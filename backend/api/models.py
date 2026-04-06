"""Request and response models for the REST API."""

from pydantic import BaseModel, Field
from typing import Optional


class ActionRequest(BaseModel):
    """POST request body for /advance endpoint."""

    actor: str = Field(..., min_length=1, description="Character ID taking the turn")
    action: str = Field(..., min_length=1, description="Freetext action or question from player")


class ActionResponse(BaseModel):
    """Response model for successful action processing."""

    status: str = Field(..., description="approved, rejected, needs_clarification, or game_start")
    ruling: str = Field(..., description="DM ruling text")
    actor_id: str = Field(..., description="Character who took the action")
    awaiting_actor_id: str = Field(..., description="Character waiting for next input")
    advanced_turn: bool = Field(..., description="Whether turn advanced to next actor")
    applied_mutation_count: int = Field(..., description="Number of world mutations applied")


class OutcomeResponse(BaseModel):
    """Unified response wrapper for all action outcomes."""

    success: bool = Field(..., description="Whether request was processed successfully")
    data: Optional[ActionResponse] = Field(None, description="Action response data (only on success)")
    error: Optional[str] = Field(None, description="Error message (only on failure)")
    actor_id: Optional[str] = Field(None, description="Character ID from request (for tracking)")
