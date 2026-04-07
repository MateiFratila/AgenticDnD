"""Helpers for building scoped LLM payloads from the current world state."""

from __future__ import annotations

import json
from typing import Any

from backend.agents.contracts import AdjudicatorResponse
from backend.world import WorldState


def summarize_party_member(pc: object) -> dict[str, Any]:
    """Return compact PC context suitable for LLM decision-making."""
    return {
        "id": pc.id,
        "name": pc.name,
        "race": pc.race,
        "class": pc.char_class,
        "level": pc.level,
        "hp_current": pc.hp_current,
        "hp_max": pc.hp_max,
        "ac": pc.ac,
        "position": pc.position,
        "conditions": pc.conditions,
        "is_alive": pc.is_alive,
    }


def summarize_npc(npc: object) -> dict[str, Any]:
    """Return compact NPC context for the current scene."""
    return {
        "id": npc.id,
        "name": npc.name,
        "type": npc.npc_type,
        "role": npc.role,
        "position": npc.position,
        "hp_current": npc.hp_current,
        "hp_max": npc.hp_max,
        "ac": npc.ac,
        "conditions": getattr(npc, "conditions", []),
        "is_alive": npc.is_alive,
        "morale": npc.morale,
    }


def summarize_room(room: object) -> dict[str, Any]:
    """Return compact room context for scoped prompts."""
    return {
        "room_id": room.id,
        "room_name": room.name,
        "is_visited": room.is_visited,
        "is_cleared": room.is_cleared,
        "trap_disarmed": room.trap_disarmed,
        "connections": getattr(room, "connections", []),
        "pc_ids": room.pc_ids,
        "npc_ids": room.npc_ids,
    }


def summarize_encounter(encounter: object) -> dict[str, Any]:
    """Return compact encounter context for scoped payloads."""
    turn_order = getattr(encounter, "turn_order", [])
    current_turn_index = getattr(encounter, "current_turn_index", 0)
    current_actor_id = None
    if turn_order and 0 <= current_turn_index < len(turn_order):
        current_actor_id = turn_order[current_turn_index].actor_id

    return {
        "id": encounter.id,
        "name": encounter.name,
        "room_id": encounter.room_id,
        "is_active": encounter.is_active,
        "is_cleared": encounter.is_cleared,
        "round_count": encounter.round_count,
        "npc_ids": encounter.npc_ids,
        "turn_order": [
            {
                "actor_id": entry.actor_id,
                "initiative_roll": entry.initiative_roll,
            }
            for entry in turn_order
        ],
        "current_turn_index": current_turn_index,
        "current_actor_id": current_actor_id,
    }


