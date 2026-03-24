"""
Adventure loader: parses JSON assets and builds initial WorldState.
"""
from typing import Dict, Any, Optional
import json
from pathlib import Path
from .state import (
    WorldState,
    PCState,
    NPCState,
    RoomState,
    EncounterState,
    ObjectiveState,
    AbilityScores,
)


class AdventureLoader:
    """Loads PC sheets, adventure data, and rules, returns initialized WorldState."""

    def __init__(self, assets_dir: Path):
        """
        Args:
            assets_dir: Path to assets/ directory containing JSON files.
        """
        self.assets_dir = Path(assets_dir)

    def load_adventure(
        self,
        adventure_file: str,
        pc_files: list[str],
        rules_file: Optional[str] = None,
    ) -> WorldState:
        """
        Load adventure, PCs, and rules into a WorldState.

        Args:
            adventure_file: Filename of adventure JSON (e.g., "adventure_sunken_grotto.json")
            pc_files: List of PC filenames (e.g., ["pc_aldric_stonehammer.json", ...])
            rules_file: Optional homebrew rules file (e.g., "homebrew_rules.json")

        Returns:
            Initialized WorldState ready for simulation.
        """
        # Load raw JSON data
        adventure_data = self._load_json(adventure_file)
        pc_data_list = [self._load_json(f) for f in pc_files]
        rules_data = self._load_json(rules_file) if rules_file else {}

        # Build state components
        party = self._build_party(pc_data_list)
        npcs = self._build_npcs(adventure_data)
        rooms = self._build_rooms(adventure_data)
        encounters = self._build_encounters(adventure_data)
        objectives = self._build_objectives(adventure_data)

        # Create world state
        world = WorldState(
            adventure_title=adventure_data.get("title", "Unknown Adventure"),
            turn_count=0,
            party=party,
            npcs=npcs,
            rooms=rooms,
            encounters=encounters,
            objectives=objectives,
            homebrew_rules=rules_data.get("rules", {}),
            active_encounter_id=None,
            turn_log=[],
        )

        # Place PCs in initial room
        if rooms:
            initial_room_id = next(iter(rooms.keys()))
            for pc_id in party.keys():
                pc = party[pc_id]
                world = world.update_pc(pc_id, pc.move_to(initial_room_id))
                room = rooms[initial_room_id]
                world = world.update_room(
                    initial_room_id,
                    RoomState(
                        id=room.id,
                        name=room.name,
                        is_cleared=room.is_cleared,
                        is_visited=True,
                        trap_disarmed=room.trap_disarmed,
                        npc_ids=room.npc_ids,
                        pc_ids=[*room.pc_ids, pc_id],
                    ),
                )

        return world

    def _load_json(self, filename: str) -> Dict[str, Any]:
        """Load JSON file from assets directory."""
        filepath = self.assets_dir / filename
        if not filepath.exists():
            raise FileNotFoundError(f"Asset not found: {filepath}")
        with open(filepath, "r") as f:
            return json.load(f)

    def _build_party(self, pc_data_list: list[Dict[str, Any]]) -> Dict[str, PCState]:
        """Build party from PC data."""
        party = {}
        for pc_data in pc_data_list:
            stats = AbilityScores(
                STR=pc_data["stats"]["STR"],
                DEX=pc_data["stats"]["DEX"],
                CON=pc_data["stats"]["CON"],
                INT=pc_data["stats"]["INT"],
                WIS=pc_data["stats"]["WIS"],
                CHA=pc_data["stats"]["CHA"],
            )
            pc = PCState(
                id=pc_data.get("id", pc_data["name"].lower().replace(" ", "_")),
                name=pc_data["name"],
                race=pc_data["race"],
                char_class=pc_data["class"],
                level=pc_data["level"],
                stats=stats,
                hp_max=pc_data["hp"]["max"],
                hp_current=pc_data["hp"]["current"],
                ac=pc_data["ac"],
                position="entrance",  # Default, will be overridden
            )
            party[pc.id] = pc
        return party

    def _build_npcs(self, adventure_data: Dict[str, Any]) -> Dict[str, NPCState]:
        """Build NPCs from adventure data."""
        npcs = {}
        
        # Extract NPCs from encounters
        for room_data in adventure_data.get("map", {}).values():
            for encounter in room_data.get("encounters", []):
                for enemy in encounter.get("enemies", []):
                    npc_id = f"{encounter['id']}_enemy_{len(npcs)}"
                    npc = NPCState(
                        id=npc_id,
                        name=enemy.get("type"),
                        npc_type=enemy.get("type"),
                        hp_max=enemy.get("hp", 10),
                        hp_current=enemy.get("hp", 10),
                        ac=enemy.get("ac", 12),
                        position=room_data.get("room_id", "unknown"),
                        role="combatant",
                    )
                    npcs[npc_id] = npc
        
        # Extract boss/named NPCs
        for npc_key, npc_data in adventure_data.get("npcs", {}).items():
            npc_id = npc_key
            # Find HP/AC from stat_block_ref if available
            stat_block_ref = npc_data.get("stat_block_ref")
            hp_max, ac = 20, 12
            if stat_block_ref:
                # Try to find the encounter
                for room_data in adventure_data.get("map", {}).values():
                    for encounter in room_data.get("encounters", []):
                        if encounter.get("id") == stat_block_ref:
                            for enemy in encounter.get("enemies", []):
                                if enemy.get("name") == npc_data.get("name"):
                                    hp_max = enemy.get("hp", 20)
                                    ac = enemy.get("ac", 12)
            
            npc = NPCState(
                id=npc_id,
                name=npc_data["name"],
                npc_type=npc_data.get("title", "Unknown"),
                hp_max=hp_max,
                hp_current=hp_max,
                ac=ac,
                position="unknown",  # Will be placed by DM logic
                role=npc_data.get("role", "unknown"),
            )
            npcs[npc_id] = npc
        
        return npcs

    def _build_rooms(self, adventure_data: Dict[str, Any]) -> Dict[str, RoomState]:
        """Build rooms from adventure data."""
        rooms = {}
        for room_id, room_data in adventure_data.get("map", {}).items():
            room = RoomState(
                id=room_id,
                name=room_data.get("name", room_id),
                is_cleared=False,
                is_visited=False,
                trap_disarmed=not room_data.get("hazards"),
            )
            rooms[room_id] = room
        return rooms

    def _build_encounters(
        self, adventure_data: Dict[str, Any]
    ) -> Dict[str, EncounterState]:
        """Build encounters from adventure data."""
        encounters = {}
        for room_data in adventure_data.get("map", {}).values():
            for encounter in room_data.get("encounters", []):
                enc_id = encounter.get("id")
                room_id = room_data.get("room_id")
                
                # Collect enemy IDs for this encounter
                npc_ids = []
                for i, enemy in enumerate(encounter.get("enemies", [])):
                    npc_ids.append(f"{enc_id}_enemy_{i}")
                
                encounter_state = EncounterState(
                    id=enc_id,
                    name=encounter.get("name", enc_id),
                    room_id=room_id,
                    is_active=False,
                    is_cleared=False,
                    round_count=0,
                    npc_ids=npc_ids,
                )
                encounters[enc_id] = encounter_state
        return encounters

    def _build_objectives(
        self, adventure_data: Dict[str, Any]
    ) -> Dict[str, ObjectiveState]:
        """Build quest objectives from adventure data."""
        objectives = {}
        for obj_data in adventure_data.get("objectives", []):
            obj_id = obj_data.get("id")
            objective = ObjectiveState(
                id=obj_id,
                goal=obj_data.get("goal", ""),
                is_completed=False,
                is_failed=False,
            )
            objectives[obj_id] = objective
        return objectives
