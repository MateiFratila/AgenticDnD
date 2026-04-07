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
    summary = ws["summary"]

    assert ws["scope"] == "adjudicator_view"
    assert ws["adventure_title"] == "The Sunken Grotto of Grell's Hoard"
    assert summary["actor"]["id"] == "aldric_stonehammer"
    assert summary["actor"]["position"] == "entrance"
    assert summary["current_scene"]["room_id"] == "entrance"
    assert summary["current_scene"]["room_name"] == "Grotto Mouth"
    assert summary["current_scene"]["connections"][0]["destination"] == "goblin_barracks"
    assert "visible_npcs" in summary["current_scene"]
    assert "active_objectives" in summary
    assert "primary" in summary["active_objectives"]
    assert "recent_turn_log" in summary
    assert "relevant_rules" in summary

    assert "canonical_world_state" in ws
    assert "party" in ws["canonical_world_state"]
    assert "npcs" in ws["canonical_world_state"]
    assert "rooms" in ws["canonical_world_state"]
    assert "encounters" in ws["canonical_world_state"]
    assert "objectives" in ws["canonical_world_state"]
    assert ws["canonical_world_state"]["objectives"]["primary"]["goal"] == "Recover the Shard of Kaelas"

    # Redundant convenience copies should be removed from the top level once the canonical world is included.
    assert "party" not in ws
    assert "current_scene" not in ws
    assert "rooms_of_interest" not in ws
    assert "active_encounter" not in ws
    assert "active_objectives" not in ws
    assert "recent_turn_log" not in ws
    assert "relevant_rules" not in ws

    print("✓ Adjudicator payload now uses a lean DM summary plus full canonical world context")
    print(f"✓ Adjudicator payload size: {len(payload_str):,} characters (~{len(payload_str) // 4:,} tokens)")
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


def test_intent_payload_uses_actor_knowledge_instead_of_remote_omniscience():
    """Verify the intent agent only receives what the acting actor has discovered so far."""
    assets_dir = Path("assets")
    with TemporaryDirectory() as temp_dir:
        loader = AdventureLoader(assets_dir, snapshot_dir=Path(temp_dir) / "snapshots")
        world = loader.load_adventure(
            adventure_file="adventure_sunken_grotto.json",
            pc_files=["pc_aldric_stonehammer.json", "pc_sylara_nightveil.json"],
            rules_file="homebrew_rules.json",
        )

    sylara = world.party["sylara_nightveil"].move_to("main_hall")
    world = world.update_pc("sylara_nightveil", sylara)
    entrance = world.rooms["entrance"]
    main_hall = world.rooms["main_hall"]
    world = world.update_room(
        "entrance",
        type(entrance)(
            id=entrance.id,
            name=entrance.name,
            is_cleared=entrance.is_cleared,
            is_visited=entrance.is_visited,
            trap_disarmed=entrance.trap_disarmed,
            connections=entrance.connections,
            npc_ids=entrance.npc_ids,
            pc_ids=[pc_id for pc_id in entrance.pc_ids if pc_id != "sylara_nightveil"],
        ),
    )
    world = world.update_room(
        "main_hall",
        type(main_hall)(
            id=main_hall.id,
            name=main_hall.name,
            is_cleared=main_hall.is_cleared,
            is_visited=main_hall.is_visited,
            trap_disarmed=main_hall.trap_disarmed,
            connections=main_hall.connections,
            npc_ids=main_hall.npc_ids,
            pc_ids=[*main_hall.pc_ids, "sylara_nightveil"],
        ),
    )
    world = world.add_log_entry("[WORLD] Sylara moved into main_hall and spotted goblins there.")

    payload = json.loads(TableOrchestrator.build_intent_payload(world, "aldric_stonehammer"))
    ws = payload["world_state"]

    assert ws["scope"] == "intent_view"
    assert ws["current_scene"]["room_id"] == "entrance"
    assert "known_rooms" in ws
    assert "entrance" in ws["known_rooms"]
    assert "main_hall" not in ws["known_rooms"]
    assert "visible_allies" in ws["current_scene"]
    assert all(ally["id"] != "sylara_nightveil" for ally in ws["current_scene"]["visible_allies"])
    assert all("main_hall" not in entry for entry in ws["recent_turn_log"])


def test_extractor_payload_keeps_npc_scene_context_for_active_npc_turns():
    """Verify extractor payload still has a concrete current scene when the active actor is an NPC."""
    assets_dir = Path("assets")
    with TemporaryDirectory() as temp_dir:
        loader = AdventureLoader(assets_dir, snapshot_dir=Path(temp_dir) / "snapshots")
        world = loader.load_adventure(
            adventure_file="adventure_sunken_grotto.json",
            pc_files=["pc_aldric_stonehammer.json", "pc_sylara_nightveil.json"],
            rules_file="homebrew_rules.json",
        )

    aldric = world.party["aldric_stonehammer"].move_to("goblin_barracks")
    world = world.update_pc("aldric_stonehammer", aldric)
    entrance = world.rooms["entrance"]
    barracks = world.rooms["goblin_barracks"]
    world = world.update_room(
        "entrance",
        type(entrance)(
            id=entrance.id,
            name=entrance.name,
            is_cleared=entrance.is_cleared,
            is_visited=entrance.is_visited,
            trap_disarmed=entrance.trap_disarmed,
            connections=entrance.connections,
            npc_ids=entrance.npc_ids,
            pc_ids=[pc_id for pc_id in entrance.pc_ids if pc_id != "aldric_stonehammer"],
        ),
    )
    world = world.update_room(
        "goblin_barracks",
        type(barracks)(
            id=barracks.id,
            name=barracks.name,
            is_cleared=barracks.is_cleared,
            is_visited=barracks.is_visited,
            trap_disarmed=barracks.trap_disarmed,
            connections=barracks.connections,
            npc_ids=barracks.npc_ids,
            pc_ids=[*barracks.pc_ids, "aldric_stonehammer"],
        ),
    )
    world = world.set_active_actor("encounter_1_enemy_0").set_active_encounter("encounter_1")
    adjudication = AdjudicatorResponse(
        status="approved",
        ruling="The goblin's arrow slips past Aldric's shield for 4 piercing damage.",
        destination=[
            DestinationRoute(
                actor="extractor",
                purpose="Apply ranged attack damage",
                payload_hint="Damage Aldric for 4",
            )
        ],
        reasoning="Resolved NPC attack with explicit damage.",
        suggested_alternatives=[],
    )

    payload = json.loads(TableOrchestrator.build_extractor_payload(world, adjudication))
    ws = payload["world_state"]

    assert ws["current_scene"]["room_id"] == "goblin_barracks"
    assert ws["current_scene"]["room_name"] == "Barracks"
    assert "aldric_stonehammer" in ws["current_scene"]["pc_ids"]


if __name__ == "__main__":
    test_adjudicator_payload_is_scoped_and_relevant()
    test_extractor_payload_contains_resolvable_npc_context()
    test_intent_payload_uses_actor_knowledge_instead_of_remote_omniscience()
    test_extractor_payload_keeps_npc_scene_context_for_active_npc_turns()
    print("\n✅ Test passed: Payloads now provide scoped but resolvable world context")
