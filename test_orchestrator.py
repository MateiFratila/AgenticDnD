"""Tests for table orchestrator flow and transition logging."""

import json
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.agents.contracts import (
    AdjudicatorResponse,
    DestinationRoute,
    ExtractorMutation,
    ExtractorResponse,
    IntentResponse,
)
from backend.orchestrator import TableOrchestrator, TableStep
from backend.world import AdventureLoader, EncounterTurnEntry


class FakeAdjudicatorAgent:
    """Fake LLM adjudicator wrapper used by orchestrator from_agents tests."""

    def __init__(self):
        self.last_payload = None
        self.payloads = []

    def think_adjudication(self, user_input: str) -> AdjudicatorResponse:
        self.last_payload = json.loads(user_input)
        self.payloads.append(self.last_payload)
        return _approved_adjudicator(None, "aldric_stonehammer", "")


class FakeExtractorAgent:
    """Fake LLM extractor wrapper used by orchestrator from_agents tests."""

    def __init__(self):
        self.last_payload = None

    def think_extraction(self, user_input: str) -> ExtractorResponse:
        self.last_payload = json.loads(user_input)
        return _approved_extractor(None, _approved_adjudicator(None, "", ""))


class FakeIntentAgent:
    """Fake intent generator used for empty-action and NPC auto-turn tests."""

    def __init__(self):
        self.payloads = []

    def think_intent(self, user_input: str) -> IntentResponse:
        payload = json.loads(user_input)
        self.payloads.append(payload)
        actor_id = payload["actor_id"]
        return IntentResponse(
            intent=f"{actor_id} takes a cautious tactical action.",
            in_character_note=f"{actor_id} hesitates for a heartbeat before acting.",
            reasoning="Test double generated a deterministic action for the active actor.",
        )


def _game_start_adjudicator(world, actor_id: str, action_text: str) -> AdjudicatorResponse:
    """Fake opening-scene adjudicator response."""
    return AdjudicatorResponse(
        status="game_start",
        ruling="The grotto mouth yawns ahead, and the hunt for the Shard of Kaelas begins.",
        destination=[
            DestinationRoute(
                actor="extractor",
                purpose="Record the opening scene and initialize play",
                payload_hint="Emit any safe start-of-adventure mutations",
            )
        ],
        reasoning="Opening scene setup for a fresh session.",
        suggested_alternatives=[],
    )


def _approved_adjudicator(world, actor_id: str, action_text: str) -> AdjudicatorResponse:
    """Fake adjudicator for deterministic orchestrator testing."""
    return AdjudicatorResponse(
        status="approved",
        ruling="Aldric charges and slams the goblin for 9 damage.",
        destination=[
            DestinationRoute(
                actor="extractor",
                purpose="Map approved ruling to world mutations",
                payload_hint="Emit mutation array",
            )
        ],
        reasoning="Legal movement and successful hit.",
        suggested_alternatives=[],
    )


def _approved_extractor(world, adjudication: AdjudicatorResponse) -> ExtractorResponse:
    """Fake extractor for deterministic orchestrator testing."""
    return ExtractorResponse(
        root=[
            ExtractorMutation(
                type="move_entity",
                entity_id="aldric_stonehammer",
                to_room_id="goblin_barracks",
            ),
            ExtractorMutation(
                type="apply_damage",
                target_id="aldric_stonehammer",
                amount=4,
            ),
            ExtractorMutation(
                type="append_log_entry",
                entry="[WORLD] Aldric executed approved action.",
            ),
            ExtractorMutation(type="increment_turn"),
        ]
    )


def _rejected_adjudicator(world, actor_id: str, action_text: str) -> AdjudicatorResponse:
    """Fake rejection path to ensure no world mutation commit happens."""
    return AdjudicatorResponse(
        status="rejected",
        ruling="You cannot move through a blocked passage this turn.",
        destination=[
            DestinationRoute(
                actor=actor_id,
                purpose="Provide a different legal action",
                payload_hint="Choose a reachable target",
            )
        ],
        reasoning="Path is blocked by hazard.",
        requires_player_response=True,
        follow_up_actor=actor_id,
        suggested_alternatives=["Attack from current room", "Use Dash toward a valid corridor"],
    )


def _pending_roll_adjudicator(world, actor_id: str, action_text: str) -> AdjudicatorResponse:
    """Fake unresolved skill-check ruling that should keep the same actor awaiting input."""
    return AdjudicatorResponse(
        status="needs_clarification",
        ruling="Sylara slips toward the tunnel mouth. Roll Dexterity (Stealth) to determine whether you enter undetected.",
        destination=[
            DestinationRoute(
                actor=actor_id,
                purpose="Roll the requested Stealth check",
                payload_hint="Provide the check result before the action resolves",
            )
        ],
        reasoning="The declared stealth approach is legal but the outcome depends on a roll.",
        requires_player_response=True,
        follow_up_actor=actor_id,
        suggested_alternatives=[],
    )


def _empty_extractor(world, adjudication: AdjudicatorResponse) -> ExtractorResponse:
    """Fake extractor returning no canonical mutations for unresolved-roll scenarios."""
    return ExtractorResponse(root=[])


