"""Turn-state models used by the table orchestrator."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


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
