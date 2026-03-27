"""Typed world mutation objects consumed by the dispatcher."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class MutationType(str, Enum):
    """Supported mutation operations for deterministic world updates."""

    MOVE_ENTITY = "move_entity"
    APPLY_DAMAGE = "apply_damage"
    APPLY_HEAL = "apply_heal"
    ADD_CONDITION = "add_condition"
    REMOVE_CONDITION = "remove_condition"
    SET_ACTIVE_ENCOUNTER = "set_active_encounter"
    SET_ENCOUNTER_ACTIVE = "set_encounter_active"
    SET_ENCOUNTER_CLEARED = "set_encounter_cleared"
    MARK_OBJECTIVE_COMPLETE = "mark_objective_complete"
    MARK_OBJECTIVE_FAILED = "mark_objective_failed"
    MARK_ROOM_VISITED = "mark_room_visited"
    MARK_ROOM_CLEARED = "mark_room_cleared"
    DISARM_ROOM_TRAP = "disarm_room_trap"
    APPEND_LOG_ENTRY = "append_log_entry"
    INCREMENT_TURN = "increment_turn"
    SET_ACTIVE_ACTOR = "set_active_actor"
    SET_AWAITING_INPUT = "set_awaiting_input"
    INCREMENT_VERSION = "increment_version"


@dataclass(frozen=True)
class WorldMutation:
    """Atomic mutation object produced by adjudication/mapping layers."""

    type: MutationType
    entity_id: Optional[str] = None
    target_id: Optional[str] = None
    room_id: Optional[str] = None
    to_room_id: Optional[str] = None
    encounter_id: Optional[str] = None
    objective_id: Optional[str] = None
    amount: Optional[int] = None
    condition: Optional[str] = None
    entry: Optional[str] = None
    is_active: Optional[bool] = None
    is_cleared: Optional[bool] = None
    actor_id: Optional[str] = None  # used by SET_ACTIVE_ACTOR / SET_AWAITING_INPUT