def _log_only_adjudicator(world, actor_id: str, action_text: str) -> AdjudicatorResponse:
    """Minimal adjudicator used for intent-generation and NPC resolution tests."""
    return AdjudicatorResponse(
        status="approved",
        ruling=f"{actor_id} commits to: {action_text}",
        destination=[
            DestinationRoute(
                actor="extractor",
                purpose="Record the committed action in the world log",
                payload_hint="Append a log entry and finalize the turn",
            )
        ],
        reasoning="The declared action is safe to resolve deterministically for test coverage.",
        suggested_alternatives=[],
    )


def _log_only_extractor(world, adjudication: AdjudicatorResponse) -> ExtractorResponse:
    """Minimal extractor that appends the adjudicated ruling to the world log."""
    return ExtractorResponse(
        root=[
            ExtractorMutation(
                type="append_log_entry",
                entry=f"[WORLD] {adjudication.ruling}",
            )
        ]
    )


class SequencedIntentAgent:
    """Intent test double that returns a per-actor sequence of responses across follow-up passes."""

    def __init__(self, sequences: dict[str, list[str]]):
        self.sequences = {actor_id: list(values) for actor_id, values in sequences.items()}
        self.payloads = []

    def think_intent(self, user_input: str) -> IntentResponse:
        payload = json.loads(user_input)
        self.payloads.append(payload)
        actor_id = payload["actor_id"]
        queued = self.sequences.get(actor_id, [f"{actor_id} waits and watches carefully."])
        intent_text = queued.pop(0) if queued else f"{actor_id} waits and watches carefully."
        self.sequences[actor_id] = queued
        return IntentResponse(
            intent=intent_text,
            in_character_note=f"{actor_id} reacts to the unfolding exchange.",
            reasoning="Sequenced test intent generated for multi-pass encounter resolution.",
        )


def test_orchestrator_game_start_history_label():
    """The first DM history entry should use the game_start label even for an opening approved turn."""
    assets_dir = Path(__file__).parent / "assets"
    with TemporaryDirectory() as temp_dir:
        snapshot_dir = Path(temp_dir) / "snapshots"
        loader = AdventureLoader(assets_dir, snapshot_dir=snapshot_dir)
        world = loader.load_adventure(
            adventure_file="adventure_sunken_grotto.json",
            pc_files=["pc_aldric_stonehammer.json", "pc_sylara_nightveil.json"],
            rules_file="homebrew_rules.json",
        )

        table = TableOrchestrator(
            world=world,
            turn_order=["aldric_stonehammer", "sylara_nightveil"],
            adjudicator_fn=_approved_adjudicator,
            extractor_fn=_approved_extractor,
            snapshot_dir=snapshot_dir,
        )

        result = table.process_intent("Adventure Start: Establish the opening scene and immediate objective for the party.")

    assert result.status == "approved"
    assert table.world.turn_log[0].startswith("[DM][game_start][aldric_stonehammer]")
    assert "Aldric charges and slams the goblin for 9 damage." in table.world.turn_log[0]
    print("✓ Orchestrator game_start history labeling passed")


def test_orchestrator_pending_roll_keeps_same_actor():
    """If the DM asks for a roll, the same actor should remain awaited instead of advancing turn."""
    assets_dir = Path(__file__).parent / "assets"
    with TemporaryDirectory() as temp_dir:
        snapshot_dir = Path(temp_dir) / "snapshots"
        loader = AdventureLoader(assets_dir, snapshot_dir=snapshot_dir)
        world = loader.load_adventure(
            adventure_file="adventure_sunken_grotto.json",
            pc_files=["pc_aldric_stonehammer.json", "pc_sylara_nightveil.json"],
            rules_file="homebrew_rules.json",
        ).add_log_entry("[DM][game_start][sylara_nightveil] The adventure begins at the grotto mouth.")

        table = TableOrchestrator(
            world=world,
            turn_order=["sylara_nightveil", "aldric_stonehammer"],
            adjudicator_fn=_pending_roll_adjudicator,
            extractor_fn=_empty_extractor,
            snapshot_dir=snapshot_dir,
        )

        result = table.process_intent("I creep forward and try to stay hidden.")

    assert result.status == "needs_clarification"
    assert result.advanced_turn is False
    assert result.awaiting_actor_id == "sylara_nightveil"
    assert table.world.active_actor_id == "sylara_nightveil"
    assert table.world.awaiting_input_from == "sylara_nightveil"
    assert table.current_actor_id == "sylara_nightveil"
    print("✓ Pending roll keeps the same actor awaiting input")


