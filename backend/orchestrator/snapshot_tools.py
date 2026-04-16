"""Utilities for listing and diffing persisted world snapshots."""

from __future__ import annotations

from argparse import ArgumentParser
import json
from pathlib import Path
from typing import Any

from .snapshot_store import list_world_snapshots


def list_snapshot_files(snapshot_dir: str | Path = "artifacts/world_snapshots") -> list[Path]:
    """Return snapshot files sorted by filename."""
    return list_world_snapshots(snapshot_dir, newest_first=False)


def load_snapshot(snapshot_path: str | Path) -> dict[str, Any]:
    """Load a snapshot JSON file."""
    path = Path(snapshot_path)
    return json.loads(path.read_text(encoding="utf-8"))


def _flatten_json(value: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten nested JSON into dot/index paths for deterministic diffing."""
    flattened: dict[str, Any] = {}

    if isinstance(value, dict):
        for key in sorted(value.keys()):
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            flattened.update(_flatten_json(value[key], child_prefix))
        return flattened

    if isinstance(value, list):
        for index, item in enumerate(value):
            child_prefix = f"{prefix}[{index}]" if prefix else f"[{index}]"
            flattened.update(_flatten_json(item, child_prefix))
        return flattened

    flattened[prefix] = value
    return flattened


def diff_snapshot_dicts(old_snapshot: dict[str, Any], new_snapshot: dict[str, Any]) -> list[str]:
    """Compute human-readable diff lines between two snapshot dictionaries."""
    old_flat = _flatten_json(old_snapshot)
    new_flat = _flatten_json(new_snapshot)

    old_keys = set(old_flat.keys())
    new_keys = set(new_flat.keys())

    diffs: list[str] = []

    for key in sorted(old_keys - new_keys):
        diffs.append(f"- {key}: {old_flat[key]!r} (removed)")

    for key in sorted(new_keys - old_keys):
        diffs.append(f"+ {key}: {new_flat[key]!r} (added)")

    for key in sorted(old_keys & new_keys):
        if old_flat[key] != new_flat[key]:
            diffs.append(f"~ {key}: {old_flat[key]!r} -> {new_flat[key]!r}")

    return diffs


def diff_snapshot_files(old_path: str | Path, new_path: str | Path) -> list[str]:
    """Compute diffs between two snapshot files."""
    old_snapshot = load_snapshot(old_path)
    new_snapshot = load_snapshot(new_path)
    return diff_snapshot_dicts(old_snapshot, new_snapshot)


def diff_snapshot_files_structured(
    old_path: str | Path, new_path: str | Path
) -> list[dict[str, Any]]:
    """Return diffs as structured records suitable for JSON serialization.

    Each record has:
      - path: dot-notation field path
      - kind: "added" | "removed" | "changed"
      - old_value: previous value (None for added)
      - new_value: new value (None for removed)
    """
    old_flat = _flatten_json(load_snapshot(old_path))
    new_flat = _flatten_json(load_snapshot(new_path))

    old_keys = set(old_flat.keys())
    new_keys = set(new_flat.keys())

    records: list[dict[str, Any]] = []

    for key in sorted(old_keys - new_keys):
        records.append({"path": key, "kind": "removed", "old_value": old_flat[key], "new_value": None})

    for key in sorted(new_keys - old_keys):
        records.append({"path": key, "kind": "added", "old_value": None, "new_value": new_flat[key]})

    for key in sorted(old_keys & new_keys):
        if old_flat[key] != new_flat[key]:
            records.append({"path": key, "kind": "changed", "old_value": old_flat[key], "new_value": new_flat[key]})

    return records


def _build_parser() -> ArgumentParser:
    parser = ArgumentParser(description="Snapshot list and diff utilities")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List available snapshots")
    list_parser.add_argument(
        "--dir",
        default="artifacts/world_snapshots",
        help="Snapshot directory",
    )

    diff_parser = subparsers.add_parser("diff", help="Diff two snapshot files")
    diff_parser.add_argument("old", help="Path to older snapshot")
    diff_parser.add_argument("new", help="Path to newer snapshot")

    diff_latest_parser = subparsers.add_parser(
        "diff-latest",
        help="Diff the two newest snapshots in a directory",
    )
    diff_latest_parser.add_argument(
        "--dir",
        default="artifacts/world_snapshots",
        help="Snapshot directory",
    )

    return parser


def main() -> int:
    """CLI entry point for snapshot tooling."""
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "list":
        snapshots = list_snapshot_files(args.dir)
        if not snapshots:
            print("No snapshots found.")
            return 0
        for snapshot in snapshots:
            print(snapshot)
        return 0

    if args.command == "diff":
        diffs = diff_snapshot_files(args.old, args.new)
        if not diffs:
            print("No differences found.")
            return 0
        for line in diffs:
            print(line)
        return 0

    if args.command == "diff-latest":
        snapshots = list_snapshot_files(args.dir)
        if len(snapshots) < 2:
            print("Need at least two snapshots to diff latest.")
            return 1

        old_path = snapshots[-2]
        new_path = snapshots[-1]
        print(f"Diffing:\n- {old_path}\n- {new_path}")
        diffs = diff_snapshot_files(old_path, new_path)
        if not diffs:
            print("No differences found.")
            return 0
        for line in diffs:
            print(line)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
