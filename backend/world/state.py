"""
World state models for the D&D simulation.
Designed for immutability and LangGraph integration.
"""
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field, replace
from enum import Enum
import json


def _merge_unique_strings(*groups: List[str]) -> List[str]:
    """Merge string lists while preserving order and removing duplicates."""
    merged: List[str] = []
    for group in groups:
        for value in group:
            if value and value not in merged:
                merged.append(value)
    return merged


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
    inventory: List[str] = field(default_factory=list)
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
        return replace(self, hp_current=new_hp, is_alive=new_hp > 0)

    def move_to(self, room_id: str) -> "PCState":
        """Move to a room. Returns updated PCState."""
        return replace(self, position=room_id)

    def add_item(self, item: str) -> "PCState":
        """Add one item to inventory. Returns updated PCState."""
        return replace(self, inventory=[*self.inventory, item])

    def remove_item(self, item: str) -> "PCState":
        """Remove one matching item from inventory. Returns updated PCState."""
        remaining = list(self.inventory)
        try:
            remaining.remove(item)
        except ValueError:
            return self
        return replace(self, inventory=remaining)

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
    inventory: List[str] = field(default_factory=list)
    conditions: List[str] = field(default_factory=list)  # e.g., ["prone", "stunned"]
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

    def heal(self, amount: int) -> "NPCState":
        """Apply healing. Returns updated NPCState."""
        new_hp = min(self.hp_max, self.hp_current + amount)
        return replace(self, hp_current=new_hp, is_alive=new_hp > 0)

    def set_morale(self, morale: int) -> "NPCState":
        """Set morale (-2 to 2). Returns updated NPCState."""
        new_morale = max(-2, min(2, morale))
        return replace(self, morale=new_morale)

    def move_to(self, room_id: str) -> "NPCState":
        """Move to a room. Returns updated NPCState."""
        return replace(self, position=room_id)

    def add_item(self, item: str) -> "NPCState":
        """Add one item to inventory. Returns updated NPCState."""
        return replace(self, inventory=[*self.inventory, item])

    def remove_item(self, item: str) -> "NPCState":
        """Remove one matching item from inventory. Returns updated NPCState."""
        remaining = list(self.inventory)
        try:
            remaining.remove(item)
        except ValueError:
            return self
        return replace(self, inventory=remaining)

    def add_condition(self, condition: str) -> "NPCState":
        """Add a condition. Returns updated NPCState."""
        if condition not in self.conditions:
            return replace(self, conditions=[*self.conditions, condition])
        return self

    def remove_condition(self, condition: str) -> "NPCState":
        """Remove a condition. Returns updated NPCState."""
        new_conditions = [c for c in self.conditions if c != condition]
        return replace(self, conditions=new_conditions)


@dataclass(frozen=True)
class EncounterTurnEntry:
    """One actor's place in an encounter turn order."""

    actor_id: str
    initiative_roll: int | None = None


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
    turn_order: List[EncounterTurnEntry] = field(default_factory=list)
    current_turn_index: int = 0


