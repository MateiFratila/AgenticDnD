"""Deterministic dispatcher that applies WorldMutation lists to WorldState."""

from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from .mutations import MutationType, WorldMutation
from .state import EncounterState, ObjectiveState, RoomState, WorldState


class DispatchError(ValueError):
    """Raised when a mutation cannot be safely applied."""


class WorldStateDispatcher:
    """Applies validated world mutations in sequence."""

    def apply_mutations(
        self,
        world: WorldState,
        mutations: Sequence[WorldMutation],
    ) -> WorldState:
        """Apply all mutations recursively in order and return final state."""
        return self._apply_recursive(world, list(mutations), index=0)

    def _apply_recursive(
        self,
        world: WorldState,
        mutations: list[WorldMutation],
        index: int,
    ) -> WorldState:
        if index >= len(mutations):
            return world
        updated = self._apply_single(world, mutations[index])
        return self._apply_recursive(updated, mutations, index + 1)

    def _apply_single(self, world: WorldState, mutation: WorldMutation) -> WorldState:
        mutation_type = mutation.type

        if mutation_type == MutationType.MOVE_ENTITY:
            return self._apply_move_entity(world, mutation)
        if mutation_type == MutationType.APPLY_DAMAGE:
            return self._apply_damage(world, mutation)
        if mutation_type == MutationType.APPLY_HEAL:
            return self._apply_heal(world, mutation)
        if mutation_type == MutationType.ADD_CONDITION:
            return self._apply_add_condition(world, mutation)
        if mutation_type == MutationType.REMOVE_CONDITION:
            return self._apply_remove_condition(world, mutation)
        if mutation_type == MutationType.SET_ACTIVE_ENCOUNTER:
            return world.set_active_encounter(mutation.encounter_id)
        if mutation_type == MutationType.SET_ENCOUNTER_ACTIVE:
            return self._apply_set_encounter_active(world, mutation)
        if mutation_type == MutationType.SET_ENCOUNTER_CLEARED:
            return self._apply_set_encounter_cleared(world, mutation)
        if mutation_type == MutationType.MARK_OBJECTIVE_COMPLETE:
            return self._apply_set_objective_status(world, mutation, complete=True)
        if mutation_type == MutationType.MARK_OBJECTIVE_FAILED:
            return self._apply_set_objective_status(world, mutation, complete=False)
        if mutation_type == MutationType.MARK_ROOM_VISITED:
            return self._apply_mark_room_visited(world, mutation)
        if mutation_type == MutationType.MARK_ROOM_CLEARED:
            return self._apply_mark_room_cleared(world, mutation)
        if mutation_type == MutationType.DISARM_ROOM_TRAP:
            return self._apply_disarm_room_trap(world, mutation)
        if mutation_type == MutationType.APPEND_LOG_ENTRY:
            if not mutation.entry:
                raise DispatchError("append_log_entry requires entry")
            return world.add_log_entry(mutation.entry)
        if mutation_type == MutationType.INCREMENT_TURN:
            return world.increment_turn()
        if mutation_type == MutationType.SET_ACTIVE_ACTOR:
            return world.set_active_actor(mutation.actor_id)
        if mutation_type == MutationType.SET_AWAITING_INPUT:
            return world.set_awaiting_input(mutation.actor_id)
        if mutation_type == MutationType.INCREMENT_VERSION:
            return world.increment_version()

        raise DispatchError(f"Unsupported mutation type: {mutation_type}")

    def _apply_move_entity(self, world: WorldState, mutation: WorldMutation) -> WorldState:
        if not mutation.entity_id:
            raise DispatchError("move_entity requires entity_id")
        if not mutation.to_room_id:
            raise DispatchError("move_entity requires to_room_id")
        if mutation.to_room_id not in world.rooms:
            raise DispatchError(f"Unknown room id: {mutation.to_room_id}")

        entity_id = mutation.entity_id
        to_room_id = mutation.to_room_id

        if entity_id in world.party:
            pc = world.party[entity_id]
            from_room_id = pc.position
            updated_world = world.update_pc(entity_id, pc.move_to(to_room_id))
            return self._sync_pc_room_membership(updated_world, entity_id, from_room_id, to_room_id)

        if entity_id in world.npcs:
            npc = world.npcs[entity_id]
            from_room_id = npc.position
            updated_world = world.update_npc(entity_id, npc.move_to(to_room_id))
            return self._sync_npc_room_membership(updated_world, entity_id, from_room_id, to_room_id)

        raise DispatchError(f"Unknown entity id: {entity_id}")

    def _apply_damage(self, world: WorldState, mutation: WorldMutation) -> WorldState:
        if not mutation.target_id:
            raise DispatchError("apply_damage requires target_id")
        if mutation.amount is None:
            raise DispatchError("apply_damage requires amount")
        amount = max(0, mutation.amount)

        if mutation.target_id in world.party:
            pc = world.party[mutation.target_id]
            return world.update_pc(mutation.target_id, pc.take_damage(amount))
        if mutation.target_id in world.npcs:
            npc = world.npcs[mutation.target_id]
            return world.update_npc(mutation.target_id, npc.take_damage(amount))

        raise DispatchError(f"Unknown target id: {mutation.target_id}")

    def _apply_heal(self, world: WorldState, mutation: WorldMutation) -> WorldState:
        if not mutation.target_id:
            raise DispatchError("apply_heal requires target_id")
        if mutation.amount is None:
            raise DispatchError("apply_heal requires amount")
        amount = max(0, mutation.amount)

        if mutation.target_id in world.party:
            pc = world.party[mutation.target_id]
            return world.update_pc(mutation.target_id, pc.heal(amount))
        if mutation.target_id in world.npcs:
            npc = world.npcs[mutation.target_id]
            healed_npc = replace(
                npc,
                hp_current=min(npc.hp_max, npc.hp_current + amount),
                is_alive=True,
            )
            return world.update_npc(mutation.target_id, healed_npc)

        raise DispatchError(f"Unknown target id: {mutation.target_id}")

    def _apply_add_condition(self, world: WorldState, mutation: WorldMutation) -> WorldState:
        if not mutation.target_id:
            raise DispatchError("add_condition requires target_id")
        if not mutation.condition:
            raise DispatchError("add_condition requires condition")
        pc = world.party[mutation.target_id]
        return world.update_pc(mutation.target_id, pc.add_condition(mutation.condition))

    def _apply_remove_condition(self, world: WorldState, mutation: WorldMutation) -> WorldState:
        if not mutation.target_id:
            raise DispatchError("remove_condition requires target_id")
        if not mutation.condition:
            raise DispatchError("remove_condition requires condition")
        pc = world.party[mutation.target_id]
        return world.update_pc(mutation.target_id, pc.remove_condition(mutation.condition))

    def _apply_set_encounter_active(self, world: WorldState, mutation: WorldMutation) -> WorldState:
        if not mutation.encounter_id:
            raise DispatchError("set_encounter_active requires encounter_id")
        if mutation.encounter_id not in world.encounters:
            raise DispatchError(f"Unknown encounter id: {mutation.encounter_id}")

        enc = world.encounters[mutation.encounter_id]
        is_active = True if mutation.is_active is None else mutation.is_active
        return world.update_encounter(mutation.encounter_id, replace(enc, is_active=is_active))

    def _apply_set_encounter_cleared(self, world: WorldState, mutation: WorldMutation) -> WorldState:
        if not mutation.encounter_id:
            raise DispatchError("set_encounter_cleared requires encounter_id")
        if mutation.encounter_id not in world.encounters:
            raise DispatchError(f"Unknown encounter id: {mutation.encounter_id}")

        enc = world.encounters[mutation.encounter_id]
        is_cleared = True if mutation.is_cleared is None else mutation.is_cleared
        return world.update_encounter(mutation.encounter_id, replace(enc, is_cleared=is_cleared))

    def _apply_set_objective_status(
        self,
        world: WorldState,
        mutation: WorldMutation,
        complete: bool,
    ) -> WorldState:
        if not mutation.objective_id:
            raise DispatchError("Objective mutation requires objective_id")
        if mutation.objective_id not in world.objectives:
            raise DispatchError(f"Unknown objective id: {mutation.objective_id}")

        obj = world.objectives[mutation.objective_id]
        updated = ObjectiveState(
            id=obj.id,
            goal=obj.goal,
            is_completed=complete,
            is_failed=not complete,
        )
        return world.update_objective(mutation.objective_id, updated)

    def _apply_mark_room_visited(self, world: WorldState, mutation: WorldMutation) -> WorldState:
        if not mutation.room_id:
            raise DispatchError("mark_room_visited requires room_id")
        if mutation.room_id not in world.rooms:
            raise DispatchError(f"Unknown room id: {mutation.room_id}")

        room = world.rooms[mutation.room_id]
        return world.update_room(mutation.room_id, replace(room, is_visited=True))

    def _apply_mark_room_cleared(self, world: WorldState, mutation: WorldMutation) -> WorldState:
        if not mutation.room_id:
            raise DispatchError("mark_room_cleared requires room_id")
        if mutation.room_id not in world.rooms:
            raise DispatchError(f"Unknown room id: {mutation.room_id}")

        room = world.rooms[mutation.room_id]
        return world.update_room(mutation.room_id, replace(room, is_cleared=True))

    def _apply_disarm_room_trap(self, world: WorldState, mutation: WorldMutation) -> WorldState:
        if not mutation.room_id:
            raise DispatchError("disarm_room_trap requires room_id")
        if mutation.room_id not in world.rooms:
            raise DispatchError(f"Unknown room id: {mutation.room_id}")

        room = world.rooms[mutation.room_id]
        return world.update_room(mutation.room_id, replace(room, trap_disarmed=True))

    def _sync_pc_room_membership(
        self,
        world: WorldState,
        pc_id: str,
        from_room_id: str,
        to_room_id: str,
    ) -> WorldState:
        updated_world = world

        if from_room_id in updated_world.rooms:
            from_room = updated_world.rooms[from_room_id]
            updated_world = updated_world.update_room(
                from_room_id,
                replace(
                    from_room,
                    pc_ids=[item for item in from_room.pc_ids if item != pc_id],
                ),
            )

        to_room = updated_world.rooms[to_room_id]
        if pc_id not in to_room.pc_ids:
            updated_world = updated_world.update_room(
                to_room_id,
                replace(to_room, pc_ids=[*to_room.pc_ids, pc_id]),
            )

        return updated_world

    def _sync_npc_room_membership(
        self,
        world: WorldState,
        npc_id: str,
        from_room_id: str,
        to_room_id: str,
    ) -> WorldState:
        updated_world = world

        if from_room_id in updated_world.rooms:
            from_room = updated_world.rooms[from_room_id]
            updated_world = updated_world.update_room(
                from_room_id,
                replace(
                    from_room,
                    npc_ids=[item for item in from_room.npc_ids if item != npc_id],
                ),
            )

        to_room = updated_world.rooms[to_room_id]
        if npc_id not in to_room.npc_ids:
            updated_world = updated_world.update_room(
                to_room_id,
                replace(to_room, npc_ids=[*to_room.npc_ids, npc_id]),
            )

        return updated_world
