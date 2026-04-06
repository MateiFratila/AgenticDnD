"""Table orchestrator: controls turn flow, agent calls, and world mutation application."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Protocol

from backend.agents.contracts import AdjudicatorResponse, ExtractorMutation, ExtractorResponse
from backend.orchestrator.payload_builders import (
    build_adjudicator_payload as build_adjudicator_payload_from_world,
    build_extractor_payload as build_extractor_payload_from_world,
)
from backend.orchestrator.snapshot_store import next_loop_index, persist_world_snapshot
from backend.orchestrator.turn_models import TableEvent, TableStep, TurnResult
from backend.world import WorldMutation, WorldState, WorldStateDispatcher


logger = logging.getLogger(__name__)


AdjudicatorFn = Callable[[WorldState, str, str], AdjudicatorResponse]
ExtractorFn = Callable[[WorldState, AdjudicatorResponse], ExtractorResponse]


class AdjudicatorAgentProtocol(Protocol):
    """Minimal protocol for adjudicator agent wrappers."""

    def think_adjudication(self, user_input: str) -> AdjudicatorResponse:
        """Return validated adjudicator response from LLM call."""


class ExtractorAgentProtocol(Protocol):
    """Minimal protocol for extractor agent wrappers."""

    def think_extraction(self, user_input: str) -> ExtractorResponse:
        """Return validated extractor response from LLM call."""


class TableOrchestrator:
    """Coordinates Adjudicator -> Extractor -> Dispatcher for table turns."""

    def __init__(
        self,
        world: WorldState,
        turn_order: list[str],
        adjudicator_fn: AdjudicatorFn,
        extractor_fn: ExtractorFn,
        dispatcher: WorldStateDispatcher | None = None,
        snapshot_dir: str | Path | None = "artifacts/world_snapshots",
    ):
        if not turn_order:
            raise ValueError("turn_order must contain at least one actor id")

        self.turn_order = turn_order
        self.turn_index = 0
        self.adjudicator_fn = adjudicator_fn
        self.extractor_fn = extractor_fn
        self.dispatcher = dispatcher or WorldStateDispatcher()
        self.snapshot_dir = Path(snapshot_dir) if snapshot_dir is not None else None
        self.loop_index = 0
        self.current_step = TableStep.WAITING_FOR_INTENT

        # Initialise world with session metadata so external readers
        # can always reconstruct full state from the WorldState alone.
        first_actor = turn_order[0]
        self.world = (
            world
            .set_active_actor(first_actor)
            .set_awaiting_input(first_actor)
        )

    @classmethod
    def from_agents(
        cls,
        world: WorldState,
        turn_order: list[str],
        adjudicator_agent: AdjudicatorAgentProtocol,
        extractor_agent: ExtractorAgentProtocol,
        dispatcher: WorldStateDispatcher | None = None,
        snapshot_dir: str | Path | None = "artifacts/world_snapshots",
    ) -> "TableOrchestrator":
        """Create orchestrator using agent wrappers instead of raw callback functions."""
        orchestrator: TableOrchestrator | None = None

        def adjudicator_fn(
            current_world: WorldState,
            actor_id: str,
            action_text: str,
        ) -> AdjudicatorResponse:
            payload = cls.build_adjudicator_payload(
                current_world,
                actor_id,
                action_text,
                loop_index=orchestrator.loop_index if orchestrator is not None else None,
            )
            return adjudicator_agent.think_adjudication(user_input=payload)

        def extractor_fn(
            current_world: WorldState,
            adjudication: AdjudicatorResponse,
        ) -> ExtractorResponse:
            payload = cls.build_extractor_payload(
                current_world,
                adjudication,
                loop_index=orchestrator.loop_index if orchestrator is not None else None,
            )
            return extractor_agent.think_extraction(user_input=payload)

        orchestrator = cls(
            world=world,
            turn_order=turn_order,
            adjudicator_fn=adjudicator_fn,
            extractor_fn=extractor_fn,
            dispatcher=dispatcher,
            snapshot_dir=snapshot_dir,
        )
        return orchestrator

    @property
    def current_actor_id(self) -> str:
        """Actor id whose turn is currently active."""
        return self.turn_order[self.turn_index]

    def process_intent(self, action_text: str) -> TurnResult:
        """Process one player intent and return turn outcome with transition events."""
        # Always read the acting actor from world state — it is the single source of truth.
        actor_id = self.world.active_actor_id or self.current_actor_id
        self.loop_index = self._next_loop_index()
        events: list[TableEvent] = []

        # Mark actor as active in world state before any LLM call.
        self.world = (
            self.world
            .set_active_actor(actor_id)
            .set_awaiting_input(None)
        )

        self._transition(
            to_step=TableStep.ADJUDICATING,
            actor_id=actor_id,
            detail="Received player intent and started adjudication",
            events=events,
        )

        adjudication = self.adjudicator_fn(self.world, actor_id, action_text)
        logger.info(
            "[TABLE] Adjudicator response | actor=%s | status=%s | destination=%s",
            actor_id,
            adjudication.status,
            [route.actor for route in adjudication.destination],
        )
        self.world = self.world.add_log_entry(
            self._format_adjudication_log_entry(
                actor_id,
                adjudication,
                is_first_entry=not self.world.turn_log,
            )
        )

        follow_up_actor = self._resolve_follow_up_actor(adjudication, actor_id)
        if adjudication.status in {"rejected", "needs_clarification"} or follow_up_actor is not None:
            awaiting_actor = follow_up_actor or actor_id
            result_status = adjudication.status
            if result_status == "approved" and awaiting_actor == actor_id:
                result_status = "needs_clarification"

            self.world = (
                self.world
                .set_active_actor(awaiting_actor)
                .set_awaiting_input(awaiting_actor)
            )
            self._transition(
                to_step=TableStep.WAITING_FOR_INTENT,
                actor_id=awaiting_actor,
                detail="No world changes committed; waiting for new player input",
                events=events,
            )
            result = TurnResult(
                status=result_status,
                ruling=adjudication.ruling,
                actor_id=actor_id,
                awaiting_actor_id=awaiting_actor,
                advanced_turn=False,
                applied_mutation_count=0,
                events=events,
            )
            self._persist_world_snapshot(actor_id)
            return result

        should_extract = any(route.actor == "extractor" for route in adjudication.destination)

        if not should_extract:
            self._advance_turn()
            next_actor = self.current_actor_id
            self.world = (
                self.world
                .set_active_actor(next_actor)
                .set_awaiting_input(next_actor)
                .increment_version()
            )
            self._transition(
                to_step=TableStep.TURN_COMPLETE,
                actor_id=actor_id,
                detail="Approved with no extractor routing; advancing turn",
                events=events,
            )
            self._transition(
                to_step=TableStep.WAITING_FOR_INTENT,
                actor_id=next_actor,
                detail="Waiting for next actor intent",
                events=events,
            )
            result = TurnResult(
                status=adjudication.status,
                ruling=adjudication.ruling,
                actor_id=actor_id,
                awaiting_actor_id=next_actor,
                advanced_turn=True,
                applied_mutation_count=0,
                events=events,
            )
            self._persist_world_snapshot(actor_id)
            return result

        self._transition(
            to_step=TableStep.EXTRACTING,
            actor_id=actor_id,
            detail="Routing approved ruling to extractor",
            events=events,
        )
        extractor_response = self.extractor_fn(self.world, adjudication)

        mutations = [self._to_world_mutation(item) for item in extractor_response.root]

        self._transition(
            to_step=TableStep.APPLYING_MUTATIONS,
            actor_id=actor_id,
            detail=f"Applying {len(mutations)} mutations to world state",
            events=events,
        )

        self.world = self.dispatcher.apply_mutations(self.world, mutations)

        self._advance_turn()
        next_actor = self.current_actor_id
        # Commit session metadata and bump version after a successful turn.
        self.world = (
            self.world
            .set_active_actor(next_actor)
            .set_awaiting_input(next_actor)
            .increment_version()
        )

        self._transition(
            to_step=TableStep.TURN_COMPLETE,
            actor_id=actor_id,
            detail="Mutations committed and turn advanced",
            events=events,
        )
        self._transition(
            to_step=TableStep.WAITING_FOR_INTENT,
            actor_id=next_actor,
            detail="Waiting for next actor intent",
            events=events,
        )

        result = TurnResult(
            status=adjudication.status,
            ruling=adjudication.ruling,
            actor_id=actor_id,
            awaiting_actor_id=next_actor,
            advanced_turn=True,
            applied_mutation_count=len(mutations),
            events=events,
        )
        self._persist_world_snapshot(actor_id)
        return result

    def _persist_world_snapshot(self, actor_id: str) -> None:
        """Persist current world state to disk for post-turn inspection."""
        if self.loop_index <= 0:
            self.loop_index = self._next_loop_index()
        persist_world_snapshot(
            self.world,
            actor_id=actor_id,
            snapshot_dir=self.snapshot_dir,
            loop_index=self.loop_index,
        )

    def _next_loop_index(self) -> int:
        """Find the next loop index for this game session."""
        return next_loop_index(self.snapshot_dir, self.world.game_session_id)

    def _advance_turn(self) -> None:
        """Move to the next actor in turn order."""
        self.turn_index = (self.turn_index + 1) % len(self.turn_order)

    def _transition(
        self,
        to_step: TableStep,
        actor_id: str,
        detail: str,
        events: list[TableEvent],
    ) -> None:
        """Record and log a state machine transition."""
        event = TableEvent(
            from_step=self.current_step,
            to_step=to_step,
            actor_id=actor_id,
            detail=detail,
        )
        events.append(event)
        logger.info(
            "[TABLE] Step transition | from=%s | to=%s | actor=%s | detail=%s",
            event.from_step.value,
            event.to_step.value,
            event.actor_id,
            event.detail,
        )
        self.current_step = to_step

    @staticmethod
    def _format_adjudication_log_entry(
        actor_id: str,
        adjudication: AdjudicatorResponse,
        is_first_entry: bool = False,
    ) -> str:
        """Create a compact DM history line for future adjudicator context."""
        status_label = "game_start" if is_first_entry else adjudication.status
        entry = f"[DM][{status_label}][{actor_id}] {adjudication.ruling}"
        if adjudication.suggested_alternatives:
            alternatives = " | ".join(adjudication.suggested_alternatives)
            entry = f"{entry} Alternatives: {alternatives}"
        return entry

    @staticmethod
    def _resolve_follow_up_actor(
        adjudication: AdjudicatorResponse,
        default_actor: str,
    ) -> str | None:
        """Return the actor who still needs to respond when a ruling is unresolved."""
        for route in adjudication.destination:
            if route.actor != "extractor":
                return route.actor

        text = f"{adjudication.ruling} {adjudication.reasoning}".lower()
        pending_markers = (
            "roll ",
            "make a ",
            "saving throw",
            "skill check",
            "ability check",
            "dc ",
            "to determine if",
            "to determine whether",
        )
        if any(marker in text for marker in pending_markers):
            return default_actor

        return None

    @staticmethod
    def _to_world_mutation(mutation: ExtractorMutation) -> WorldMutation:
        """Convert validated extractor mutation to dispatcher mutation dataclass."""
        return WorldMutation(
            type=mutation.type,
            entity_id=mutation.entity_id,
            target_id=mutation.target_id,
            room_id=mutation.room_id,
            to_room_id=mutation.to_room_id,
            encounter_id=mutation.encounter_id,
            objective_id=mutation.objective_id,
            amount=mutation.amount,
            condition=mutation.condition,
            entry=mutation.entry,
            is_active=mutation.is_active,
            is_cleared=mutation.is_cleared,
            actor_id=getattr(mutation, "actor_id", None),
        )

    @staticmethod
    def build_adjudicator_payload(
        world: WorldState,
        actor_id: str,
        action_text: str,
        loop_index: int | None = None,
    ) -> str:
        """Build the adjudicator payload from a scoped world-state view."""
        return build_adjudicator_payload_from_world(
            world,
            actor_id,
            action_text,
            loop_index=loop_index,
        )

    @staticmethod
    def build_extractor_payload(
        world: WorldState,
        adjudication: AdjudicatorResponse,
        loop_index: int | None = None,
    ) -> str:
        """Build the extractor payload from the current world state and ruling."""
        return build_extractor_payload_from_world(
            world,
            adjudication,
            loop_index=loop_index,
        )
