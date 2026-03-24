"""
Simple test to verify world state loader works with adventure assets.
"""
from pathlib import Path
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
    """Test loading the Sunken Grotto adventure with PCs."""
    assets_dir = Path(__file__).parent / "assets"
    
    loader = AdventureLoader(assets_dir)
    
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
    print(f"✓ Party size: {len(world.party)}")
    for pc_id, pc in world.party.items():
        print(f"  - {pc.name} ({pc.char_class}): {pc.hp_current}/{pc.hp_max} HP at {pc.position}")
    
    print(f"✓ NPCs: {len(world.npcs)}")
    print(f"✓ Rooms: {len(world.rooms)}")
    print(f"✓ Encounters: {len(world.encounters)}")
    print(f"✓ Objectives: {len(world.objectives)}")
    print(f"✓ Homebrew rules loaded: {len(world.homebrew_rules)} rules")
    
    # Verify initial placement
    initial_room_id = "entrance"
    pcs_in_entrance = world.get_pcs_in_room(initial_room_id)
    print(f"✓ PCs in {initial_room_id}: {len(pcs_in_entrance)}")
    
    # Verify state is immutable
    aldric = world.party["aldric_stonehammer"]
    aldric_damaged = aldric.take_damage(5)
    world2 = world.update_pc("aldric_stonehammer", aldric_damaged)
    
    assert world.party["aldric_stonehammer"].hp_current == aldric.hp_current, "Original state mutated!"
    assert world2.party["aldric_stonehammer"].hp_current == aldric.hp_current - 5, "New state not updated!"
    print(f"✓ Immutability check passed")

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
    print(f"✓ Dispatcher mutation array check passed")


if __name__ == "__main__":
    test_load_sunken_grotto()
    print("\n✅ All checks passed!")