def test_orchestrator_approved_damage_roll_reasoning_still_commits_extractor_mutations():
    """Approved rulings should still commit when the reasoning mentions a completed damage roll."""
    assets_dir = Path(__file__).parent / "assets"
    with TemporaryDirectory() as temp_dir:
        snapshot_dir = Path(temp_dir) / "snapshots"
        loader = AdventureLoader(assets_dir, snapshot_dir=snapshot_dir)
        world = loader.load_adventure(
            adventure_file="adventure_sunken_grotto.json",
            pc_files=["pc_aldric_stonehammer.json", "pc_sylara_nightveil.json"],
            rules_file="homebrew_rules.json",
        ).add_log_entry("[DM][game_start][aldric_stonehammer] The adventure begins at the grotto mouth.")

        def approved_damage_roll_adjudicator(world, actor_id: str, action_text: str) -> AdjudicatorResponse:
            return AdjudicatorResponse(
                status="approved",
                ruling="Aldric's warhammer caves in the Goblin Boss's skull and drops it on the spot.",
                destination=[
                    DestinationRoute(
                        actor="extractor",
                        purpose="Commit the killing blow to the world state",
                        payload_hint="Apply the 21 damage and mark the goblin dead",
                    )
                ],
                reasoning="Damage roll of 21 equals the Goblin Boss's 21 HP, so the approved hit should now resolve canonically.",
                requires_player_response=False,
                follow_up_actor=None,
                suggested_alternatives=[],
            )

        def kill_goblin_extractor(world, adjudication: AdjudicatorResponse) -> ExtractorResponse:
            return ExtractorResponse(
                root=[
                    ExtractorMutation(
                        type="apply_damage",
                        target_id="encounter_1_enemy_0",
                        amount=21,
                    ),
                    ExtractorMutation(
                        type="append_log_entry",
                        entry="[WORLD] Aldric drops the Goblin Boss with a crushing warhammer hit.",
                    ),
                ]
            )

        table = TableOrchestrator(
            world=world,
            turn_order=["aldric_stonehammer", "sylara_nightveil"],
            adjudicator_fn=approved_damage_roll_adjudicator,
            extractor_fn=kill_goblin_extractor,
            snapshot_dir=snapshot_dir,
        )

        result = table.process_intent("I roll 9 bludgeoning damage with my warhammer.")

    goblin = table.world.npcs["encounter_1_enemy_0"]
    assert result.status == "approved"
    assert result.advanced_turn is True
    assert result.applied_mutation_count == 2
    assert result.awaiting_actor_id == "sylara_nightveil"
    assert goblin.hp_current == 0
    assert goblin.is_alive is False
    print("✓ Approved damage-roll follow-up still commits extractor mutations")


def test_orchestrator_can_mark_dead_npc_as_looted():
    """Searching a corpse should be representable as inventory gain plus a looted condition on the dead NPC."""
    assets_dir = Path(__file__).parent / "assets"
    with TemporaryDirectory() as temp_dir:
        snapshot_dir = Path(temp_dir) / "snapshots"
        loader = AdventureLoader(assets_dir, snapshot_dir=snapshot_dir)
        world = loader.load_adventure(
            adventure_file="adventure_sunken_grotto.json",
            pc_files=["pc_aldric_stonehammer.json", "pc_sylara_nightveil.json"],
            rules_file="homebrew_rules.json",
        )
        dead_boss = world.npcs["encounter_1_enemy_0"].take_damage(world.npcs["encounter_1_enemy_0"].hp_current)
        world = world.update_npc("encounter_1_enemy_0", dead_boss)

        def loot_corpse_adjudicator(world, actor_id: str, action_text: str) -> AdjudicatorResponse:
            return AdjudicatorResponse(
                status="approved",
                ruling="Sylara searches the fallen Goblin Boss and pockets a bronze key and a bloodstained note.",
                destination=[
                    DestinationRoute(
                        actor="extractor",
                        purpose="Commit the discovered loot and mark the corpse as searched",
                        payload_hint="Add the found items and mark the dead boss as looted",
                    )
                ],
                reasoning="The target is dead and the search succeeds without uncertainty.",
                suggested_alternatives=[],
            )

        def loot_corpse_extractor(world, adjudication: AdjudicatorResponse) -> ExtractorResponse:
            return ExtractorResponse(
                root=[
                    ExtractorMutation(
                        type="item_add",
                        target_id="sylara_nightveil",
                        item="Bronze key",
                    ),
                    ExtractorMutation(
                        type="item_add",
                        target_id="sylara_nightveil",
                        item="Bloodstained note",
                    ),
                    ExtractorMutation(
                        type="add_condition",
                        target_id="encounter_1_enemy_0",
                        condition="looted",
                    ),
                    ExtractorMutation(
                        type="append_log_entry",
                        entry="[WORLD] Sylara loots the Goblin Boss's corpse.",
                    ),
                ]
            )

        table = TableOrchestrator(
            world=world,
            turn_order=["sylara_nightveil", "aldric_stonehammer"],
            adjudicator_fn=loot_corpse_adjudicator,
            extractor_fn=loot_corpse_extractor,
            snapshot_dir=snapshot_dir,
        )

        result = table.process_intent("I search the Goblin Boss's corpse.")

    boss = table.world.npcs["encounter_1_enemy_0"]
    sylara = table.world.party["sylara_nightveil"]
    assert result.status == "approved"
    assert "Bronze key" in sylara.inventory
    assert "Bloodstained note" in sylara.inventory
    assert "looted" in boss.conditions
    assert boss.is_alive is False
    print("✓ Orchestrator can mark dead NPCs as looted")


