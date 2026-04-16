"""REST API routes for table orchestration."""

import asyncio
import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException, status

from backend.agents import BaseAgent
from backend.api.models import ActionRequest, OutcomeResponse, ActionResponse, ResolvedActionResponse
from backend.orchestrator.snapshot_store import clear_world_snapshots, list_world_snapshots
from backend.orchestrator.snapshot_tools import diff_snapshot_files, diff_snapshot_files_structured
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
    return clear_world_snapshots(snapshot_dir)


def _list_world_snapshots(snapshot_dir: Path, session_id: str | None = None) -> list[Path]:
    """Return session snapshots ordered newest-first by modification time."""
    return list_world_snapshots(snapshot_dir, session_id=session_id, newest_first=True)


def _build_fresh_orchestrator(
    snapshot_dir: Path,
    game_session_id: str | None = None,
) -> TableOrchestrator:
    """Build a new orchestrator from the latest matching snapshot or source assets."""
    loader = AdventureLoader(_assets_dir(), snapshot_dir=snapshot_dir)

    world = loader.load_adventure(
        adventure_file="adventure_sunken_grotto.json",
        pc_files=["pc_aldric_stonehammer.json", "pc_sylara_nightveil.json"],
        rules_file="homebrew_rules.json",
        game_session_id=game_session_id,
    )

    adjudicator_agent = BaseAgent(
        agent_type="adjudicator",
        agent_name="Adjudicator",
    )

    extractor_agent = BaseAgent(
        agent_type="extractor",
        agent_name="Extractor",
    )
    intent_agent = BaseAgent(
        agent_type="intent",
        agent_name="Intent Generator",
    )

    return TableOrchestrator.from_agents(
        world=world,
        turn_order=list(world.party.keys()),
        adjudicator_agent=adjudicator_agent,
        extractor_agent=extractor_agent,
        intent_agent=intent_agent,
        snapshot_dir=snapshot_dir,
    )


def set_orchestrator(orchestrator: TableOrchestrator, session_id: str) -> None:
    """Set the active orchestrator instance (called during app startup)."""
    _state["orchestrator"] = orchestrator
    _state["session_id"] = session_id


def get_orchestrator() -> TableOrchestrator:
    """Get the active orchestrator, lazily bootstrapping it if startup has not run yet."""
    if _state["orchestrator"] is None:
        try:
            orchestrator = _build_fresh_orchestrator(
                _snapshot_dir(),
                game_session_id=_state.get("session_id"),
            )
            set_orchestrator(orchestrator, orchestrator.world.game_session_id)
            logger.info(
                "[API] Lazily initialized orchestrator | session_id=%s",
                orchestrator.world.game_session_id,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Game engine not initialized: {exc}",
            ) from exc
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


@router.get("/rewind")
async def rewind_game() -> dict:
    """Delete the latest snapshot for the active session and reload the previous one."""
    try:
        orchestrator = get_orchestrator()
        snapshot_dir = _snapshot_dir()
        session_id = _state.get("session_id") or orchestrator.world.game_session_id

        snapshots = _list_world_snapshots(snapshot_dir, session_id=session_id)
        if len(snapshots) < 2:
            return {
                "success": False,
                "error": (
                    f"Cannot rewind session {session_id}: at least 2 snapshots are required, "
                    f"found {len(snapshots)}."
                ),
                "session_id": session_id,
            }

        deleted_snapshot = snapshots[0]
        deleted_snapshot.unlink()

        remaining_snapshots = _list_world_snapshots(snapshot_dir, session_id=session_id)
        restored_snapshot = remaining_snapshots[0] if remaining_snapshots else None

        reloaded_orchestrator = _build_fresh_orchestrator(
            snapshot_dir,
            game_session_id=session_id,
        )
        set_orchestrator(reloaded_orchestrator, reloaded_orchestrator.world.game_session_id)

        world = reloaded_orchestrator.world
        logger.info(
            "[API] Game rewound | session_id=%s | deleted=%s | restored=%s",
            world.game_session_id,
            deleted_snapshot.name,
            restored_snapshot.name if restored_snapshot else None,
        )

        return {
            "success": True,
            "session_id": world.game_session_id,
            "deleted_snapshot": deleted_snapshot.name,
            "restored_from_snapshot": restored_snapshot.name if restored_snapshot else None,
            "active_actor_id": world.active_actor_id,
            "awaiting_input_from": world.awaiting_input_from,
            "world_version": world.world_version,
            "turn_count": world.turn_count,
        }
    except Exception as e:
        logger.error("[API] Error rewinding game: %s", str(e), exc_info=True)
        return {"success": False, "error": str(e)}


