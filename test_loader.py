"""
Simple tests to verify world state loader behavior and dispatcher correctness.
"""

from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.world import (
    AdventureLoader,
    MutationType,
    WorldMutation,
    WorldStateDispatcher,
)


def _describe_world_changes(before, after):
    """Return human-readable list of state differences."""
    changes = []

    if before.turn_count != after.turn_count:
        changes.append(f"turn_count: {before.turn_count} -> {after.turn_count}")

    for pc_id in before.party.keys():
        pc_before = before.party[pc_id]
        pc_after = after.party[pc_id]
        if pc_before.position != pc_after.position:
            changes.append(
                f"pc[{pc_id}].position: {pc_before.position} -> {pc_after.position}"
            )
        if pc_before.hp_current != pc_after.hp_current:
            changes.append(
                f"pc[{pc_id}].hp_current: {pc_before.hp_current} -> {pc_after.hp_current}"
            )
        if pc_before.conditions != pc_after.conditions:
            changes.append(
                f"pc[{pc_id}].conditions: {pc_before.conditions} -> {pc_after.conditions}"
            )

    for room_id in before.rooms.keys():
        room_before = before.rooms[room_id]
        room_after = after.rooms[room_id]
        if room_before.pc_ids != room_after.pc_ids:
            changes.append(
                f"room[{room_id}].pc_ids: {room_before.pc_ids} -> {room_after.pc_ids}"
            )

    if len(before.turn_log) != len(after.turn_log):
        new_entries = after.turn_log[len(before.turn_log):]
        for entry in new_entries:
            changes.append(f"turn_log += {entry}")

    return changes


def test_load_sunken_grotto():
    """Test loading the Sunken Grotto adventure with PCs and dispatcher mutations."""
    assets_dir = Path(__file__).parent / "assets"

    with TemporaryDirectory() as temp_dir:
        snapshot_dir = Path(temp_dir) / "snapshots"
        loader = AdventureLoader(assets_dir, snapshot_dir=snapshot_dir)

        world = loader.load_adventure(
            adventure_file="adventure_sunken_grotto.json",
            pc_files=[
                "pc_aldric_stonehammer.json",
                "pc_sylara_nightveil.json",
            ],
            rules_file="homebrew_rules.json",
        )

        # Verify state loaded correctly
        print(f"✓ Adventure: {world.adventure_title}")
        print(f"✓ Session ID: {world.game_session_id}")
        print(f"✓ Party size: {len(world.party)}")
        for _, pc in world.party.items():
            print(f"  - {pc.name} ({pc.char_class}): {pc.hp_current}/{pc.hp_max} HP at {pc.position}")

        print(f"✓ NPCs: {len(world.npcs)}")
        print(f"✓ Rooms: {len(world.rooms)}")
        print(f"✓ Encounters: {len(world.encounters)}")
        print(f"✓ Objectives: {len(world.objectives)}")
        print(f"✓ Homebrew rules loaded: {len(world.homebrew_rules)} rules")

        first_encounter = world.encounters["encounter_1"]
        assert first_encounter.turn_order == [], "Fresh encounters should start with an empty turn order"
        assert first_encounter.current_turn_index == 0, "Fresh encounters should start at turn index 0"

        assert len(world.game_session_id) == 5, "Session id should be 5 chars"

        # Verify initial placement
        initial_room_id = "entrance"
        pcs_in_entrance = world.get_pcs_in_room(initial_room_id)
        print(f"✓ PCs in {initial_room_id}: {len(pcs_in_entrance)}")
        assert set(world.rooms[initial_room_id].pc_ids) == {"aldric_stonehammer", "sylara_nightveil"}, "Initial room membership should list both PCs"
        assert world.rooms[initial_room_id].connections[0]["destination"] == "goblin_barracks", "Entrance should preserve its connected destination"

        goblin_room = world.rooms["goblin_barracks"]
        assert "encounter_1_enemy_0" in goblin_room.npc_ids, "Goblin Boss should be discoverable from room membership"

        # Verify state is immutable
        aldric = world.party["aldric_stonehammer"]
        aldric_damaged = aldric.take_damage(5)
        world2 = world.update_pc("aldric_stonehammer", aldric_damaged)

        assert world.party["aldric_stonehammer"].hp_current == aldric.hp_current, "Original state mutated!"
        assert world2.party["aldric_stonehammer"].hp_current == aldric.hp_current - 5, "New state not updated!"
        print("✓ Immutability check passed")

        # Verify dispatcher can apply mutation arrays in sequence
        dispatcher = WorldStateDispatcher()
        mutations = [
            WorldMutation(
                type=MutationType.MOVE_ENTITY,
                entity_id="aldric_stonehammer",
                to_room_id="goblin_barracks",
            ),
            WorldMutation(
                type=MutationType.APPLY_DAMAGE,
                target_id="aldric_stonehammer",
                amount=6,
            ),
            WorldMutation(
                type=MutationType.ADD_CONDITION,
                target_id="aldric_stonehammer",
                condition="prone",
            ),
            WorldMutation(
                type=MutationType.APPEND_LOG_ENTRY,
                entry="[DM] Aldric advances and gets knocked prone.",
            ),
            WorldMutation(type=MutationType.INCREMENT_TURN),
        ]

        world3 = world
        print("\n[DISPATCH] Applying mutations and logging world diffs:")
        for index, mutation in enumerate(mutations, start=1):
            before = world3
            world3 = dispatcher.apply_mutations(world3, [mutation])
            print(f"  {index}. {mutation.type.value}")
            diffs = _describe_world_changes(before, world3)
            if diffs:
                for diff in diffs:
                    print(f"     - {diff}")
            else:
                print("     - no world changes")

        moved_aldric = world3.party["aldric_stonehammer"]
        assert moved_aldric.position == "goblin_barracks", "Aldric did not move"
        assert moved_aldric.hp_current == 46, "Aldric damage not applied"
        assert "prone" in moved_aldric.conditions, "Condition not applied"
        assert moved_aldric.id in world3.rooms["goblin_barracks"].pc_ids, "Room membership not synced"
        assert moved_aldric.id not in world3.rooms["entrance"].pc_ids, "Old room membership not cleaned"
        assert world3.turn_count == 1, "Turn increment failed"
        assert world3.turn_log[-1].startswith("[DM]"), "Log entry missing"
        print("✓ Dispatcher mutation array check passed")