@dataclass(frozen=True)
class RoomState:
    """State of a single room in the adventure."""
    id: str
    name: str
    is_cleared: bool = False
    is_visited: bool = False
    trap_disarmed: bool = False
    connections: List[Dict[str, Any]] = field(default_factory=list)  # exits from this room
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
class ActorKnowledgeState:
    """Discovered world knowledge available to one actor's intent generation."""

    actor_id: str
    actor_type: str
    known_room_ids: List[str] = field(default_factory=list)
    known_npc_ids: List[str] = field(default_factory=list)
    known_pc_ids: List[str] = field(default_factory=list)
    last_seen_room_id: Optional[str] = None


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
    actor_knowledge: Dict[str, ActorKnowledgeState] = field(default_factory=dict)  # actor id → discovered knowledge
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

    def update_actor_knowledge(self, actor_id: str, knowledge: ActorKnowledgeState) -> "WorldState":
        """Update one actor's discovered knowledge. Returns new WorldState."""
        new_knowledge = {**self.actor_knowledge, actor_id: knowledge}
        return replace(self, actor_knowledge=new_knowledge)

    def observe_actor(self, actor_id: str) -> "WorldState":
        """Capture what one actor can currently observe and merge it into their knowledge."""
        actor = self.party.get(actor_id)
        actor_type = "pc"
        if actor is None:
            actor = self.npcs.get(actor_id)
            actor_type = "npc"
        if actor is None:
            return self

        actor_room_id = getattr(actor, "position", None)
        visible_pc_ids = [
            pc_id
            for pc_id, pc in self.party.items()
            if pc.position == actor_room_id
        ]
        visible_npc_ids = [
            npc_id
            for npc_id, npc in self.npcs.items()
            if npc.position == actor_room_id and npc.is_alive
        ]

        encounter = self.encounters.get(self.active_encounter_id) if self.active_encounter_id else None
        if encounter is not None and encounter.room_id == actor_room_id:
            visible_npc_ids = _merge_unique_strings(visible_npc_ids, encounter.npc_ids)

        previous = self.actor_knowledge.get(actor_id)
        knowledge = ActorKnowledgeState(
            actor_id=actor_id,
            actor_type=actor_type,
            known_room_ids=_merge_unique_strings(
                previous.known_room_ids if previous is not None else [],
                [actor_room_id] if actor_room_id else [],
            ),
            known_npc_ids=_merge_unique_strings(
                previous.known_npc_ids if previous is not None else [],
                visible_npc_ids,
            ),
            known_pc_ids=_merge_unique_strings(
                previous.known_pc_ids if previous is not None else [],
                visible_pc_ids,
                [actor_id],
            ),
            last_seen_room_id=actor_room_id,
        )
        return self.update_actor_knowledge(actor_id, knowledge)

    def sync_actor_knowledge(self, actor_ids: Optional[List[str]] = None) -> "WorldState":
        """Refresh actor knowledge for the provided actors, or for the full cast."""
        resolved_actor_ids = actor_ids or [*self.party.keys(), *self.npcs.keys()]
        world = self
        for actor_id in resolved_actor_ids:
            world = world.observe_actor(actor_id)
        return world

    def set_active_encounter(self, encounter_id: Optional[str]) -> "WorldState":
        """Set active encounter. Returns new WorldState."""
        return replace(self, active_encounter_id=encounter_id)

    def set_encounter_turn_order(
        self,
        encounter_id: str,
        turn_order: List[EncounterTurnEntry],
    ) -> "WorldState":
        """Persist encounter-owned turn order. Returns new WorldState."""
        encounter = self.encounters[encounter_id]
        safe_index = 0
        if turn_order and encounter.turn_order:
            current_actor_id = None
            if 0 <= encounter.current_turn_index < len(encounter.turn_order):
                current_actor_id = encounter.turn_order[encounter.current_turn_index].actor_id
            if current_actor_id is not None:
                for index, entry in enumerate(turn_order):
                    if entry.actor_id == current_actor_id:
                        safe_index = index
                        break
                else:
                    safe_index = min(encounter.current_turn_index, len(turn_order) - 1)
        updated = replace(encounter, turn_order=turn_order, current_turn_index=safe_index if turn_order else 0)
        return self.update_encounter(encounter_id, updated)

    def set_encounter_turn_index(self, encounter_id: str, turn_index: int) -> "WorldState":
        """Set the current turn pointer for an encounter. Returns new WorldState."""
        encounter = self.encounters[encounter_id]
        if not encounter.turn_order:
            safe_index = 0
        else:
            safe_index = max(0, min(turn_index, len(encounter.turn_order) - 1))
        return self.update_encounter(encounter_id, replace(encounter, current_turn_index=safe_index))

    def get_current_encounter_actor_id(self, encounter_id: Optional[str] = None) -> Optional[str]:
        """Return the actor id whose slot is active in the given active, uncleared encounter."""
        resolved_encounter_id = encounter_id or self.active_encounter_id
        if resolved_encounter_id is None or resolved_encounter_id not in self.encounters:
            return None

        encounter = self.encounters[resolved_encounter_id]
        if encounter.is_cleared or not encounter.is_active or not encounter.turn_order:
            return None

        safe_index = max(0, min(encounter.current_turn_index, len(encounter.turn_order) - 1))
        return encounter.turn_order[safe_index].actor_id

    def advance_encounter_turn(self, encounter_id: str) -> "WorldState":
        """Advance the active slot for an encounter and increment round_count on wrap."""
        encounter = self.encounters[encounter_id]
        if encounter.is_cleared or not encounter.is_active or not encounter.turn_order:
            return self

        next_index = (encounter.current_turn_index + 1) % len(encounter.turn_order)
        next_round_count = encounter.round_count + 1 if next_index == 0 else encounter.round_count
        updated = replace(encounter, current_turn_index=next_index, round_count=next_round_count)
        return self.update_encounter(encounter_id, updated)

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