def test_orchestrator_approved_flow():
    """Approved adjudication should call extractor and apply mutations."""
    assets_dir = Path(__file__).parent / "assets"
    with TemporaryDirectory() as temp_dir:
        snapshot_dir = Path(temp_dir) / "snapshots"
        loader = AdventureLoader(assets_dir, snapshot_dir=snapshot_dir)
        world = loader.load_adventure(
            adventure_file="adventure_sunken_grotto.json",
            pc_files=["pc_aldric_stonehammer.json", "pc_sylara_nightveil.json"],
            rules_file="homebrew_rules.json",
        ).add_log_entry("[DM][game_start][aldric_stonehammer] The adventure begins at the grotto mouth.")

        table = TableOrchestrator(
            world=world,
            turn_order=["aldric_stonehammer", "sylara_nightveil"],
            adjudicator_fn=_approved_adjudicator,
            extractor_fn=_approved_extractor,
            snapshot_dir=snapshot_dir,
        )

        result = table.process_intent("I rush the goblin and attack.")

    assert result.status == "approved"
    assert result.advanced_turn is True
    assert result.applied_mutation_count == 4
    assert result.awaiting_actor_id == "sylara_nightveil"

    aldric = table.world.party["aldric_stonehammer"]
    assert aldric.position == "goblin_barracks"
    assert aldric.hp_current == 48

    # Session metadata — world is now authoritative source of truth for turn state.
    assert table.world.active_actor_id == "sylara_nightveil"
    assert table.world.awaiting_input_from == "sylara_nightveil"
    assert table.world.world_version == 1
    assert any(entry.startswith("[DM][approved][aldric_stonehammer]") for entry in table.world.turn_log)
    assert any("Aldric charges and slams the goblin for 9 damage." in entry for entry in table.world.turn_log)

    transition_steps = [event.to_step for event in result.events]
    assert TableStep.ADJUDICATING in transition_steps
    assert TableStep.EXTRACTING in transition_steps
    assert TableStep.APPLYING_MUTATIONS in transition_steps
    assert TableStep.TURN_COMPLETE in transition_steps
    assert transition_steps[-1] == TableStep.WAITING_FOR_INTENT
    print("✓ Orchestrator approved flow with step transitions passed")


def test_orchestrator_rejected_flow_no_mutation():
    """Rejected adjudication should not call world mutation flow."""
    assets_dir = Path(__file__).parent / "assets"
    with TemporaryDirectory() as temp_dir:
        snapshot_dir = Path(temp_dir) / "snapshots"
        loader = AdventureLoader(assets_dir, snapshot_dir=snapshot_dir)
        world = loader.load_adventure(
            adventure_file="adventure_sunken_grotto.json",
            pc_files=["pc_aldric_stonehammer.json", "pc_sylara_nightveil.json"],
            rules_file="homebrew_rules.json",
        ).add_log_entry("[DM][game_start][aldric_stonehammer] The adventure begins at the grotto mouth.")

        table = TableOrchestrator(
            world=world,
            turn_order=["aldric_stonehammer", "sylara_nightveil"],
            adjudicator_fn=_rejected_adjudicator,
            extractor_fn=_approved_extractor,
            snapshot_dir=snapshot_dir,
        )

        result = table.process_intent("I phase through the wall.")

    assert result.status == "rejected"
    assert result.advanced_turn is False
    assert result.applied_mutation_count == 0
    assert result.awaiting_actor_id == "aldric_stonehammer"

    aldric = table.world.party["aldric_stonehammer"]
    assert aldric.position == "entrance"
    assert table.current_actor_id == "aldric_stonehammer"

    # Rejection must NOT advance version; actor must remain blocked.
    assert table.world.active_actor_id == "aldric_stonehammer"
    assert table.world.awaiting_input_from == "aldric_stonehammer"
    assert table.world.world_version == 0
    assert any(entry.startswith("[DM][rejected][aldric_stonehammer]") for entry in table.world.turn_log)
    assert any("You cannot move through a blocked passage this turn." in entry for entry in table.world.turn_log)

    transition_steps = [event.to_step for event in result.events]
    assert TableStep.ADJUDICATING in transition_steps
    assert transition_steps[-1] == TableStep.WAITING_FOR_INTENT
    print("✓ Orchestrator rejection flow with no commit passed")


def test_orchestrator_from_agents_llm_response_handling():
    """Orchestrator should build payloads and process validated agent responses."""
    assets_dir = Path(__file__).parent / "assets"
    with TemporaryDirectory() as temp_dir:
        snapshot_dir = Path(temp_dir) / "snapshots"
        loader = AdventureLoader(assets_dir, snapshot_dir=snapshot_dir)
        world = loader.load_adventure(
            adventure_file="adventure_sunken_grotto.json",
            pc_files=["pc_aldric_stonehammer.json", "pc_sylara_nightveil.json"],
            rules_file="homebrew_rules.json",
        )

        adjudicator_agent = FakeAdjudicatorAgent()
        extractor_agent = FakeExtractorAgent()

        table = TableOrchestrator.from_agents(
            world=world,
            turn_order=["aldric_stonehammer", "sylara_nightveil"],
            adjudicator_agent=adjudicator_agent,
            extractor_agent=extractor_agent,
            snapshot_dir=snapshot_dir,
        )

        result = table.process_intent("I rush the goblin and attack.")

    assert result.status == "approved"
    assert result.applied_mutation_count == 4
    assert result.resolved_action is not None
    assert result.resolved_action.source == "player"
    assert result.resolved_action.action == "I rush the goblin and attack."
    assert adjudicator_agent.last_payload is not None
    assert extractor_agent.last_payload is not None
    assert adjudicator_agent.last_payload["action"] == "I rush the goblin and attack."
    assert adjudicator_agent.last_payload["actor_id"] == "aldric_stonehammer"
    assert adjudicator_agent.last_payload["world_state"]["scope"] == "adjudicator_view"
    assert adjudicator_agent.last_payload["world_state"]["summary"]["actor"]["id"] == "aldric_stonehammer"
    assert "adjudication" in extractor_agent.last_payload
    assert extractor_agent.last_payload["adjudication"]["status"] == "approved"
    print("✓ Orchestrator from_agents LLM response handling passed")


