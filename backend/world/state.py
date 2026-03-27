"""
World state models for the D&D simulation.
Designed for immutability and LangGraph integration.
"""
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field, replace
from enum import Enum
import json


class AbilityScoreType(str, Enum):
    """D&D 5e ability scores."""
    STR = "STR"
    DEX = "DEX"
    CON = "CON"
    INT = "INT"
    WIS = "WIS"
    CHA = "CHA"


@dataclass(frozen=True)
class AbilityScores:
    """Character ability scores."""
    STR: int
    DEX: int
    CON: int
    INT: int
    WIS: int
    CHA: int

    def __getitem__(self, key: str) -> int:
        """Allow dict-like access."""
        return getattr(self, key)


@dataclass(frozen=True)
class PCState:
    """Player character state."""
    id: str
    name: str
    race: str
    char_class: str
    level: int
    stats: AbilityScores
    hp_max: int
    hp_current: int
    ac: int
    position: str  # room_id
    conditions: List[str] = field(default_factory=list)  # e.g., ["prone", "blinded"]
    is_alive: bool = True

    @property
    def is_bloodied(self) -> bool:
        """Returns True if PC is at <= 50% HP."""
        return self.hp_current <= self.hp_max // 2

    def take_damage(self, amount: int) -> "PCState":
        """Apply damage. Returns updated PCState."""
        new_hp = max(0, self.hp_current - amount)
        is_alive = new_hp > 0
        return replace(self, hp_current=new_hp, is_alive=is_alive)

    def heal(self, amount: int) -> "PCState":
        """Apply healing. Returns updated PCState."""
        new_hp = min(self.hp_max, self.hp_current + amount)
        return replace(self, hp_current=new_hp)

    def move_to(self, room_id: str) -> "PCState":
        """Move to a room. Returns updated PCState."""
        return replace(self, position=room_id)

    def add_condition(self, condition: str) -> "PCState":
        """Add a condition. Returns updated PCState."""
        if condition not in self.conditions:
            return replace(self, conditions=[*self.conditions, condition])
        return self

    def remove_condition(self, condition: str) -> "PCState":
        """Remove a condition. Returns updated PCState."""
        new_conditions = [c for c in self.conditions if c != condition]
        return replace(self, conditions=new_conditions)


@dataclass(frozen=True)
class NPCState:
    """NPC state (enemy or ally)."""
    id: str
    name: str
    npc_type: str  # e.g., "Kobold", "Goblin", "Grell"
    hp_max: int
    hp_current: int
    ac: int
    position: str  # room_id
    role: str  # e.g., "warlord", "mercenary", "guard"
    is_alive: bool = True
    morale: int = 0  # -2 to 2 scale for tactical behavior

    @property
    def is_bloodied(self) -> bool:
        """Returns True if NPC is at <= 50% HP."""
        return self.hp_current <= self.hp_max // 2

    def take_damage(self, amount: int) -> "NPCState":
        """Apply damage. Returns updated NPCState."""
        new_hp = max(0, self.hp_current - amount)
        is_alive = new_hp > 0
        return replace(self, hp_current=new_hp, is_alive=is_alive)

    def set_morale(self, morale: int) -> "NPCState":
        """Set morale (-2 to 2). Returns updated NPCState."""
        new_morale = max(-2, min(2, morale))
        return replace(self, morale=new_morale)

    def move_to(self, room_id: str) -> "NPCState":
        """Move to a room. Returns updated NPCState."""
        return replace(self, position=room_id)


@dataclass(frozen=True)
class EncounterState:
    """State of a single encounter."""
    id: str
    name: str
    room_id: str
    is_active: bool = False
    is_cleared: bool = False
    round_count: int = 0
    npc_ids: List[str] = field(default_factory=list)  # IDs of NPCs in this encounter


@dataclass(frozen=True)
class RoomState:
    """State of a single room in the adventure."""
    id: str
    name: str
    is_cleared: bool = False
    is_visited: bool = False
    trap_disarmed: bool = False
    npc_ids: List[str] = field(default_factory=list)  # NPCs currently in room
    pc_ids: List[str] = field(default_factory=list)  # PCs currently in room


@dataclass(frozen=True)
class ObjectiveState:
    """State of a quest objective."""
    id: str
    goal: str
    is_completed: bool = False
    is_failed: bool = False


