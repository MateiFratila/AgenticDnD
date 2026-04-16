"""Table orchestrator: controls turn flow, agent calls, and world mutation application."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable, Protocol

from backend.agents.contracts import (
    AdjudicatorResponse,
    ExtractorMutation,
    ExtractorResponse,
    IntentResponse,
)
from backend.orchestrator.payload_builders import (
    build_adjudicator_payload as build_adjudicator_payload_from_world,
    build_extractor_payload as build_extractor_payload_from_world,
    build_intent_payload as build_intent_payload_from_world,
)
from backend.orchestrator.snapshot_store import next_loop_index, persist_world_snapshot
from backend.orchestrator.turn_models import NpcTurnSummary, ResolvedAction, TableEvent, TableStep, TurnResult
from backend.world import EncounterTurnEntry, WorldMutation, WorldState, WorldStateDispatcher


logger = logging.getLogger(__name__)


IntentFn = Callable[[WorldState, str], IntentResponse]
AdjudicatorFn = Callable[[WorldState, str, str], AdjudicatorResponse]
ExtractorFn = Callable[[WorldState, AdjudicatorResponse], ExtractorResponse]


class IntentAgentProtocol(Protocol):
    """Minimal protocol for PC/NPC intent-generator wrappers."""

    def think_intent(self, user_input: str) -> IntentResponse:
        """Return validated intent response from LLM call."""


class AdjudicatorAgentProtocol(Protocol):
    """Minimal protocol for adjudicator agent wrappers."""

    def think_adjudication(self, user_input: str) -> AdjudicatorResponse:
        """Return validated adjudicator response from LLM call."""


class ExtractorAgentProtocol(Protocol):
    """Minimal protocol for extractor agent wrappers."""

    def think_extraction(self, user_input: str) -> ExtractorResponse:
        """Return validated extractor response from LLM call."""


class TableOrchestrator:
    """Coordinates Intent -> Adjudicator -> Extractor -> Dispatcher for table turns."""

    def __init__(
        self,
        world: WorldState,
        turn_order: list[str],
        adjudicator_fn: AdjudicatorFn,
        extractor_fn: ExtractorFn,
        intent_fn: IntentFn | None = None,
        dispatcher: WorldStateDispatcher | None = None,
        snapshot_dir: str | Path | None = "artifacts/world_snapshots",
        max_auto_npc_turns: int = 12,
        max_npc_follow_up_passes: int = 3,
        npc_turn_delay: float = 0.5,
    ):
        if not turn_order:
            raise ValueError("turn_order must contain at least one actor id")

        self.turn_order = turn_order
        self.turn_index = 0
        self.adjudicator_fn = adjudicator_fn
        self.extractor_fn = extractor_fn
        self.intent_fn = intent_fn
        self.dispatcher = dispatcher or WorldStateDispatcher()
        self.snapshot_dir = Path(snapshot_dir) if snapshot_dir is not None else None
        self.loop_index = 0
        self.current_step = TableStep.WAITING_FOR_INTENT
        self.max_auto_npc_turns = max(1, max_auto_npc_turns)
        self.max_npc_follow_up_passes = max(1, max_npc_follow_up_passes)
        self.npc_turn_delay = max(0.0, npc_turn_delay)
        self.world = world
        self._sync_active_encounter_turn_order()

        # Initialise world with session metadata so external readers
        # can always reconstruct full state from the WorldState alone.
        first_actor = self.current_actor_id
        self.world = (
            self.world
            .set_active_actor(first_actor)
            .set_awaiting_input(first_actor)
            .sync_actor_knowledge()
        )

    @classmethod
    def from_agents(
        cls,
        world: WorldState,
        turn_order: list[str],
        adjudicator_agent: AdjudicatorAgentProtocol,
        extractor_agent: ExtractorAgentProtocol,
        intent_agent: IntentAgentProtocol | None = None,
        dispatcher: WorldStateDispatcher | None = None,
        snapshot_dir: str | Path | None = "artifacts/world_snapshots",
        max_auto_npc_turns: int = 12,
        max_npc_follow_up_passes: int = 3,
        npc_turn_delay: float = 0.5,
    ) -> "TableOrchestrator":
        """Create orchestrator using agent wrappers instead of raw callback functions."""
        orchestrator: TableOrchestrator | None = None

        def intent_fn(current_world: WorldState, actor_id: str) -> IntentResponse:
            if intent_agent is None:
                raise ValueError("Intent agent is required to generate actions for empty actor input")
            payload = cls.build_intent_payload(
                current_world,
                actor_id,
                loop_index=orchestrator.loop_index if orchestrator is not None else None,
            )
            return intent_agent.think_intent(user_input=payload)

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
            intent_fn=intent_fn if intent_agent is not None else None,
            dispatcher=dispatcher,
            snapshot_dir=snapshot_dir,
            max_auto_npc_turns=max_auto_npc_turns,
            max_npc_follow_up_passes=max_npc_follow_up_passes,
            npc_turn_delay=npc_turn_delay,
        )
        return orchestrator

    @property
    def current_actor_id(self) -> str:
        """Actor id whose turn is currently active."""
        self._sync_active_encounter_turn_order()
        encounter_actor_id = self.world.get_current_encounter_actor_id()
        if encounter_actor_id is not None:
            return encounter_actor_id
        return self.turn_order[self.turn_index]

    def _sync_active_encounter_turn_order(self) -> None:
        """Keep active encounter turn order aligned with alive actors in the encounter room."""
        encounter_id = self.world.active_encounter_id
        if encounter_id is None or encounter_id not in self.world.encounters:
            return

        encounter = self.world.encounters[encounter_id]
        if encounter.is_cleared or not encounter.is_active:
            return

        room = self.world.rooms.get(encounter.room_id)

        existing_entries = [
            entry
            for entry in encounter.turn_order
            if (
                entry.actor_id in self.world.party and self.world.party[entry.actor_id].is_alive
            )
            or (
                entry.actor_id in self.world.npcs and self.world.npcs[entry.actor_id].is_alive
            )
        ]

        if encounter.turn_order:
            new_turn_order = existing_entries
            # Add any PC from the global turn order who is alive but not yet in the encounter
            # (e.g. a PC in a different room who still needs a turn to move into the fight).
            existing_ids = {entry.actor_id for entry in new_turn_order}
            for pc_id in self.turn_order:
                if (
                    pc_id not in existing_ids
                    and pc_id in self.world.party
                    and self.world.party[pc_id].is_alive
                ):
                    new_turn_order = [*new_turn_order, EncounterTurnEntry(actor_id=pc_id, initiative_roll=None)]
        else:
            candidate_actor_ids = [
                *[
                    pc_id
                    for pc_id in self.turn_order
                    if pc_id in self.world.party
                    and self.world.party[pc_id].is_alive
                ],
                *[
                    npc_id
                    for npc_id in encounter.npc_ids
                    if npc_id in self.world.npcs and self.world.npcs[npc_id].is_alive
                ],
            ]
            new_turn_order = [
                EncounterTurnEntry(actor_id=actor_id, initiative_roll=None)
                for actor_id in candidate_actor_ids
            ]

        if encounter.turn_order != new_turn_order:
            self.world = self.world.set_encounter_turn_order(encounter_id, new_turn_order)
        elif encounter.turn_order and encounter.current_turn_index >= len(encounter.turn_order):
            self.world = self.world.set_encounter_turn_index(encounter_id, encounter.current_turn_index)

    def process_intent(self, action_text: str | None, actor_id: str | None = None) -> TurnResult:
        """Process one actor intent and, for PCs, auto-resolve any active NPC turns."""
        result = self._process_single_intent(action_text, actor_id=actor_id)
        if result.actor_id not in self.world.party or not result.advanced_turn:
            return result

        npc_turns = self.resolve_npc_turns()
        final_awaiting_actor = self.world.awaiting_input_from or self.current_actor_id
        if not npc_turns and final_awaiting_actor == result.awaiting_actor_id:
            return result

        return TurnResult(
            status=result.status,
            ruling=result.ruling,
            actor_id=result.actor_id,
            awaiting_actor_id=final_awaiting_actor,
            advanced_turn=result.advanced_turn,
            applied_mutation_count=result.applied_mutation_count,
            events=result.events,
            generated_action=result.generated_action,
            resolved_action=result.resolved_action,
            npc_turns=npc_turns,
        )

    def _resolve_action(self, actor_id: str, action_text: str | None) -> ResolvedAction:
        """Normalize player-provided or agent-generated input into one internal action contract."""
        self.world = self.world.sync_actor_knowledge([actor_id])
        submitted_action = (action_text or "").strip()
        if submitted_action:
            return ResolvedAction(
                actor_id=actor_id,
                action=submitted_action,
                source="player",
            )

        if self.intent_fn is None:
            raise ValueError(f"Empty action received for actor '{actor_id}' but no intent agent is configured")

        intent = self.intent_fn(self.world, actor_id)
        generated_action = intent.intent.strip()
        if not generated_action:
            raise ValueError(f"Intent agent returned an empty action for actor '{actor_id}'")

        logger.info("[TABLE] Generated action intent | actor=%s | action=%s", actor_id, generated_action)
        return ResolvedAction(
            actor_id=actor_id,
            action=generated_action,
            source="intent_agent",
            in_character_note=intent.in_character_note or None,
            reasoning=intent.reasoning,
        )

    def _process_single_intent(self, action_text: str | None, actor_id: str | None = None) -> TurnResult:
        """Process one actor intent through adjudication/extraction without recursive NPC chaining."""
        self._sync_active_encounter_turn_order()
        actor_id = actor_id or self.world.active_actor_id or self.current_actor_id
        self.loop_index = self._next_loop_index()
        resolved_action = self._resolve_action(actor_id, action_text)
        generated_action = resolved_action.action if resolved_action.source == "intent_agent" else None

        events: list[TableEvent] = []

        self.world = self.world.set_active_actor(actor_id).set_awaiting_input(None)

        self._transition(
            to_step=TableStep.ADJUDICATING,
            actor_id=actor_id,
            detail="Received actor intent and started adjudication",
            events=events,
        )

        adjudication = self.adjudicator_fn(self.world, actor_id, resolved_action.action)
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

        correction_attempts = 0
        max_correction_attempts = 2

        while True:
            follow_up_actor = self._resolve_follow_up_actor(adjudication, actor_id)
            should_wait_for_response = (
                adjudication.requires_player_response
                or adjudication.status in {"rejected", "needs_clarification"}
                or follow_up_actor is not None
            )
            if should_wait_for_response:
                awaiting_actor = follow_up_actor or actor_id
                result_status = adjudication.status
                if result_status == "approved" and awaiting_actor == actor_id:
                    result_status = "needs_clarification"

                self.world = self.world.set_active_actor(awaiting_actor).set_awaiting_input(awaiting_actor)
                self._transition(
                    to_step=TableStep.WAITING_FOR_INTENT,
                    actor_id=awaiting_actor,
                    detail="No world changes committed; waiting for new actor input",
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
                    generated_action=generated_action,
                    resolved_action=resolved_action,
                )
                self._persist_world_snapshot(actor_id)
                return result

            should_extract = (
                adjudication.status in {"approved", "game_start"}
                and any(route.actor == "extractor" for route in adjudication.destination)
            )

            if not should_extract:
                self._advance_turn(actor_id)
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
                    generated_action=generated_action,
                    resolved_action=resolved_action,
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

            extractor_feedback = self._extract_extractor_feedback(mutations)
            if extractor_feedback is not None:
                correction_attempts += 1
                if correction_attempts > max_correction_attempts:
                    self.world = self.world.add_log_entry(
                        f"[TABLE][FAILSAFE] Extractor correction loop exhausted for actor={actor_id}: {extractor_feedback}"
                    )
                    adjudication = AdjudicatorResponse(
                        status="needs_clarification",
                        ruling="The action cannot be resolved cleanly yet. Provide the missing roll, result, or clarification.",
                        destination=[
                            {
                                "actor": actor_id,
                                "purpose": "Clarify the unresolved action",
                                "payload_hint": extractor_feedback,
                            }
                        ],
                        reasoning="Extractor could not safely commit the approved ruling after repeated correction attempts.",
                        requires_player_response=True,
                        follow_up_actor=actor_id,
                        suggested_alternatives=[],
                    )
                else:
                    self._transition(
                        to_step=TableStep.ADJUDICATING,
                        actor_id=actor_id,
                        detail="Extractor requested adjudication correction",
                        events=events,
                    )
                    adjudication = self._request_adjudication_correction(
                        actor_id=actor_id,
                        action_text=resolved_action.action,
                        adjudication=adjudication,
                        extractor_feedback=extractor_feedback,
                    )
                    logger.info(
                        "[TABLE] Adjudicator correction response | actor=%s | status=%s | destination=%s",
                        actor_id,
                        adjudication.status,
                        [route.actor for route in adjudication.destination],
                    )

                self.world = self.world.add_log_entry(
                    self._format_adjudication_log_entry(
                        actor_id,
                        adjudication,
                        is_first_entry=False,
                    )
                )
                continue

            self._transition(
                to_step=TableStep.APPLYING_MUTATIONS,
                actor_id=actor_id,
                detail=f"Applying {len(mutations)} mutations to world state",
                events=events,
            )

            self.world = self.dispatcher.apply_mutations(self.world, mutations)
            self._sync_active_encounter_turn_order()

            self._advance_turn(actor_id)
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
                generated_action=generated_action,
                resolved_action=resolved_action,
            )
            self._persist_world_snapshot(actor_id)
            return result

    def resolve_npc_turns(self, max_auto_turns: int | None = None) -> list[NpcTurnSummary]:
        """Auto-resolve encounter NPC turns until a PC is awaited again, subject to multi-pass failsafes."""
        if self.intent_fn is None or self.world.active_encounter_id is None:
            return []

        self._sync_active_encounter_turn_order()
        encounter = self.world.encounters.get(self.world.active_encounter_id)
        if encounter is None or encounter.is_cleared or not encounter.turn_order:
            return []

        combatant_count = max(1, len(encounter.turn_order))
        total_pass_limit = (
            max_auto_turns
            if max_auto_turns is not None
            else min(self.max_auto_npc_turns, max(6, combatant_count * 3))
        )
        npc_turns: list[NpcTurnSummary] = []
        total_passes = 0

        while total_passes < total_pass_limit:
            next_actor_id = self.current_actor_id
            if next_actor_id in self.world.party:
                break
            if next_actor_id not in self.world.npcs:
                break

            npc = self.world.npcs.get(next_actor_id)
            if npc is None or not npc.is_alive:
                self._advance_turn(next_actor_id)
                continue

            turn_result: TurnResult | None = None
            follow_up_passes = 0
            repeated_action_count = 0
            last_action = None
            start_fingerprint = self._state_fingerprint()

            while total_passes < total_pass_limit and follow_up_passes < self.max_npc_follow_up_passes:
                turn_result = self._process_single_intent("", actor_id=next_actor_id)
                total_passes += 1
                follow_up_passes += 1

                current_action = (
                    turn_result.resolved_action.action
                    if turn_result.resolved_action is not None
                    else turn_result.generated_action or ""
                )
                if turn_result.status in {"rejected", "needs_clarification"} and current_action == last_action:
                    repeated_action_count += 1
                else:
                    repeated_action_count = 0
                last_action = current_action

                if turn_result.advanced_turn:
                    break

                follow_up_actor = turn_result.awaiting_actor_id
                follow_up_is_npc = follow_up_actor in self.world.npcs
                if turn_result.status in {"rejected", "needs_clarification"} and follow_up_is_npc:
                    if repeated_action_count >= 1:
                        self._log_npc_failsafe(
                            "NPC auto-resolution stopped because the same unresolved action repeated "
                            f"for actor={follow_up_actor}."
                        )
                        break
                    next_actor_id = follow_up_actor
                    continue

                logger.warning(
                    "[TABLE] NPC auto-resolution paused because actor=%s returned status=%s",
                    next_actor_id,
                    turn_result.status,
                )
                break

            if turn_result is None:
                break

            if self.npc_turn_delay > 0 and self.current_actor_id in self.world.npcs:
                time.sleep(self.npc_turn_delay)

            npc_turns.append(
                NpcTurnSummary(
                    actor_id=turn_result.actor_id,
                    generated_action=(
                        turn_result.resolved_action.action
                        if turn_result.resolved_action is not None
                        else turn_result.generated_action or ""
                    ),
                    status=turn_result.status,
                    ruling=turn_result.ruling,
                    advanced_turn=turn_result.advanced_turn,
                    applied_mutation_count=turn_result.applied_mutation_count,
                )
            )

            end_fingerprint = self._state_fingerprint()
            if end_fingerprint == start_fingerprint:
                self._log_npc_failsafe(
                    f"NPC auto-resolution stopped after actor={turn_result.actor_id} made no observable progress."
                )
                break

            if not turn_result.advanced_turn:
                if follow_up_passes >= self.max_npc_follow_up_passes and turn_result.awaiting_actor_id in self.world.npcs:
                    self._log_npc_failsafe(
                        "NPC auto-resolution stopped after "
                        f"{follow_up_passes} follow-up passes for actor={turn_result.awaiting_actor_id}."
                    )
                break

        if total_passes >= total_pass_limit and self.current_actor_id in self.world.npcs:
            self._log_npc_failsafe(
                f"NPC auto-resolution stopped after {total_passes} internal passes (limit={total_pass_limit})."
            )

        return npc_turns

    def _state_fingerprint(self) -> tuple[object, ...]:
        """Return a compact fingerprint for loop-safety checks during auto-resolution."""
        encounter = (
            self.world.encounters.get(self.world.active_encounter_id)
            if self.world.active_encounter_id is not None
            else None
        )
        return (
            self.world.active_actor_id,
            self.world.awaiting_input_from,
            self.world.active_encounter_id,
            self.turn_index,
            encounter.current_turn_index if encounter is not None else None,
            encounter.round_count if encounter is not None else None,
            self.world.turn_count,
            self.world.world_version,
        )

    def _log_npc_failsafe(self, detail: str) -> None:
        """Log and persist a standard failsafe marker for NPC auto-resolution stops."""
        logger.warning("[TABLE][FAILSAFE] %s", detail)
        self.world = self.world.add_log_entry(f"[TABLE][FAILSAFE] {detail}")

    def _is_turn_order_actor(self, actor_id: str) -> bool:
        """Return True when the actor participates in the external PC turn order."""
        return actor_id in self.turn_order

    def _persist_world_snapshot(self, actor_id: str) -> None:
        """Persist current world state to disk for post-turn inspection."""
        self.world = self.world.sync_actor_knowledge()
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

    def _advance_turn(self, actor_id: str | None = None) -> None:
        """Move to the next actor in encounter order when active, else in the global PC order."""
        self._sync_active_encounter_turn_order()
        encounter_id = self.world.active_encounter_id
        if encounter_id is not None and encounter_id in self.world.encounters:
            encounter = self.world.encounters[encounter_id]
            if (
                encounter.is_active
                and not encounter.is_cleared
                and encounter.turn_order
                and (actor_id is None or any(entry.actor_id == actor_id for entry in encounter.turn_order))
            ):
                self.world = self.world.advance_encounter_turn(encounter_id)
                self._sync_active_encounter_turn_order()
                return

        if actor_id is None or actor_id in self.turn_order:
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
        """Return the explicitly routed actor who should respond next, if any."""
        if adjudication.follow_up_actor:
            return adjudication.follow_up_actor

        for route in adjudication.destination:
            if route.actor != "extractor":
                return route.actor

        if adjudication.requires_player_response:
            return default_actor

        return None

    @staticmethod
    def _extract_extractor_feedback(mutations: list[WorldMutation]) -> str | None:
        """Return structured extractor failure feedback when a needs_revision entry is present.

        A needs_revision entry always triggers re-adjudication regardless of other mutations in
        the batch. The safe partial mutations are discarded here; the corrected adjudicator ruling
        will cause the extractor to re-emit them alongside the previously missing details.
        """
        for mutation in mutations:
            if (
                mutation.type == "append_log_entry"
                and mutation.entry
                and (
                    mutation.entry.startswith("[EXTRACTOR][needs_revision]")
                    or mutation.entry.startswith("[EXTRACTOR] Extraction failed")
                )
            ):
                return mutation.entry
        return None

    def _request_adjudication_correction(
        self,
        actor_id: str,
        action_text: str,
        adjudication: AdjudicatorResponse,
        extractor_feedback: str,
    ) -> AdjudicatorResponse:
        """Re-ask the adjudicator to revise a ruling that the extractor could not safely commit."""
        correction_request = (
            f"{action_text}\n\n"
            "[EXTRACTOR_FEEDBACK]\n"
            f"Previous ruling: {adjudication.ruling}\n"
            f"Extractor feedback: {extractor_feedback}\n"
            "Revise the ruling so it either includes a concrete canonical outcome for extraction "
            "or returns needs_clarification/rejected if more input is still required."
        )
        return self.adjudicator_fn(self.world, actor_id, correction_request)

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
            item=getattr(mutation, "item", None),
            condition=mutation.condition,
            entry=mutation.entry,
            is_active=mutation.is_active,
            is_cleared=mutation.is_cleared,
            actor_id=getattr(mutation, "actor_id", None),
            turn_index=getattr(mutation, "turn_index", None),
            turn_order=getattr(mutation, "turn_order", None),
        )

    @staticmethod
    def build_intent_payload(
        world: WorldState,
        actor_id: str,
        loop_index: int | None = None,
    ) -> str:
        """Build the intent-generator payload from a scoped world-state view."""
        return build_intent_payload_from_world(
            world,
            actor_id,
            loop_index=loop_index,
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