def test_orchestrator_empty_action_uses_intent_agent_and_resolves_active_npcs():
    """Empty actor input should be generated by the intent agent, then active encounter NPCs should auto-resolve safely."""
    assets_dir = Path(__file__).parent / "assets"
    with TemporaryDirectory() as temp_dir:
        snapshot_dir = Path(temp_dir) / "snapshots"
        loader = AdventureLoader(assets_dir, snapshot_dir=snapshot_dir)
        world = loader.load_adventure(
            adventure_file="adventure_sunken_grotto.json",
            pc_files=["pc_aldric_stonehammer.json", "pc_sylara_nightveil.json"],
            rules_file="homebrew_rules.json",
        )
        encounter_id = next(iter(world.encounters.keys()))
        world = world.set_active_encounter(encounter_id)
        world = world.update_encounter(
            encounter_id,
            replace(
                world.encounters[encounter_id],
                is_active=True,
                turn_order=[
                    EncounterTurnEntry(actor_id="aldric_stonehammer", initiative_roll=18),
                    EncounterTurnEntry(actor_id="encounter_1_enemy_0", initiative_roll=14),
                    EncounterTurnEntry(actor_id="sylara_nightveil", initiative_roll=11),
                ],
                current_turn_index=0,
            ),
        )

        intent_agent = FakeIntentAgent()
        adjudicator_agent = FakeAdjudicatorAgent()
        extractor_agent = FakeExtractorAgent()

        table = TableOrchestrator.from_agents(
            world=world,
            turn_order=["aldric_stonehammer", "sylara_nightveil"],
            adjudicator_agent=adjudicator_agent,
            extractor_agent=extractor_agent,
            intent_agent=intent_agent,
            snapshot_dir=snapshot_dir,
        )

        result = table.process_intent("")

    assert result.generated_action == "aldric_stonehammer takes a cautious tactical action."
    assert result.resolved_action is not None
    assert result.resolved_action.source == "intent_agent"
    assert result.resolved_action.action == "aldric_stonehammer takes a cautious tactical action."
    assert intent_agent.payloads[0]["actor_id"] == "aldric_stonehammer"
    assert (
        intent_agent.payloads[0]["world_state"]["session"]["loop_index"]
        == adjudicator_agent.payloads[0]["world_state"]["summary"]["session"]["loop_index"]
    )
    assert len(result.npc_turns) == 1
    assert result.npc_turns[0].generated_action == "encounter_1_enemy_0 takes a cautious tactical action."
    assert table.world.awaiting_input_from == "sylara_nightveil"
    assert table.world.encounters[encounter_id].current_turn_index == 2
    print("✓ Empty actions use the intent agent and encounter turn order routes to the next PC")


def test_orchestrator_encounter_turn_wraps_and_increments_round_count():
    """Encounter-owned turn order should wrap cleanly and increment the encounter round counter."""
    assets_dir = Path(__file__).parent / "assets"
    with TemporaryDirectory() as temp_dir:
        snapshot_dir = Path(temp_dir) / "snapshots"
        loader = AdventureLoader(assets_dir, snapshot_dir=snapshot_dir)
        world = loader.load_adventure(
            adventure_file="adventure_sunken_grotto.json",
            pc_files=["pc_aldric_stonehammer.json", "pc_sylara_nightveil.json"],
            rules_file="homebrew_rules.json",
        )
        encounter_id = next(iter(world.encounters.keys()))
        world = world.set_active_encounter(encounter_id)
        world = world.update_encounter(
            encounter_id,
            replace(
                world.encounters[encounter_id],
                is_active=True,
                turn_order=[
                    EncounterTurnEntry(actor_id="aldric_stonehammer", initiative_roll=18),
                    EncounterTurnEntry(actor_id="encounter_1_enemy_0", initiative_roll=14),
                ],
                current_turn_index=0,
            ),
        )

        table = TableOrchestrator.from_agents(
            world=world,
            turn_order=["aldric_stonehammer"],
            adjudicator_agent=FakeAdjudicatorAgent(),
            extractor_agent=FakeExtractorAgent(),
            intent_agent=FakeIntentAgent(),
            snapshot_dir=snapshot_dir,
        )

        result = table.process_intent("I hold the chokepoint and brace for the goblin.")

    assert len(result.npc_turns) == 1
    assert result.awaiting_actor_id == "aldric_stonehammer"
    assert table.world.awaiting_input_from == "aldric_stonehammer"
    assert table.world.encounters[encounter_id].current_turn_index == 0
    assert table.world.encounters[encounter_id].round_count == 1
    print("✓ Encounter turn order wraps and increments round_count")