@dataclass(frozen=True)
class WorldState:
    """Complete game world state for D&D simulation."""
    adventure_title: str
    game_session_id: str = ""  # short session identifier (5 chars)
    turn_count: int = 0
    party: Dict[str, PCState] = field(default_factory=dict)  # PC id → PCState
    npcs: Dict[str, NPCState] = field(default_factory=dict)  # NPC id → NPCState
    rooms: Dict[str, RoomState] = field(default_factory=dict)  # room id → RoomState
    encounters: Dict[str, EncounterState] = field(default_factory=dict)  # encounter id → EncounterState
    objectives: Dict[str, ObjectiveState] = field(default_factory=dict)  # objective id → ObjectiveState
    homebrew_rules: Dict[str, Any] = field(default_factory=dict)
    active_encounter_id: Optional[str] = None
    turn_log: List[str] = field(default_factory=list)
    # Session / orchestration metadata
    active_actor_id: Optional[str] = None       # Actor whose turn is currently being processed
    awaiting_input_from: Optional[str] = None   # Actor whose input is needed next
    world_version: int = 0                       # Monotonic counter; increments on every committed turn

    # Utility methods for safe state mutations

    def update_pc(self, pc_id: str, new_pc: PCState) -> "WorldState":
        """Update a PC. Returns new WorldState."""
        new_party = {**self.party, pc_id: new_pc}
        return replace(self, party=new_party)

    def update_npc(self, npc_id: str, new_npc: NPCState) -> "WorldState":
        """Update an NPC. Returns new WorldState."""
        new_npcs = {**self.npcs, npc_id: new_npc}
        return replace(self, npcs=new_npcs)

    def update_room(self, room_id: str, new_room: RoomState) -> "WorldState":
        """Update a room. Returns new WorldState."""
        new_rooms = {**self.rooms, room_id: new_room}
        return replace(self, rooms=new_rooms)

    def update_encounter(self, enc_id: str, new_enc: EncounterState) -> "WorldState":
        """Update an encounter. Returns new WorldState."""
        new_encounters = {**self.encounters, enc_id: new_enc}
        return replace(self, encounters=new_encounters)

    def update_objective(self, obj_id: str, new_obj: ObjectiveState) -> "WorldState":
        """Update an objective. Returns new WorldState."""
        new_objectives = {**self.objectives, obj_id: new_obj}
        return replace(self, objectives=new_objectives)

    def set_active_encounter(self, encounter_id: Optional[str]) -> "WorldState":
        """Set active encounter. Returns new WorldState."""
        return replace(self, active_encounter_id=encounter_id)

    def increment_turn(self) -> "WorldState":
        """Increment turn counter. Returns new WorldState."""
        return replace(self, turn_count=self.turn_count + 1)

    def add_log_entry(self, entry: str) -> "WorldState":
        """Add entry to turn log. Returns new WorldState."""
        new_log = [*self.turn_log, entry]
        return replace(self, turn_log=new_log)

    def set_active_actor(self, actor_id: Optional[str]) -> "WorldState":
        """Set the actor currently being processed. Returns new WorldState."""
        return replace(self, active_actor_id=actor_id)

    def set_awaiting_input(self, actor_id: Optional[str]) -> "WorldState":
        """Set the actor whose input is required next. Returns new WorldState."""
        return replace(self, awaiting_input_from=actor_id)

    def increment_version(self) -> "WorldState":
        """Increment world version counter. Returns new WorldState."""
        return replace(self, world_version=self.world_version + 1)

    @property
    def party_alive(self) -> List[PCState]:
        """Return list of alive party members."""
        return [pc for pc in self.party.values() if pc.is_alive]

    @property
    def party_dead(self) -> List[PCState]:
        """Return list of dead party members."""
        return [pc for pc in self.party.values() if not pc.is_alive]

    @property
    def all_enemies_defeated(self) -> bool:
        """Check if all NPCs are defeated."""
        return all(not npc.is_alive for npc in self.npcs.values())

    def get_npcs_in_room(self, room_id: str) -> List[NPCState]:
        """Get all NPCs in a room."""
        return [npc for npc in self.npcs.values() if npc.position == room_id]

    def get_pcs_in_room(self, room_id: str) -> List[PCState]:
        """Get all PCs in a room."""
        return [pc for pc in self.party.values() if pc.position == room_id]
