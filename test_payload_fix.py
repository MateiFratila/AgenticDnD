#!/usr/bin/env python3
"""Regression test for the scoped adjudicator payload."""

import json
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.agents.contracts import AdjudicatorResponse, DestinationRoute
from backend.orchestrator.table_orchestrator import TableOrchestrator
from backend.world.loader import AdventureLoader


def test_adjudicator_payload_is_scoped_and_relevant():
    """Verify that adjudicator receives a reduced but decision-ready world view."""
    assets_dir = Path("assets")
    with TemporaryDirectory() as temp_dir:
        loader = AdventureLoader(assets_dir, snapshot_dir=Path(temp_dir) / "snapshots")
        world = loader.load_adventure(
            adventure_file="adventure_sunken_grotto.json",
            pc_files=["pc_aldric_stonehammer.json", "pc_sylara_nightveil.json"],
            rules_file="homebrew_rules.json",
        )

    full_world_str = json.dumps(asdict(world), indent=2)
    payload_str = TableOrchestrator.build_adjudicator_payload(
        world,
        "aldric_stonehammer",
        "Adventure Start: Establish the opening scene and immediate objective for the party.",
    )
    payload = json.loads(payload_str)

    assert payload["actor_id"] == "aldric_stonehammer"
    assert "world_state" in payload

    ws = payload["world_state"]
    assert ws["scope"] == "adjudicator_view"
    assert ws["adventure_title"] == "The Sunken Grotto of Grell's Hoard"
    assert ws["actor"]["id"] == "aldric_stonehammer"
    assert ws["actor"]["position"] == "entrance"
    assert "current_scene" in ws
    assert ws["current_scene"]["room_id"] == "entrance"
    assert ws["current_scene"]["room_name"] == "Grotto Mouth"
    assert ws["current_scene"]["connections"][0]["destination"] == "goblin_barracks"
    assert "visible_npcs" in ws["current_scene"]
    assert ws["rooms_of_interest"]["entrance"]["connections"][0]["destination"] == "goblin_barracks"
    assert "active_objectives" in ws
    assert "primary" in ws["active_objectives"]
    assert "recent_turn_log" in ws
    assert "relevant_rules" in ws
    assert "world_summary" in ws

    # Ensure we no longer dump the entire world blob into the adjudicator call.
    assert "npcs" not in ws
    assert "rooms" not in ws
    assert "encounters" not in ws
    assert len(payload_str) < len(full_world_str)

    print("✓ Scoped adjudicator payload contains actor/scene/objective context")
    print(f"✓ Scoped payload size: {len(payload_str):,} characters (~{len(payload_str) // 4:,} tokens)")
    print(f"✓ Full world dump size: {len(full_world_str):,} characters (~{len(full_world_str) // 4:,} tokens)")


def test_extractor_payload_contains_resolvable_npc_context():
    """Verify extractor receives nearby NPC details needed to resolve named targets."""
    assets_dir = Path("assets")
    with TemporaryDirectory() as temp_dir:
        loader = AdventureLoader(assets_dir, snapshot_dir=Path(temp_dir) / "snapshots")
        world = loader.load_adventure(
            adventure_file="adventure_sunken_grotto.json",
            pc_files=["pc_aldric_stonehammer.json", "pc_sylara_nightveil.json"],
            rules_file="homebrew_rules.json",
        )

    adjudication = AdjudicatorResponse(
        status="approved",
        ruling="Five darts of magical force slam into the Goblin Boss.",
        destination=[
            DestinationRoute(
                actor="extractor",
                purpose="Apply Magic Missile damage",
                payload_hint="Reduce Goblin Boss HP by 17",
            )
        ],
        reasoning="Magic Missile auto-hits.",
        suggested_alternatives=[],
    )

    payload = json.loads(TableOrchestrator.build_extractor_payload(world, adjudication))
    ws = payload["world_state"]

    assert "npcs_of_interest" in ws
    assert "encounter_1_enemy_1" in ws["npcs_of_interest"]
    assert ws["npcs_of_interest"]["encounter_1_enemy_1"]["name"] == "Goblin Boss"


if __name__ == "__main__":
    test_adjudicator_payload_is_scoped_and_relevant()
    test_extractor_payload_contains_resolvable_npc_context()
    print("\n✅ Test passed: Payloads now provide scoped but resolvable world context")
