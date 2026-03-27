"""Typed LLM contracts for adjudicator and extractor outputs."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, ValidationError, model_validator

from backend.world.mutations import MutationType


class ContractParseError(ValueError):
    """Raised when an LLM response cannot be parsed into a valid contract."""


class DestinationRoute(BaseModel):
    """Routing instruction emitted by the adjudicator."""

    model_config = ConfigDict(extra="forbid")

    actor: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    payload_hint: str = Field(min_length=1)


class AdjudicatorResponse(BaseModel):
    """Strict response contract for the adjudicator agent."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["approved", "rejected", "needs_clarification"]
    ruling: str = Field(min_length=1)
    destination: list[DestinationRoute] = Field(min_length=1)
    reasoning: str = Field(min_length=1)
    suggested_alternatives: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_rejection_alternatives(self) -> "AdjudicatorResponse":
        if self.status == "rejected" and not self.suggested_alternatives:
            raise ValueError("Rejected rulings must include at least one suggested alternative")
        if self.status == "approved" and not any(d.actor == "extractor" for d in self.destination):
            raise ValueError("Approved rulings must route to extractor in destination")
        return self


class ExtractorMutation(BaseModel):
    """Single mutation object emitted by the extractor agent."""

    model_config = ConfigDict(extra="forbid")

    type: MutationType
    entity_id: str | None = None
    target_id: str | None = None
    room_id: str | None = None
    to_room_id: str | None = None
    encounter_id: str | None = None
    objective_id: str | None = None
    amount: int | None = None
    condition: str | None = None
    entry: str | None = None
    is_active: bool | None = None
    is_cleared: bool | None = None

    @model_validator(mode="after")
    def _validate_type_requirements(self) -> "ExtractorMutation":
        required_by_type = {
            MutationType.MOVE_ENTITY: ["entity_id", "to_room_id"],
            MutationType.APPLY_DAMAGE: ["target_id", "amount"],
            MutationType.APPLY_HEAL: ["target_id", "amount"],
            MutationType.ADD_CONDITION: ["target_id", "condition"],
            MutationType.REMOVE_CONDITION: ["target_id", "condition"],
            MutationType.SET_ACTIVE_ENCOUNTER: ["encounter_id"],
            MutationType.SET_ENCOUNTER_ACTIVE: ["encounter_id", "is_active"],
            MutationType.SET_ENCOUNTER_CLEARED: ["encounter_id", "is_cleared"],
            MutationType.MARK_OBJECTIVE_COMPLETE: ["objective_id"],
            MutationType.MARK_OBJECTIVE_FAILED: ["objective_id"],
            MutationType.MARK_ROOM_VISITED: ["room_id"],
            MutationType.MARK_ROOM_CLEARED: ["room_id"],
            MutationType.DISARM_ROOM_TRAP: ["room_id"],
            MutationType.APPEND_LOG_ENTRY: ["entry"],
            MutationType.INCREMENT_TURN: [],
        }
        required_fields = required_by_type[self.type]
        for field_name in required_fields:
            if getattr(self, field_name) in (None, ""):
                raise ValueError(f"Mutation {self.type.value} requires field '{field_name}'")

        if self.amount is not None and self.amount < 0:
            raise ValueError("Mutation amount cannot be negative")

        return self


class ExtractorResponse(RootModel[list[ExtractorMutation]]):
    """Strict response contract for the extractor agent."""


def _extract_json_block(raw_text: str) -> str:
    """Extract JSON payload from plain text or fenced code blocks."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL)
        if not match:
            raise ContractParseError("Invalid fenced JSON block")
        return match.group(1)
    return cleaned


def parse_adjudicator_response(raw_text: str) -> AdjudicatorResponse:
    """Parse and validate adjudicator JSON output."""
    try:
        payload = json.loads(_extract_json_block(raw_text))
    except json.JSONDecodeError as exc:
        raise ContractParseError(f"Adjudicator JSON parse error: {exc}") from exc

    try:
        return AdjudicatorResponse.model_validate(payload)
    except ValidationError as exc:
        raise ContractParseError(f"Adjudicator schema validation error: {exc}") from exc


def parse_extractor_response(raw_text: str) -> ExtractorResponse:
    """Parse and validate extractor JSON output."""
    try:
        payload = json.loads(_extract_json_block(raw_text))
    except json.JSONDecodeError as exc:
        raise ContractParseError(f"Extractor JSON parse error: {exc}") from exc

    try:
        return ExtractorResponse.model_validate(payload)
    except ValidationError as exc:
        raise ContractParseError(f"Extractor schema validation error: {exc}") from exc


def dump_model_json(model: BaseModel | RootModel[Any]) -> str:
    """Serialize validated contract model for logs or tests."""
    return model.model_dump_json(indent=2)