def build_adjudicator_world_view(
    world: WorldState,
    actor_id: str,
    loop_index: int | None = None,
) -> dict[str, Any]:
    """Build a lean DM-facing payload: a small summary plus the full canonical world."""
    actor = world.party.get(actor_id)
    actor_type = "pc"
    if actor is None:
        actor = world.npcs.get(actor_id)
        actor_type = "npc"
    actor_room_id = actor.position if actor is not None else None
    active_encounter = (
        world.encounters.get(world.active_encounter_id)
        if world.active_encounter_id is not None
        else None
    )

    visible_npcs = {
        npc_id: summarize_npc(npc)
        for npc_id, npc in world.npcs.items()
        if npc.position == actor_room_id
        or (
            active_encounter is not None
            and npc_id in active_encounter.npc_ids
        )
    }

    relevant_room_ids = {
        pc.position
        for pc in world.party.values()
        if pc.position
    }
    if actor_room_id:
        relevant_room_ids.add(actor_room_id)
    if active_encounter is not None and active_encounter.room_id:
        relevant_room_ids.add(active_encounter.room_id)

    rooms_of_interest = {
        room_id: summarize_room(room)
        for room_id, room in world.rooms.items()
        if room_id in relevant_room_ids
    }

    current_room = world.rooms.get(actor_room_id) if actor_room_id else None
    active_objectives = {
        obj_id: {
            "goal": obj.goal,
            "is_completed": obj.is_completed,
            "is_failed": obj.is_failed,
        }
        for obj_id, obj in world.objectives.items()
        if not obj.is_completed and not obj.is_failed
    }

    if not active_objectives:
        active_objectives = {
            obj_id: {
                "goal": obj.goal,
                "is_completed": obj.is_completed,
                "is_failed": obj.is_failed,
            }
            for obj_id, obj in world.objectives.items()
        }

    return {
        "scope": "adjudicator_view",
        "adventure_title": world.adventure_title,
        "loop_index": loop_index,
        "summary": {
            "session": {
                "game_session_id": world.game_session_id,
                "turn_count": world.turn_count,
                "loop_index": loop_index,
                "world_version": world.world_version,
                "active_actor_id": world.active_actor_id,
                "awaiting_input_from": world.awaiting_input_from,
                "active_encounter_id": world.active_encounter_id,
            },
            "actor": (
                summarize_party_member(actor)
                if actor is not None and actor_type == "pc"
                else summarize_npc(actor)
                if actor is not None and actor_type == "npc"
                else {"id": actor_id, "position": actor_room_id}
            ),
            "actor_type": actor_type,
            "current_scene": {
                "room_id": current_room.id if current_room is not None else actor_room_id,
                "room_name": current_room.name if current_room is not None else actor_room_id,
                "is_visited": current_room.is_visited if current_room is not None else False,
                "is_cleared": current_room.is_cleared if current_room is not None else False,
                "trap_disarmed": current_room.trap_disarmed if current_room is not None else None,
                "connections": current_room.connections if current_room is not None else [],
                "party_members_here": [
                    pc_id
                    for pc_id, pc in world.party.items()
                    if pc.position == actor_room_id
                ],
                "visible_npcs": visible_npcs,
            },
            "active_encounter": (
                summarize_encounter(active_encounter)
                if active_encounter is not None
                else None
            ),
            "active_objectives": active_objectives,
            "relevant_rules": world.homebrew_rules,
            "recent_turn_log": world.turn_log[-8:],
        },
        "canonical_world_state": {
            "adventure_title": world.adventure_title,
            "game_session_id": world.game_session_id,
            "turn_count": world.turn_count,
            "world_version": world.world_version,
            "party": {
                pc_id: summarize_party_member(pc)
                for pc_id, pc in world.party.items()
            },
            "npcs": {
                npc_id: summarize_npc(npc)
                for npc_id, npc in world.npcs.items()
                if (
                    npc.position == actor_room_id
                    or (active_encounter is not None and npc_id in active_encounter.npc_ids)
                )
            },
            "rooms_of_interest": rooms_of_interest,
            "encounters": {
                enc_id: summarize_encounter(enc)
                for enc_id, enc in world.encounters.items()
                if enc_id == world.active_encounter_id or enc.is_active
            },
            "objectives": {
                obj_id: {
                    "goal": obj.goal,
                    "is_completed": obj.is_completed,
                    "is_failed": obj.is_failed,
                }
                for obj_id, obj in world.objectives.items()
            },
            "active_encounter_id": world.active_encounter_id,
            "active_actor_id": world.active_actor_id,
            "awaiting_input_from": world.awaiting_input_from,
        },
    }