def test_orchestrator_ignores_stale_cleared_encounter_turn_order():
    """A cleared/inactive encounter should no longer control current_actor_id even if the pointer is still present."""
    assets_dir = Path(__file__).parent / "assets"
    with TemporaryDirectory() as temp_dir:
        snapshot_dir = Path(temp_dir) / "snapshots"
        loader = AdventureLoader(assets_dir, snapshot_dir=snapshot_dir)
        world = loader.load_adventure(
            adventure_file="adventure_sunken_grotto.json",
            pc_files=["pc_aldric_stonehammer.json", "pc_sylara_nightveil.json"],
            rules_file="homebrew_rules.json",
        )
        encounter_id = next(iter(world.encounters.keys()))
        world = world.set_active_encounter(encounter_id)
        world = world.update_encounter(
            encounter_id,
            replace(
                world.encounters[encounter_id],
                is_active=False,
                is_cleared=True,
                turn_order=[
                    EncounterTurnEntry(actor_id="sylara_nightveil", initiative_roll=18),
                    EncounterTurnEntry(actor_id="encounter_1_enemy_0", initiative_roll=14),
                ],
                current_turn_index=1,
            ),
        )

        table = TableOrchestrator(
            world=world,
            turn_order=["aldric_stonehammer", "sylara_nightveil"],
            adjudicator_fn=_log_only_adjudicator,
            extractor_fn=_log_only_extractor,
            snapshot_dir=snapshot_dir,
        )

    assert table.current_actor_id == "aldric_stonehammer"
    assert table.world.awaiting_input_from == "aldric_stonehammer"
    print("✓ Cleared encounters no longer hijack turn order")


def test_orchestrator_npc_needs_clarification_auto_resolves_follow_up_roll():
    """NPC clarification prompts should self-resolve through additional intent passes instead of pausing immediately."""
    assets_dir = Path(__file__).parent / "assets"
    with TemporaryDirectory() as temp_dir:
        snapshot_dir = Path(temp_dir) / "snapshots"
        loader = AdventureLoader(assets_dir, snapshot_dir=snapshot_dir)
        world = loader.load_adventure(
            adventure_file="adventure_sunken_grotto.json",
            pc_files=["pc_aldric_stonehammer.json", "pc_sylara_nightveil.json"],
            rules_file="homebrew_rules.json",
        )
        encounter_id = next(iter(world.encounters.keys()))
        world = world.set_active_encounter(encounter_id)
        world = world.update_encounter(
            encounter_id,
            replace(
                world.encounters[encounter_id],
                is_active=True,
                turn_order=[
                    EncounterTurnEntry(actor_id="aldric_stonehammer", initiative_roll=18),
                    EncounterTurnEntry(actor_id="encounter_1_enemy_0", initiative_roll=14),
                    EncounterTurnEntry(actor_id="sylara_nightveil", initiative_roll=11),
                ],
                current_turn_index=0,
            ),
        )

        intent_agent = SequencedIntentAgent(
            {
                "encounter_1_enemy_0": [
                    "I attack Aldric Stonehammer with my scimitar.",
                    "I make the requested attack roll: 16.",
                ]
            }
        )

        def clarifying_adjudicator(world, actor_id: str, action_text: str) -> AdjudicatorResponse:
            if actor_id == "encounter_1_enemy_0" and "attack roll" not in action_text.lower():
                return AdjudicatorResponse(
                    status="needs_clarification",
                    ruling="The goblin snarls and slashes at Aldric with its scimitar. Roll an attack to determine if the blade finds a gap in the dwarf's armor.",
                    destination=[
                        DestinationRoute(
                            actor=actor_id,
                            purpose="Provide the goblin's attack roll",
                            payload_hint="Return the requested attack roll result",
                        )
                    ],
                    reasoning="The attack declaration is valid but needs the roll outcome before it can resolve.",
                    requires_player_response=True,
                    follow_up_actor=actor_id,
                    suggested_alternatives=[],
                )
            return AdjudicatorResponse(
                status="approved",
                ruling="The goblin's scimitar slips past Aldric's guard and cuts him for 3 damage.",
                destination=[
                    DestinationRoute(
                        actor="extractor",
                        purpose="Apply the successful goblin hit",
                        payload_hint="Damage Aldric for 3 and log the strike",
                    )
                ],
                reasoning="The follow-up attack roll is sufficient to resolve the goblin's turn.",
                suggested_alternatives=[],
            )

        def goblin_hit_extractor(world, adjudication: AdjudicatorResponse) -> ExtractorResponse:
            if "3 damage" in adjudication.ruling:
                return ExtractorResponse(
                    root=[
                        ExtractorMutation(type="apply_damage", target_id="aldric_stonehammer", amount=3),
                        ExtractorMutation(
                            type="append_log_entry",
                            entry="[WORLD] The goblin's scimitar clips Aldric for 3 damage.",
                        ),
                    ]
                )
            return _log_only_extractor(world, adjudication)

        table = TableOrchestrator(
            world=world,
            turn_order=["aldric_stonehammer", "sylara_nightveil"],
            adjudicator_fn=clarifying_adjudicator,
            extractor_fn=goblin_hit_extractor,
            intent_fn=lambda current_world, actor_id: intent_agent.think_intent(
                TableOrchestrator.build_intent_payload(current_world, actor_id, loop_index=1)
            ),
            snapshot_dir=snapshot_dir,
            max_auto_npc_turns=8,
        )

        result = table.process_intent("I hold the line and watch the goblin's blade.")

    assert len(result.npc_turns) == 1
    assert result.npc_turns[0].status == "approved"
    assert "attack roll: 16" in result.npc_turns[0].generated_action.lower()
    assert table.world.party["aldric_stonehammer"].hp_current == 46
    assert table.world.awaiting_input_from == "sylara_nightveil"
    print("✓ NPC clarification follow-up auto-resolves through additional intent passes")