def test_dispatcher_can_apply_conditions_to_npcs():
    """Dispatcher should support add/remove condition mutations for NPC targets."""
    assets_dir = Path(__file__).parent / "assets"

    with TemporaryDirectory() as temp_dir:
        snapshot_dir = Path(temp_dir) / "snapshots"
        loader = AdventureLoader(assets_dir, snapshot_dir=snapshot_dir)
        world = loader.load_adventure(
            adventure_file="adventure_sunken_grotto.json",
            pc_files=[
                "pc_aldric_stonehammer.json",
                "pc_sylara_nightveil.json",
            ],
            rules_file="homebrew_rules.json",
        )

        dispatcher = WorldStateDispatcher()
        goblin_id = "encounter_1_enemy_0"

        stunned_world = dispatcher.apply_mutations(
            world,
            [
                WorldMutation(
                    type=MutationType.ADD_CONDITION,
                    target_id=goblin_id,
                    condition="stunned",
                )
            ],
        )
        assert "stunned" in stunned_world.npcs[goblin_id].conditions

        recovered_world = dispatcher.apply_mutations(
            stunned_world,
            [
                WorldMutation(
                    type=MutationType.REMOVE_CONDITION,
                    target_id=goblin_id,
                    condition="stunned",
                )
            ],
        )
        assert "stunned" not in recovered_world.npcs[goblin_id].conditions
        print("✓ Dispatcher supports NPC condition mutations")


def test_dispatcher_can_add_and_remove_inventory_items():
    """Dispatcher should support item_add/item_remove for PC and NPC inventories."""
    assets_dir = Path(__file__).parent / "assets"

    with TemporaryDirectory() as temp_dir:
        snapshot_dir = Path(temp_dir) / "snapshots"
        loader = AdventureLoader(assets_dir, snapshot_dir=snapshot_dir)
        world = loader.load_adventure(
            adventure_file="adventure_sunken_grotto.json",
            pc_files=[
                "pc_aldric_stonehammer.json",
                "pc_sylara_nightveil.json",
            ],
            rules_file="homebrew_rules.json",
        )

        dispatcher = WorldStateDispatcher()
        updated_world = dispatcher.apply_mutations(
            world,
            [
                WorldMutation(
                    type=MutationType.ITEM_ADD,
                    target_id="sylara_nightveil",
                    item="Silver key",
                ),
                WorldMutation(
                    type=MutationType.ITEM_ADD,
                    target_id="encounter_1_enemy_0",
                    item="Stolen map scrap",
                ),
                WorldMutation(
                    type=MutationType.ITEM_REMOVE,
                    target_id="encounter_1_enemy_0",
                    item="Stolen map scrap",
                ),
            ],
        )

        assert "Silver key" in updated_world.party["sylara_nightveil"].inventory
        assert "Stolen map scrap" not in updated_world.npcs["encounter_1_enemy_0"].inventory
        print("✓ Dispatcher supports inventory mutations")