def build_intent_world_view(
    world: WorldState,
    actor_id: str,
    loop_index: int | None = None,
) -> dict[str, Any]:
    """Build an actor-knowledge-scoped world snapshot for intent generation."""
    world = world.sync_actor_knowledge([actor_id])

    actor = world.party.get(actor_id)
    actor_type = "pc"
    if actor is None:
        actor = world.npcs.get(actor_id)
        actor_type = "npc"

    actor_room_id = actor.position if actor is not None else None
    current_room = world.rooms.get(actor_room_id) if actor_room_id else None
    knowledge = world.actor_knowledge.get(actor_id)
    known_room_ids = knowledge.known_room_ids if knowledge is not None else ([actor_room_id] if actor_room_id else [])
    known_npc_ids = knowledge.known_npc_ids if knowledge is not None else []
    known_pc_ids = knowledge.known_pc_ids if knowledge is not None else [actor_id]

    visible_pcs = [
        summarize_party_member(pc)
        for pc_id, pc in world.party.items()
        if pc.position == actor_room_id and pc_id != actor_id
    ]
    visible_npcs = {
        npc_id: summarize_npc(npc)
        for npc_id, npc in world.npcs.items()
        if npc.position == actor_room_id and npc_id != actor_id and npc.is_alive
    }
    visible_allies = visible_pcs if actor_type == "pc" else list(visible_npcs.values())
    visible_tokens = {actor_id, *visible_npcs.keys(), *[ally["id"] for ally in visible_allies]}
    if actor_room_id:
        visible_tokens.add(actor_room_id)
    recent_turn_log = [
        entry
        for entry in world.turn_log
        if "[DM][game_start]" in entry or any(token in entry for token in visible_tokens)
    ][-6:]

    active_objectives = {
        obj_id: {
            "goal": obj.goal,
            "is_completed": obj.is_completed,
            "is_failed": obj.is_failed,
        }
        for obj_id, obj in world.objectives.items()
        if not obj.is_completed and not obj.is_failed
    }
    if not active_objectives:
        active_objectives = {
            obj_id: {
                "goal": obj.goal,
                "is_completed": obj.is_completed,
                "is_failed": obj.is_failed,
            }
            for obj_id, obj in world.objectives.items()
        }

    return {
        "scope": "intent_view",
        "adventure_title": world.adventure_title,
        "loop_index": loop_index,
        "session": {
            "game_session_id": world.game_session_id,
            "turn_count": world.turn_count,
            "loop_index": loop_index,
            "world_version": world.world_version,
            "active_actor_id": world.active_actor_id,
            "awaiting_input_from": world.awaiting_input_from,
            "active_encounter_id": world.active_encounter_id,
        },
        "actor": (
            summarize_party_member(actor)
            if actor is not None and actor_type == "pc"
            else summarize_npc(actor)
            if actor is not None and actor_type == "npc"
            else {"id": actor_id, "position": actor_room_id}
        ),
        "actor_type": actor_type,
        "knowledge": {
            "known_room_ids": known_room_ids,
            "known_npc_ids": known_npc_ids,
            "known_pc_ids": known_pc_ids,
            "last_seen_room_id": knowledge.last_seen_room_id if knowledge is not None else actor_room_id,
        },
        "known_party": {
            pc_id: {
                "id": pc.id,
                "name": pc.name,
                "class": pc.char_class,
                "level": pc.level,
                "is_alive": pc.is_alive,
            }
            for pc_id, pc in world.party.items()
            if pc_id in known_pc_ids
        },
        "current_scene": {
            "room_id": current_room.id if current_room is not None else actor_room_id,
            "room_name": current_room.name if current_room is not None else actor_room_id,
            "is_visited": current_room.is_visited if current_room is not None else False,
            "is_cleared": current_room.is_cleared if current_room is not None else False,
            "trap_disarmed": current_room.trap_disarmed if current_room is not None else None,
            "connections": current_room.connections if current_room is not None else [],
            "visible_allies": visible_allies,
            "visible_pcs": visible_pcs,
            "visible_npcs": visible_npcs,
        },
        "known_rooms": {
            room_id: {
                "room_id": room.id,
                "room_name": room.name,
                "is_visited": room.is_visited,
                "is_cleared": room.is_cleared,
                "trap_disarmed": room.trap_disarmed,
                "connections": room.connections,
            }
            for room_id, room in world.rooms.items()
            if room_id in known_room_ids
        },
        "known_npcs": {
            npc_id: {
                "id": npc.id,
                "name": npc.name,
                "type": npc.npc_type,
                "role": npc.role,
                "is_alive": npc.is_alive,
            }
            for npc_id, npc in world.npcs.items()
            if npc_id in known_npc_ids
        },
        "active_objectives": active_objectives,
        "relevant_rules": world.homebrew_rules,
        "recent_turn_log": recent_turn_log,
        "knowledge_summary": {
            "known_room_count": len([room_id for room_id in known_room_ids if room_id in world.rooms]),
            "known_npc_count": len([npc_id for npc_id in known_npc_ids if npc_id in world.npcs]),
            "withheld_sections": [
                "remote_party_positions",
                "undiscovered_rooms",
                "unseen_npcs",
                "full_world_state_dump",
            ],
        },
    }


def build_intent_payload(
    world: WorldState,
    actor_id: str,
    loop_index: int | None = None,
) -> str:
    """Build the intent-generator payload with actor-scoped world context."""
    actor_type = "pc" if actor_id in world.party else "npc"
    payload = {
        "actor_id": actor_id,
        "actor_type": actor_type,
        "goal": "Generate exactly one immediate action intent for this actor using only the actor-scoped knowledge provided.",
        "world_state": build_intent_world_view(world, actor_id, loop_index=loop_index),
    }
    return json.dumps(payload, indent=2)