def test_orchestrator_routes_extractor_feedback_back_to_adjudicator():
    """If extractor cannot commit an approved NPC attack, the payload should be routed back through adjudication for correction."""
    assets_dir = Path(__file__).parent / "assets"
    with TemporaryDirectory() as temp_dir:
        snapshot_dir = Path(temp_dir) / "snapshots"
        loader = AdventureLoader(assets_dir, snapshot_dir=snapshot_dir)
        world = loader.load_adventure(
            adventure_file="adventure_sunken_grotto.json",
            pc_files=["pc_aldric_stonehammer.json", "pc_sylara_nightveil.json"],
            rules_file="homebrew_rules.json",
        )
        encounter_id = next(iter(world.encounters.keys()))
        world = world.set_active_encounter(encounter_id)
        world = world.update_encounter(
            encounter_id,
            replace(
                world.encounters[encounter_id],
                is_active=True,
                turn_order=[
                    EncounterTurnEntry(actor_id="aldric_stonehammer", initiative_roll=18),
                    EncounterTurnEntry(actor_id="encounter_1_enemy_0", initiative_roll=14),
                    EncounterTurnEntry(actor_id="sylara_nightveil", initiative_roll=11),
                ],
                current_turn_index=0,
            ),
        )

        intent_agent = SequencedIntentAgent(
            {
                "encounter_1_enemy_0": [
                    "I fire my shortbow at Aldric Stonehammer.",
                    "I make the requested attack roll: 16.",
                ]
            }
        )

        def incomplete_attack_adjudicator(world, actor_id: str, action_text: str) -> AdjudicatorResponse:
            if actor_id != "encounter_1_enemy_0":
                return AdjudicatorResponse(
                    status="approved",
                    ruling=f"{actor_id} keeps pressure on the goblins without committing a new mechanical effect.",
                    destination=[
                        DestinationRoute(
                            actor="extractor",
                            purpose="Record the committed action in the world log",
                            payload_hint="Append a log entry and finalize the turn",
                        )
                    ],
                    reasoning="The declared action is safe to resolve deterministically for test coverage.",
                    suggested_alternatives=[],
                )
            if "[EXTRACTOR_FEEDBACK]" in action_text:
                return AdjudicatorResponse(
                    status="needs_clarification",
                    ruling="The goblin's shot is declared but unresolved. Make the attack roll to determine whether it hits.",
                    destination=[
                        DestinationRoute(
                            actor=actor_id,
                            purpose="Provide the goblin's attack roll",
                            payload_hint="Return the requested attack roll result",
                        )
                    ],
                    reasoning="Extractor requested a concrete hit or miss outcome before state can be committed.",
                    requires_player_response=True,
                    follow_up_actor=actor_id,
                    suggested_alternatives=[],
                )
            if "attack roll" not in action_text.lower():
                return AdjudicatorResponse(
                    status="approved",
                    ruling="The goblin sneers and fires a crude, black-fletched arrow at Aldric.",
                    destination=[
                        DestinationRoute(
                            actor="extractor",
                            purpose="Resolve attack roll and apply damage if hit",
                            payload_hint="Process goblin shortbow attack against Aldric Stonehammer",
                        )
                    ],
                    reasoning="Valid ranged attack by active NPC against visible PC in same room.",
                    suggested_alternatives=[],
                )
            return AdjudicatorResponse(
                status="approved",
                ruling="The goblin's arrow slips past Aldric's shield and deals 4 piercing damage.",
                destination=[
                    DestinationRoute(
                        actor="extractor",
                        purpose="Apply the resolved shortbow hit",
                        payload_hint="Damage Aldric by 4 and log the attack",
                    )
                ],
                reasoning="The follow-up attack roll resolves the NPC attack into a canonical hit.",
                suggested_alternatives=[],
            )

        def npc_attack_extractor(world, adjudication: AdjudicatorResponse) -> ExtractorResponse:
            if "4 piercing damage" in adjudication.ruling:
                return ExtractorResponse(
                    root=[
                        ExtractorMutation(type="apply_damage", target_id="aldric_stonehammer", amount=4),
                        ExtractorMutation(
                            type="append_log_entry",
                            entry="[WORLD] The goblin's shortbow hits Aldric for 4 piercing damage.",
                        ),
                    ]
                )
            if "black-fletched arrow" in adjudication.ruling:
                return ExtractorResponse(
                    root=[
                        ExtractorMutation(
                            type="append_log_entry",
                            entry="[EXTRACTOR] Extraction failed: Approved ruling lacked a canonical attack outcome.",
                        )
                    ]
                )
            return ExtractorResponse(
                root=[
                    ExtractorMutation(
                        type="append_log_entry",
                        entry=f"[WORLD] {adjudication.ruling}",
                    )
                ]
            )

        table = TableOrchestrator(
            world=world,
            turn_order=["aldric_stonehammer", "sylara_nightveil"],
            adjudicator_fn=incomplete_attack_adjudicator,
            extractor_fn=npc_attack_extractor,
            intent_fn=lambda current_world, actor_id: intent_agent.think_intent(
                TableOrchestrator.build_intent_payload(current_world, actor_id, loop_index=1)
            ),
            snapshot_dir=snapshot_dir,
            max_auto_npc_turns=8,
        )

        result = table.process_intent("I raise my shield and wait for the goblin to loose its arrow.")

    assert len(result.npc_turns) == 1
    assert result.npc_turns[0].status == "approved"
    assert table.world.party["aldric_stonehammer"].hp_current == 48
    assert any("attack roll" in entry.lower() for entry in table.world.turn_log)
    assert not any("[EXTRACTOR] Extraction failed" in entry for entry in table.world.turn_log)
    print("✓ Extractor feedback is routed back through adjudication until the NPC attack is commit-ready")