def test_dispatcher_clearing_active_encounter_resets_pointer():
    """Clearing an active encounter should also deactivate it and clear the active encounter pointer."""
    assets_dir = Path(__file__).parent / "assets"

    with TemporaryDirectory() as temp_dir:
        snapshot_dir = Path(temp_dir) / "snapshots"
        loader = AdventureLoader(assets_dir, snapshot_dir=snapshot_dir)
        world = loader.load_adventure(
            adventure_file="adventure_sunken_grotto.json",
            pc_files=[
                "pc_aldric_stonehammer.json",
                "pc_sylara_nightveil.json",
            ],
            rules_file="homebrew_rules.json",
        )

        dispatcher = WorldStateDispatcher()
        encounter_id = "encounter_1"
        world = dispatcher.apply_mutations(
            world,
            [
                WorldMutation(type=MutationType.SET_ACTIVE_ENCOUNTER, encounter_id=encounter_id),
                WorldMutation(
                    type=MutationType.SET_ENCOUNTER_ACTIVE,
                    encounter_id=encounter_id,
                    is_active=True,
                ),
            ],
        )

        cleared_world = dispatcher.apply_mutations(
            world,
            [
                WorldMutation(
                    type=MutationType.SET_ENCOUNTER_CLEARED,
                    encounter_id=encounter_id,
                    is_cleared=True,
                )
            ],
        )

        assert cleared_world.encounters[encounter_id].is_cleared is True
        assert cleared_world.encounters[encounter_id].is_active is False
        assert cleared_world.active_encounter_id is None
        print("✓ Clearing an encounter resets the active encounter pointer")


def test_loader_restore_snapshot_or_initialize_new():
    """Loader should restore latest session snapshot, else initialize a new world."""
    assets_dir = Path(__file__).parent / "assets"

    # Branch 1: initialize new world when snapshot does not exist.
    with TemporaryDirectory() as temp_dir:
        snapshot_dir = Path(temp_dir) / "snapshots"
        loader = AdventureLoader(assets_dir, snapshot_dir=snapshot_dir)

        fresh_world = loader.load_adventure(
            adventure_file="adventure_sunken_grotto.json",
            pc_files=[
                "pc_aldric_stonehammer.json",
                "pc_sylara_nightveil.json",
            ],
            rules_file="homebrew_rules.json",
        )
        assert len(fresh_world.game_session_id) == 5
        assert fresh_world.turn_count == 0
        print("✓ Fresh world initialized with generated session id")

        # Branch 2: restore from existing snapshot for that session.
        restored_seed = fresh_world.update_pc(
            "sylara_nightveil",
            fresh_world.party["sylara_nightveil"].add_item("Goblin keyring"),
        )
        restored_seed = (
            restored_seed
            .increment_turn()
            .add_log_entry("[WORLD] Restored from snapshot")
            .increment_version()
        )
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = snapshot_dir / (
            f"s_{restored_seed.game_session_id}_"
            "l_0001_a_test.json"
        )
        snapshot_path.write_text(json.dumps(asdict(restored_seed), indent=2), encoding="utf-8")

        restored_world = loader.load_adventure(
            adventure_file="adventure_sunken_grotto.json",
            pc_files=[
                "pc_aldric_stonehammer.json",
                "pc_sylara_nightveil.json",
            ],
            rules_file="homebrew_rules.json",
            game_session_id=restored_seed.game_session_id,
        )

        assert restored_world.game_session_id == restored_seed.game_session_id
        assert restored_world.turn_count == 1
        assert restored_world.world_version == 1
        assert restored_world.turn_log[-1] == "[WORLD] Restored from snapshot"
        assert "Goblin keyring" in restored_world.party["sylara_nightveil"].inventory
        print("✓ Existing snapshot restored by game_session_id")


if __name__ == "__main__":
    test_load_sunken_grotto()
    test_dispatcher_can_apply_conditions_to_npcs()
    test_loader_restore_snapshot_or_initialize_new()
    print("\n✅ All checks passed!")
