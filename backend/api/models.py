"""Request and response models for the REST API."""

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class AdvanceActorRequest(BaseModel):
    """Nested actor payload accepted by POST /advance."""

    actor_id: str = Field(..., min_length=1, description="Character ID taking the turn")
    action: Optional[str] = Field(
        default=None,
        description="Freetext action or question from the player; leave it blank or null to have the intent agent generate it.",
    )


class ActionRequest(BaseModel):
    """POST request body for /advance endpoint."""

    actor: AdvanceActorRequest = Field(
        ...,
        description="Nested actor payload containing the acting character and optional action text.",
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_payload(cls, data: object) -> object:
        """Accept the legacy flat payload while preferring the nested actor contract."""
        if isinstance(data, dict) and isinstance(data.get("actor"), str):
            return {
                "actor": {
                    "actor_id": data["actor"],
                    "action": data.get("action"),
                }
            }
        return data


class NpcTurnResponse(BaseModel):
    """Compact summary of one NPC turn auto-resolved during the request."""

    actor_id: str = Field(..., description="NPC actor who took the turn")
    generated_action: str = Field(..., description="Intent text generated for the NPC")
    status: str = Field(..., description="Outcome status of the NPC turn")
    ruling: str = Field(..., description="Adjudicator ruling for the NPC turn")
    advanced_turn: bool = Field(..., description="Whether that NPC turn completed successfully")
    applied_mutation_count: int = Field(..., description="World mutations committed during the NPC turn")


class ResolvedActionResponse(BaseModel):
    """API-safe representation of the normalized action that was processed."""

    actor_id: str = Field(..., description="Character whose action was resolved")
    action: str = Field(..., description="The effective action text that was actually processed")
    source: Literal["player", "intent_agent"] = Field(
        ...,
        description="Whether the action came directly from the player or from the intent agent.",
    )
    in_character_note: Optional[str] = Field(
        default=None,
        description="Optional in-character flavor note returned by the intent agent.",
    )
    reasoning: Optional[str] = Field(
        default=None,
        description="Optional short explanation for why that action was chosen.",
    )


class ActionResponse(BaseModel):
    """Response model for successful action processing."""

    status: str = Field(..., description="approved, rejected, needs_clarification, or game_start")
    ruling: str = Field(..., description="DM ruling text")
    actor: ResolvedActionResponse = Field(
        ...,
        description="The full normalized actor/action payload that was actually processed.",
    )
    actor_id: str = Field(..., description="Character who took the action")
    awaiting_actor_id: str = Field(..., description="Character waiting for next input")
    advanced_turn: bool = Field(..., description="Whether turn advanced to next actor")
    applied_mutation_count: int = Field(..., description="Number of world mutations applied")
    npc_turns: list[NpcTurnResponse] = Field(
        default_factory=list,
        description="NPC turns auto-resolved between the initiating player action and the response.",
    )


class OutcomeResponse(BaseModel):
    """Unified response wrapper for all action outcomes."""

    success: bool = Field(..., description="Whether request was processed successfully")
    data: Optional[ActionResponse] = Field(None, description="Action response data (only on success)")
    error: Optional[str] = Field(None, description="Error message (only on failure)")
    actor_id: Optional[str] = Field(None, description="Character ID from request (for tracking)")