def build_adjudicator_payload(
    world: WorldState,
    actor_id: str,
    action_text: str,
    loop_index: int | None = None,
) -> str:
    """Build the adjudicator payload with scoped world-state context."""
    payload = {
        "actor_id": actor_id,
        "action": action_text,
        "world_state": build_adjudicator_world_view(world, actor_id, loop_index=loop_index),
    }
    return json.dumps(payload, indent=2)


def build_extractor_payload(
    world: WorldState,
    adjudication: AdjudicatorResponse,
    loop_index: int | None = None,
) -> str:
    """Build the extractor payload with ruling and relevant world context."""
    active_encounter = (
        world.encounters.get(world.active_encounter_id)
        if world.active_encounter_id is not None
        else None
    )
    active_actor = None
    active_actor_type = None
    if world.active_actor_id:
        active_actor = world.party.get(world.active_actor_id)
        active_actor_type = "pc" if active_actor is not None else None
        if active_actor is None:
            active_actor = world.npcs.get(world.active_actor_id)
            active_actor_type = "npc" if active_actor is not None else None
    current_room = world.rooms.get(active_actor.position) if active_actor and active_actor.position else None

    relevant_room_ids = {
        pc.position
        for pc in world.party.values()
        if pc.position in world.rooms
    }
    if current_room is not None:
        relevant_room_ids.add(current_room.id)
    if active_encounter is not None and active_encounter.room_id in world.rooms:
        relevant_room_ids.add(active_encounter.room_id)

    for room_id in list(relevant_room_ids):
        room = world.rooms.get(room_id)
        if room is None:
            continue
        for connection in getattr(room, "connections", []):
            destination = connection.get("destination")
            if destination in world.rooms:
                relevant_room_ids.add(destination)

    npcs_of_interest = {
        npc_id: summarize_npc(npc)
        for npc_id, npc in world.npcs.items()
        if npc.position in relevant_room_ids
        or (
            active_encounter is not None
            and npc_id in active_encounter.npc_ids
        )
    }
    encounters_of_interest = {
        encounter_id: summarize_encounter(encounter)
        for encounter_id, encounter in world.encounters.items()
        if encounter.room_id in relevant_room_ids
        or encounter_id == world.active_encounter_id
    }

    payload = {
        "adjudication": adjudication.model_dump(),
        "world_state": {
            "game_session_id": world.game_session_id,
            "active_encounter_id": world.active_encounter_id,
            "turn_count": world.turn_count,
            "loop_index": loop_index,
            "session": {
                "game_session_id": world.game_session_id,
                "turn_count": world.turn_count,
                "loop_index": loop_index,
                "world_version": world.world_version,
                "active_actor_id": world.active_actor_id,
                "awaiting_input_from": world.awaiting_input_from,
            },
            "active_actor": (
                summarize_party_member(active_actor)
                if active_actor is not None and active_actor_type == "pc"
                else summarize_npc(active_actor)
                if active_actor is not None and active_actor_type == "npc"
                else None
            ),
            "party": {
                pc_id: {
                    "name": pc.name,
                    "position": pc.position,
                    "hp_current": pc.hp_current,
                    "hp_max": pc.hp_max,
                    "conditions": pc.conditions,
                }
                for pc_id, pc in world.party.items()
            },
            "current_scene": {
                "room_id": current_room.id if current_room is not None else None,
                "room_name": current_room.name if current_room is not None else None,
                "connections": current_room.connections if current_room is not None else [],
                "pc_ids": current_room.pc_ids if current_room is not None else [],
                "npc_ids": current_room.npc_ids if current_room is not None else [],
                "visible_pcs": {
                    pc_id: {
                        "name": pc.name,
                        "position": pc.position,
                        "hp_current": pc.hp_current,
                        "hp_max": pc.hp_max,
                        "conditions": pc.conditions,
                    }
                    for pc_id, pc in world.party.items()
                    if current_room is not None and pc.position == current_room.id
                },
                "visible_npcs": npcs_of_interest,
            },
            "rooms_of_interest": {
                room_id: summarize_room(room)
                for room_id, room in world.rooms.items()
                if room_id in relevant_room_ids
            },
            "npcs_of_interest": npcs_of_interest,
            "encounters_of_interest": encounters_of_interest,
            "active_encounter": (
                summarize_encounter(active_encounter)
                if active_encounter is not None
                else None
            ),
        },
    }
    return json.dumps(payload, indent=2)