@router.get("/snapshots")
async def list_snapshots(session_id: str | None = None) -> dict:
    """List persisted world snapshots for the active or requested session."""
    try:
        orchestrator = get_orchestrator()
        resolved_session_id = session_id or _state.get("session_id") or orchestrator.world.game_session_id
        snapshots = _list_world_snapshots(_snapshot_dir(), session_id=resolved_session_id)

        return {
            "success": True,
            "session_id": resolved_session_id,
            "snapshot_count": len(snapshots),
            "snapshots": [path.name for path in snapshots],
        }
    except Exception as e:
        logger.error("[API] Error listing snapshots: %s", str(e), exc_info=True)
        return {"success": False, "error": str(e)}


@router.get("/snapshots/diff-latest")
async def diff_latest_snapshots(session_id: str | None = None) -> dict:
    """Diff the newest two snapshots for the active or requested session."""
    try:
        orchestrator = get_orchestrator()
        resolved_session_id = session_id or _state.get("session_id") or orchestrator.world.game_session_id
        snapshots = _list_world_snapshots(_snapshot_dir(), session_id=resolved_session_id)

        if len(snapshots) < 2:
            return {
                "success": False,
                "session_id": resolved_session_id,
                "error": (
                    f"Cannot diff latest snapshots for session {resolved_session_id}: "
                    f"at least 2 snapshots are required, found {len(snapshots)}."
                ),
            }

        new_snapshot = snapshots[0]
        old_snapshot = snapshots[1]
        diffs = diff_snapshot_files_structured(old_snapshot, new_snapshot)

        return {
            "success": True,
            "session_id": resolved_session_id,
            "old_snapshot": old_snapshot.name,
            "new_snapshot": new_snapshot.name,
            "diff_count": len(diffs),
            "diffs": diffs,
        }
    except Exception as e:
        logger.error("[API] Error diffing latest snapshots: %s", str(e), exc_info=True)
        return {"success": False, "error": str(e)}


@router.post("/advance", response_model=OutcomeResponse)
async def advance_game(request: ActionRequest) -> OutcomeResponse:
    """
    Process a player action and advance the game state.

    POST body:
    ```json
    {
      "actor": {
        "actor_id": "aldric_stonehammer",
        "action": "I swing my sword at the goblin"
      }
    }
    ```

    Leave `actor.action` blank to have the intent agent propose one for the acting PC.
    The response also includes `data.actor` as the full normalized `ResolvedAction`, plus
    `npc_turns` for any NPC actions auto-resolved before control returns.
    """
    request_actor = request.actor
    actor_id = request_actor.actor_id

    try:
        orchestrator = get_orchestrator()

        if actor_id != orchestrator.world.active_actor_id:
            return OutcomeResponse(
                success=False,
                data=None,
                error=f"It is not {actor_id}'s turn. Waiting for {orchestrator.world.awaiting_input_from}.",
                actor_id=actor_id,
            )

        submitted_action = request_actor.action or ""
        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: orchestrator.process_intent(submitted_action, actor_id=actor_id)
        )

        resolved_action = getattr(result, "resolved_action", None)
        actor_response = ResolvedActionResponse(
            actor_id=(resolved_action.actor_id if resolved_action is not None else result.actor_id),
            action=(resolved_action.action if resolved_action is not None else submitted_action),
            source=(
                resolved_action.source
                if resolved_action is not None
                else ("player" if submitted_action else "intent_agent")
            ),
            in_character_note=(
                resolved_action.in_character_note if resolved_action is not None else None
            ),
            reasoning=(resolved_action.reasoning if resolved_action is not None else None),
        )

        action_response = ActionResponse(
            status=result.status,
            ruling=result.ruling,
            actor=actor_response,
            actor_id=result.actor_id,
            awaiting_actor_id=result.awaiting_actor_id,
            advanced_turn=result.advanced_turn,
            applied_mutation_count=result.applied_mutation_count,
            npc_turns=[
                {
                    "actor_id": turn.actor_id,
                    "generated_action": turn.generated_action,
                    "status": turn.status,
                    "ruling": turn.ruling,
                    "advanced_turn": turn.advanced_turn,
                    "applied_mutation_count": turn.applied_mutation_count,
                }
                for turn in result.npc_turns
            ],
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
            actor_id=actor_id,
        )

    except Exception as e:
        logger.error("[API] Error processing action: %s", str(e), exc_info=True)
        return OutcomeResponse(
            success=False,
            data=None,
            error=str(e),
            actor_id=actor_id,
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
