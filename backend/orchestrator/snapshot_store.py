"""Shared world-snapshot persistence helpers for the orchestrator and HTTP routes."""

from __future__ import annotations

from dataclasses import asdict
import json
import logging
from pathlib import Path

from backend.world import WorldState


logger = logging.getLogger(__name__)


def _snapshot_patterns(session_id: str | None) -> tuple[str, str]:
    """Return compact and legacy snapshot filename globs for the optional session."""
    if session_id is None:
        return "s_*_l_*.json", "session_*_loop_*.json"
    return f"s_{session_id}_l_*.json", f"session_{session_id}_loop_*.json"


def list_world_snapshots(
    snapshot_dir: str | Path = "artifacts/world_snapshots",
    session_id: str | None = None,
    newest_first: bool = False,
) -> list[Path]:
    """Return persisted world snapshots, optionally filtered to one game session."""
    base_dir = Path(snapshot_dir)
    if not base_dir.exists():
        return []

    compact_pattern, legacy_pattern = _snapshot_patterns(session_id)
    snapshots = [*base_dir.glob(compact_pattern), *base_dir.glob(legacy_pattern)]
    snapshots = list(dict.fromkeys(snapshots))

    if newest_first:
        return sorted(snapshots, key=lambda path: path.stat().st_mtime, reverse=True)
    return sorted(snapshots)


def clear_world_snapshots(
    snapshot_dir: str | Path = "artifacts/world_snapshots",
    session_id: str | None = None,
) -> int:
    """Delete persisted world snapshots and return the number removed."""
    deleted_count = 0
    for snapshot_path in list_world_snapshots(snapshot_dir, session_id=session_id):
        snapshot_path.unlink()
        deleted_count += 1
    return deleted_count


def next_loop_index(
    snapshot_dir: str | Path | None,
    game_session_id: str,
) -> int:
    """Find the next loop index for a given game session."""
    if snapshot_dir is None:
        return 1

    base_dir = Path(snapshot_dir)
    if not base_dir.exists():
        return 1

    compact_prefix = f"s_{game_session_id}_l_"
    legacy_prefix = f"session_{game_session_id}_loop_"
    max_loop = 0
    for snapshot_path in [
        *base_dir.glob(f"s_{game_session_id}_l_*.json"),
        *base_dir.glob(f"session_{game_session_id}_loop_*.json"),
    ]:
        name = snapshot_path.name
        if name.startswith(compact_prefix):
            loop_token = name[len(compact_prefix): len(compact_prefix) + 4]
        elif name.startswith(legacy_prefix):
            loop_token = name[len(legacy_prefix): len(legacy_prefix) + 4]
        else:
            continue
        if loop_token.isdigit():
            max_loop = max(max_loop, int(loop_token))

    return max_loop + 1


def persist_world_snapshot(
    world: WorldState,
    actor_id: str,
    snapshot_dir: str | Path | None = "artifacts/world_snapshots",
    loop_index: int | None = None,
) -> Path | None:
    """Persist the current world state to disk and return the snapshot path."""
    if snapshot_dir is None:
        return None

    base_dir = Path(snapshot_dir)
    base_dir.mkdir(parents=True, exist_ok=True)

    resolved_loop_index = loop_index or next_loop_index(base_dir, world.game_session_id)
    file_path = base_dir / (
        f"s_{world.game_session_id}_"
        f"l_{resolved_loop_index:04d}_"
        f"a_{actor_id}.json"
    )
    file_path.write_text(json.dumps(asdict(world), indent=2), encoding="utf-8")
    logger.info("[TABLE] Snapshot persisted | path=%s", file_path)
    return file_path
