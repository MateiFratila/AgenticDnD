"""REST API routes for table orchestration."""

import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException, status

from backend.agents import BaseAgent
from backend.api.models import ActionRequest, OutcomeResponse, ActionResponse
from backend.orchestrator.table_orchestrator import TableOrchestrator
from backend.world import AdventureLoader

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["game"])

# Global state holder: set by app lifespan context manager
_state = {"orchestrator": None, "session_id": None}


def _project_root() -> Path:
    """Return repository root path."""
    return Path(__file__).resolve().parents[2]


def _snapshot_dir() -> Path:
    """Return world snapshot directory path."""
    return _project_root() / "artifacts" / "world_snapshots"


def _assets_dir() -> Path:
    """Return assets directory path."""
    return _project_root() / "assets"


def _clear_world_snapshots(snapshot_dir: Path) -> int:
    """Delete all persisted world snapshot files and return deleted count."""
    if not snapshot_dir.exists():
        return 0

    deleted_count = 0
    for snapshot_path in snapshot_dir.glob("*loop_*.json"):
        snapshot_path.unlink()
        deleted_count += 1
    return deleted_count


def _build_fresh_orchestrator(snapshot_dir: Path) -> TableOrchestrator:
    """Build a new orchestrator from source assets only."""
    loader = AdventureLoader(_assets_dir(), snapshot_dir=snapshot_dir)

    world = loader.load_adventure(
        adventure_file="adventure_sunken_grotto.json",
        pc_files=["pc_aldric_stonehammer.json", "pc_sylara_nightveil.json"],
        rules_file="homebrew_rules.json",
    )

    adjudicator_agent = BaseAgent(
        agent_type="adjudicator",
        agent_name="Adjudicator",
    )

    extractor_agent = BaseAgent(
        agent_type="extractor",
        agent_name="Extractor",
    )

    return TableOrchestrator.from_agents(
        world=world,
        turn_order=list(world.party.keys()),
        adjudicator_agent=adjudicator_agent,
        extractor_agent=extractor_agent,
        snapshot_dir=snapshot_dir,
    )


def set_orchestrator(orchestrator: TableOrchestrator, session_id: str) -> None:
    """Set the active orchestrator instance (called during app startup)."""
    _state["orchestrator"] = orchestrator
    _state["session_id"] = session_id


def get_orchestrator() -> TableOrchestrator:
    """Get the active orchestrator, raising if not initialized."""
    if _state["orchestrator"] is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Game engine not initialized",
        )
    return _state["orchestrator"]


@router.post("/init")
async def init_game() -> dict:
    """Reset persisted state, reload a fresh world, and trigger adventure kickoff."""
    try:
        snapshot_dir = _snapshot_dir()
        deleted_snapshots = _clear_world_snapshots(snapshot_dir)

        orchestrator = _build_fresh_orchestrator(snapshot_dir)
        set_orchestrator(orchestrator, orchestrator.world.game_session_id)

        kickoff_result = orchestrator.process_intent(
            "Adventure Start: Establish the opening scene and immediate objective for the party."
        )

        logger.info(
            "[API] Game initialized | session_id=%s | deleted_snapshots=%s | kickoff_status=%s",
            orchestrator.world.game_session_id,
            deleted_snapshots,
            kickoff_result.status,
        )

        return {
            "success": True,
            "session_id": orchestrator.world.game_session_id,
            "deleted_snapshots": deleted_snapshots,
            "kickoff": {
                "status": kickoff_result.status,
                "ruling": kickoff_result.ruling,
                "actor_id": kickoff_result.actor_id,
                "awaiting_actor_id": kickoff_result.awaiting_actor_id,
                "advanced_turn": kickoff_result.advanced_turn,
                "applied_mutation_count": kickoff_result.applied_mutation_count,
            },
        }
    except Exception as e:
        logger.error("[API] Error initializing game: %s", str(e), exc_info=True)
        return {"success": False, "error": str(e)}


@router.post("/advance", response_model=OutcomeResponse)
async def advance_game(request: ActionRequest) -> OutcomeResponse:
    """
    Process a player action and advance the game state.

    POST body:
    ```json
    {
      "actor": "aldric_stonehammer",
      "action": "I swing my sword at the goblin"
    }
    ```

    Returns OutcomeResponse with adjudication status, ruling, and turn state.
    Not all responses advance the turn (e.g., question answers).
    """
    try:
        orchestrator = get_orchestrator()

        if request.actor != orchestrator.world.active_actor_id:
            return OutcomeResponse(
                success=False,
                data=None,
                error=f"It is not {request.actor}'s turn. Waiting for {orchestrator.world.awaiting_input_from}.",
                actor_id=request.actor,
            )

        result = orchestrator.process_intent(request.action)

        action_response = ActionResponse(
            status=result.status,
            ruling=result.ruling,
            actor_id=result.actor_id,
            awaiting_actor_id=result.awaiting_actor_id,
            advanced_turn=result.advanced_turn,
            applied_mutation_count=result.applied_mutation_count,
        )

        logger.info(
            "[API] Action processed | actor=%s | status=%s | advanced=%s",
            result.actor_id,
            result.status,
            result.advanced_turn,
        )

        return OutcomeResponse(
            success=True,
            data=action_response,
            error=None,
            actor_id=request.actor,
        )

    except Exception as e:
        logger.error("[API] Error processing action: %s", str(e), exc_info=True)
        return OutcomeResponse(
            success=False,
            data=None,
            error=str(e),
            actor_id=request.actor,
        )


@router.get("/status")
async def game_status() -> dict:
    """Get current game state snapshot."""
    try:
        orchestrator = get_orchestrator()
        world = orchestrator.world

        return {
            "success": True,
            "session_id": world.game_session_id,
            "active_actor_id": world.active_actor_id,
            "awaiting_input_from": world.awaiting_input_from,
            "world_version": world.world_version,
            "turn_count": world.turn_count,
            "party_size": len(world.party),
            "party_members": list(world.party.keys()),
        }
    except Exception as e:
        logger.error("[API] Error fetching status: %s", str(e), exc_info=True)
        return {"success": False, "error": str(e)}
