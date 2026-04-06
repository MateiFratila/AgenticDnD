"""Tests for table orchestrator flow and transition logging."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.agents.contracts import (
    AdjudicatorResponse,
    DestinationRoute,
    ExtractorMutation,
    ExtractorResponse,
)
from backend.orchestrator import TableOrchestrator, TableStep
from backend.world import AdventureLoader


class FakeAdjudicatorAgent:
    """Fake LLM adjudicator wrapper used by orchestrator from_agents tests."""

    def __init__(self):
        self.last_payload = None

    def think_adjudication(self, user_input: str) -> AdjudicatorResponse:
        self.last_payload = json.loads(user_input)
        return _approved_adjudicator(None, "aldric_stonehammer", "")


class FakeExtractorAgent:
    """Fake LLM extractor wrapper used by orchestrator from_agents tests."""

    def __init__(self):
        self.last_payload = None

    def think_extraction(self, user_input: str) -> ExtractorResponse:
        self.last_payload = json.loads(user_input)
        return _approved_extractor(None, _approved_adjudicator(None, "", ""))


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
        suggested_alternatives=["Attack from current room", "Use Dash toward a valid corridor"],
    )


def _pending_roll_adjudicator(world, actor_id: str, action_text: str) -> AdjudicatorResponse:
    """Fake unresolved skill-check ruling that should keep the same actor awaiting input."""
    return AdjudicatorResponse(
        status="approved",
        ruling="Sylara slips toward the tunnel mouth. Roll Dexterity (Stealth) to determine whether you enter undetected.",
        destination=[
            DestinationRoute(
                actor="extractor",
                purpose="Attempt to map the movement",
                payload_hint="Move toward the next connected room if the action fully resolves",
            )
        ],
        reasoning="The declared stealth approach is legal but the outcome depends on a roll.",
        suggested_alternatives=[],
    )


def _empty_extractor(world, adjudication: AdjudicatorResponse) -> ExtractorResponse:
    """Fake extractor returning no canonical mutations for unresolved-roll scenarios."""
    return ExtractorResponse(root=[])


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
    assert adjudicator_agent.last_payload is not None
    assert extractor_agent.last_payload is not None
    assert adjudicator_agent.last_payload["action"] == "I rush the goblin and attack."
    assert adjudicator_agent.last_payload["actor_id"] == "aldric_stonehammer"
    assert adjudicator_agent.last_payload["world_state"]["scope"] == "adjudicator_view"
    assert adjudicator_agent.last_payload["world_state"]["actor"]["id"] == "aldric_stonehammer"
    assert "adjudication" in extractor_agent.last_payload
    assert extractor_agent.last_payload["adjudication"]["status"] == "approved"
    print("✓ Orchestrator from_agents LLM response handling passed")


if __name__ == "__main__":
    test_orchestrator_game_start_history_label()
    test_orchestrator_pending_roll_keeps_same_actor()
    test_orchestrator_approved_flow()
    test_orchestrator_rejected_flow_no_mutation()
    test_orchestrator_from_agents_llm_response_handling()
    print("\n✅ All orchestrator tests passed!")
