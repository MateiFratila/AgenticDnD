"""
Adventure loader: restores from snapshots first, or builds initial WorldState from assets.
"""
from typing import Dict, Any, Optional
import json
from pathlib import Path
from uuid import uuid4
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
    """Loads world state from snapshots first, then falls back to assets."""

    def __init__(
        self,
        assets_dir: Path,
        snapshot_dir: Path | str = "artifacts/world_snapshots",
    ):
        """
        Args:
            assets_dir: Path to assets/ directory containing JSON files.
            snapshot_dir: Path where world snapshots are persisted.
        """
        self.assets_dir = Path(assets_dir)
        self.snapshot_dir = Path(snapshot_dir)

    def load_adventure(
        self,
        adventure_file: str,
        pc_files: list[str],
        rules_file: Optional[str] = None,
        game_session_id: Optional[str] = None,
    ) -> WorldState:
        """
        Load latest world snapshot first, otherwise initialize from assets.

        Args:
            adventure_file: Filename of adventure JSON (e.g., "adventure_sunken_grotto.json")
            pc_files: List of PC filenames (e.g., ["pc_aldric_stonehammer.json", ...])
            rules_file: Optional homebrew rules file (e.g., "homebrew_rules.json")
            game_session_id: Optional session id to restore a specific game session.

        Returns:
            Restored or newly initialized WorldState.
        """
        latest_snapshot = self._find_latest_snapshot(game_session_id=game_session_id)
        if latest_snapshot is not None:
            return self._load_world_from_snapshot(latest_snapshot)

        # Load raw JSON data for a fresh world.
        adventure_data = self._load_json(adventure_file)
        pc_data_list = [self._load_json(f) for f in pc_files]
        rules_data = self._load_json(rules_file) if rules_file else {}

        # Build state components
        party = self._build_party(pc_data_list)
        npcs = self._build_npcs(adventure_data)
        rooms = self._build_rooms(adventure_data)
        encounters = self._build_encounters(adventure_data)
        objectives = self._build_objectives(adventure_data)

        # Create world state with a fresh short session id.
        world = WorldState(
            adventure_title=adventure_data.get("title", "Unknown Adventure"),
            game_session_id=game_session_id or self._generate_game_session_id(),
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

    def _generate_game_session_id(self) -> str:
        """Generate a short random session id."""
        return uuid4().hex[:5]

    def _find_latest_snapshot(self, game_session_id: Optional[str]) -> Optional[Path]:
        """Find latest snapshot, optionally filtered by game session id."""
        if not self.snapshot_dir.exists():
            return None

        snapshot_files = sorted(
            self.snapshot_dir.glob("*loop_*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not snapshot_files:
            return None

        if game_session_id is None:
            return snapshot_files[0]

        for snapshot_path in snapshot_files:
            try:
                snapshot_data = json.loads(snapshot_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if snapshot_data.get("game_session_id") == game_session_id:
                return snapshot_path

        return None

    def _load_world_from_snapshot(self, snapshot_path: Path) -> WorldState:
        """Load and materialize a WorldState from snapshot JSON."""
        snapshot_data = json.loads(snapshot_path.read_text(encoding="utf-8"))

        party = {
            pc_id: PCState(
                id=pc_data["id"],
                name=pc_data["name"],
                race=pc_data["race"],
                char_class=pc_data["char_class"],
                level=pc_data["level"],
                stats=AbilityScores(**pc_data["stats"]),
                hp_max=pc_data["hp_max"],
                hp_current=pc_data["hp_current"],
                ac=pc_data["ac"],
                position=pc_data["position"],
                conditions=pc_data.get("conditions", []),
                is_alive=pc_data.get("is_alive", True),
            )
            for pc_id, pc_data in snapshot_data.get("party", {}).items()
        }

        npcs = {
            npc_id: NPCState(
                id=npc_data["id"],
                name=npc_data["name"],
                npc_type=npc_data["npc_type"],
                hp_max=npc_data["hp_max"],
                hp_current=npc_data["hp_current"],
                ac=npc_data["ac"],
                position=npc_data["position"],
                role=npc_data["role"],
                is_alive=npc_data.get("is_alive", True),
                morale=npc_data.get("morale", 0),
            )
            for npc_id, npc_data in snapshot_data.get("npcs", {}).items()
        }

        rooms = {
            room_id: RoomState(
                id=room_data["id"],
                name=room_data["name"],
                is_cleared=room_data.get("is_cleared", False),
                is_visited=room_data.get("is_visited", False),
                trap_disarmed=room_data.get("trap_disarmed", False),
                npc_ids=room_data.get("npc_ids", []),
                pc_ids=room_data.get("pc_ids", []),
            )
            for room_id, room_data in snapshot_data.get("rooms", {}).items()
        }

        encounters = {
            enc_id: EncounterState(
                id=enc_data["id"],
                name=enc_data["name"],
                room_id=enc_data["room_id"],
                is_active=enc_data.get("is_active", False),
                is_cleared=enc_data.get("is_cleared", False),
                round_count=enc_data.get("round_count", 0),
                npc_ids=enc_data.get("npc_ids", []),
            )
            for enc_id, enc_data in snapshot_data.get("encounters", {}).items()
        }

        objectives = {
            obj_id: ObjectiveState(
                id=obj_data["id"],
                goal=obj_data.get("goal", ""),
                is_completed=obj_data.get("is_completed", False),
                is_failed=obj_data.get("is_failed", False),
            )
            for obj_id, obj_data in snapshot_data.get("objectives", {}).items()
        }

        return WorldState(
            adventure_title=snapshot_data.get("adventure_title", "Unknown Adventure"),
            game_session_id=snapshot_data.get("game_session_id") or self._generate_game_session_id(),
            turn_count=snapshot_data.get("turn_count", 0),
            party=party,
            npcs=npcs,
            rooms=rooms,
            encounters=encounters,
            objectives=objectives,
            homebrew_rules=snapshot_data.get("homebrew_rules", {}),
            active_encounter_id=snapshot_data.get("active_encounter_id"),
            turn_log=snapshot_data.get("turn_log", []),
            active_actor_id=snapshot_data.get("active_actor_id"),
            awaiting_input_from=snapshot_data.get("awaiting_input_from"),
            world_version=snapshot_data.get("world_version", 0),
        )
