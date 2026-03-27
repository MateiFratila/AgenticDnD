"""Tests for snapshot list/diff utility helpers."""

from pathlib import Path
import json

from backend.orchestrator.snapshot_tools import (
    main,
    list_snapshot_files,
    diff_snapshot_files,
)


def test_list_snapshot_files_sorted(tmp_path: Path):
    snapshot_dir = tmp_path / "snaps"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    names = [
        "loop_0002_turn_0001_v_0001_actor_a.json",
        "loop_0001_turn_0000_v_0000_actor_a.json",
    ]

    for name in names:
        (snapshot_dir / name).write_text("{}", encoding="utf-8")

    found = list_snapshot_files(snapshot_dir)
    assert [path.name for path in found] == sorted(names)


def test_diff_snapshot_files_detects_changes(tmp_path: Path):
    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"

    old_payload = {
        "turn_count": 0,
        "active_actor_id": "aldric_stonehammer",
        "party": {"aldric_stonehammer": {"hp_current": 52}},
    }
    new_payload = {
        "turn_count": 1,
        "active_actor_id": "sylara_nightveil",
        "party": {"aldric_stonehammer": {"hp_current": 48}},
        "world_version": 1,
    }

    old_path.write_text(json.dumps(old_payload), encoding="utf-8")
    new_path.write_text(json.dumps(new_payload), encoding="utf-8")

    diffs = diff_snapshot_files(old_path, new_path)

    assert any("~ turn_count" in line for line in diffs)
    assert any("~ active_actor_id" in line for line in diffs)
    assert any("~ party.aldric_stonehammer.hp_current" in line for line in diffs)
    assert any("+ world_version" in line for line in diffs)


def test_diff_latest_command(tmp_path: Path, monkeypatch, capsys):
    snapshot_dir = tmp_path / "snaps"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    first = snapshot_dir / "loop_0001_turn_0000_v_0000_actor_a.json"
    second = snapshot_dir / "loop_0002_turn_0001_v_0001_actor_b.json"

    first.write_text(json.dumps({"turn_count": 0}), encoding="utf-8")
    second.write_text(json.dumps({"turn_count": 1}), encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "snapshot_tools",
            "diff-latest",
            "--dir",
            str(snapshot_dir),
        ],
    )

    code = main()
    out = capsys.readouterr().out

    assert code == 0
    assert "Diffing:" in out
    assert "~ turn_count" in out


def test_diff_latest_requires_two_snapshots(tmp_path: Path, monkeypatch, capsys):
    snapshot_dir = tmp_path / "snaps"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    only = snapshot_dir / "loop_0001_turn_0000_v_0000_actor_a.json"
    only.write_text(json.dumps({"turn_count": 0}), encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "snapshot_tools",
            "diff-latest",
            "--dir",
            str(snapshot_dir),
        ],
    )

    code = main()
    out = capsys.readouterr().out

    assert code == 1
    assert "Need at least two snapshots" in out