def test_orchestrator_npc_follow_up_failsafe_stops_repeated_clarification_loop():
    """Repeated unresolved NPC clarification loops should stop at the follow-up failsafe instead of running forever."""
    assets_dir = Path(__file__).parent / "assets"
    with TemporaryDirectory() as temp_dir:
        snapshot_dir = Path(temp_dir) / "snapshots"
        loader = AdventureLoader(assets_dir, snapshot_dir=snapshot_dir)
        world = loader.load_adventure(
            adventure_file="adventure_sunken_grotto.json",
            pc_files=["pc_aldric_stonehammer.json", "pc_sylara_nightveil.json"],
            rules_file="homebrew_rules.json",
        )
        encounter_id = next(iter(world.encounters.keys()))
        world = world.set_active_encounter(encounter_id)
        world = world.update_encounter(
            encounter_id,
            replace(
                world.encounters[encounter_id],
                is_active=True,
                turn_order=[
                    EncounterTurnEntry(actor_id="aldric_stonehammer", initiative_roll=18),
                    EncounterTurnEntry(actor_id="encounter_1_enemy_0", initiative_roll=14),
                ],
                current_turn_index=0,
            ),
        )

        intent_agent = SequencedIntentAgent(
            {"encounter_1_enemy_0": ["I swing wildly at Aldric.", "I roll a 12 to attack.", "I roll a 12 to attack."]}
        )

        def endless_clarification_adjudicator(world, actor_id: str, action_text: str) -> AdjudicatorResponse:
            if actor_id == "encounter_1_enemy_0":
                return AdjudicatorResponse(
                    status="needs_clarification",
                    ruling="The goblin's attack still needs another resolving roll from the DM workflow.",
                    destination=[
                        DestinationRoute(
                            actor=actor_id,
                            purpose="Provide another follow-up roll",
                            payload_hint="Respond to the unresolved attack prompt",
                        )
                    ],
                    reasoning="This test intentionally keeps the goblin in an unresolved clarification loop.",
                    requires_player_response=True,
                    follow_up_actor=actor_id,
                    suggested_alternatives=[],
                )
            return _approved_adjudicator(world, actor_id, action_text)

        table = TableOrchestrator(
            world=world,
            turn_order=["aldric_stonehammer", "sylara_nightveil"],
            adjudicator_fn=endless_clarification_adjudicator,
            extractor_fn=_empty_extractor,
            intent_fn=lambda current_world, actor_id: intent_agent.think_intent(
                TableOrchestrator.build_intent_payload(current_world, actor_id, loop_index=1)
            ),
            snapshot_dir=snapshot_dir,
            max_auto_npc_turns=5,
        )

        result = table.process_intent("I ready myself for the goblin's next move.")

    assert len(result.npc_turns) == 1
    assert result.npc_turns[0].status == "needs_clarification"
    assert table.world.awaiting_input_from == "encounter_1_enemy_0"
    assert any("FAILSAFE" in entry for entry in table.world.turn_log)
    print("✓ NPC clarification failsafe stops repeated unresolved follow-up loops")


if __name__ == "__main__":
    test_orchestrator_game_start_history_label()
    test_orchestrator_pending_roll_keeps_same_actor()
    test_orchestrator_approved_damage_roll_reasoning_still_commits_extractor_mutations()
    test_orchestrator_approved_flow()
    test_orchestrator_rejected_flow_no_mutation()
    test_orchestrator_from_agents_llm_response_handling()
    test_orchestrator_empty_action_uses_intent_agent_and_resolves_active_npcs()
    test_orchestrator_encounter_turn_wraps_and_increments_round_count()
    test_orchestrator_npc_needs_clarification_auto_resolves_follow_up_roll()
    test_orchestrator_routes_extractor_feedback_back_to_adjudicator()
    test_orchestrator_npc_follow_up_failsafe_stops_repeated_clarification_loop()
    print("\n✅ All orchestrator tests passed!")
