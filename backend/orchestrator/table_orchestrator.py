"""Table orchestrator: controls turn flow, agent calls, and world mutation application."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import json
import logging
from pathlib import Path
from typing import Callable, Protocol

from backend.agents.contracts import AdjudicatorResponse, ExtractorMutation, ExtractorResponse
from backend.world import WorldMutation, WorldState, WorldStateDispatcher


logger = logging.getLogger(__name__)


class TableStep(str, Enum):
    """State machine steps for a single table turn."""

    WAITING_FOR_INTENT = "waiting_for_intent"
    ADJUDICATING = "adjudicating"
    EXTRACTING = "extracting"
    APPLYING_MUTATIONS = "applying_mutations"
    TURN_COMPLETE = "turn_complete"


@dataclass(frozen=True)
class TableEvent:
    """Structured orchestrator event for transition/debug logging."""

    from_step: TableStep
    to_step: TableStep
    actor_id: str
    detail: str


@dataclass(frozen=True)
class TurnResult:
    """Result of one orchestrator turn cycle."""

    status: str
    ruling: str
    actor_id: str
    awaiting_actor_id: str
    advanced_turn: bool
    applied_mutation_count: int
    events: list[TableEvent] = field(default_factory=list)


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

        def adjudicator_fn(
            current_world: WorldState,
            actor_id: str,
            action_text: str,
        ) -> AdjudicatorResponse:
            payload = cls.build_adjudicator_payload(current_world, actor_id, action_text)
            return adjudicator_agent.think_adjudication(user_input=payload)

        def extractor_fn(
            current_world: WorldState,
            adjudication: AdjudicatorResponse,
        ) -> ExtractorResponse:
            payload = cls.build_extractor_payload(current_world, adjudication)
            return extractor_agent.think_extraction(user_input=payload)

        return cls(
            world=world,
            turn_order=turn_order,
            adjudicator_fn=adjudicator_fn,
            extractor_fn=extractor_fn,
            dispatcher=dispatcher,
            snapshot_dir=snapshot_dir,
        )

    @property
    def current_actor_id(self) -> str:
        """Actor id whose turn is currently active."""
        return self.turn_order[self.turn_index]

    def process_intent(self, action_text: str) -> TurnResult:
        """Process one player intent and return turn outcome with transition events."""
        # Always read the acting actor from world state — it is the single source of truth.
        actor_id = self.world.active_actor_id or self.current_actor_id
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

        if adjudication.status in {"rejected", "needs_clarification"}:
            # No world changes. Record that we're still waiting on the same actor.
            self.world = self.world.set_awaiting_input(actor_id)
            self._transition(
                to_step=TableStep.WAITING_FOR_INTENT,
                actor_id=actor_id,
                detail="No world changes committed; waiting for new player input",
                events=events,
            )
            result = TurnResult(
                status=adjudication.status,
                ruling=adjudication.ruling,
                actor_id=actor_id,
                awaiting_actor_id=actor_id,
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
        if self.snapshot_dir is None:
            return

        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.loop_index = self._next_loop_index()
        file_path = self.snapshot_dir / (
            f"session_{self.world.game_session_id}_"
            f"loop_{self.loop_index:04d}_"
            f"turn_{self.world.turn_count:04d}_"
            f"v_{self.world.world_version:04d}_"
            f"actor_{actor_id}.json"
        )
        file_path.write_text(json.dumps(asdict(self.world), indent=2), encoding="utf-8")
        logger.info("[TABLE] Snapshot persisted | path=%s", file_path)

    def _next_loop_index(self) -> int:
        """Find the next loop index for this game session."""
        if self.snapshot_dir is None or not self.snapshot_dir.exists():
            return 1

        prefix = f"session_{self.world.game_session_id}_loop_"
        max_loop = 0
        for snapshot_path in self.snapshot_dir.glob(f"session_{self.world.game_session_id}_loop_*.json"):
            name = snapshot_path.name
            if not name.startswith(prefix):
                continue
            loop_token = name[len(prefix): len(prefix) + 4]
            if loop_token.isdigit():
                max_loop = max(max_loop, int(loop_token))

        return max_loop + 1

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
    def build_adjudicator_payload(world: WorldState, actor_id: str, action_text: str) -> str:
        """Helper to build a compact JSON payload for adjudicator prompts."""
        actor = world.party.get(actor_id)
        payload = {
            "actor_id": actor_id,
            "action": action_text,
            "actor_state": {
                "name": actor.name if actor else actor_id,
                "hp_current": actor.hp_current if actor else None,
                "hp_max": actor.hp_max if actor else None,
                "position": actor.position if actor else None,
                "conditions": actor.conditions if actor else [],
            },
            "active_encounter_id": world.active_encounter_id,
            "turn_count": world.turn_count,
        }
        return json.dumps(payload, indent=2)

    @staticmethod
    def build_extractor_payload(
        world: WorldState,
        adjudication: AdjudicatorResponse,
    ) -> str:
        """Helper to build extractor payload with ruling and world context."""
        payload = {
            "adjudication": adjudication.model_dump(),
            "world_state": {
                "active_encounter_id": world.active_encounter_id,
                "turn_count": world.turn_count,
                "party": {
                    pc_id: {
                        "name": pc.name,
                        "position": pc.position,
                        "hp_current": pc.hp_current,
                        "hp_max": pc.hp_max,
                        "conditions": pc.conditions,
                    }
                    for pc_id, pc in world.party.items()
                },
            },
        }
        return json.dumps(payload, indent=2)
