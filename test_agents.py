"""Test agent initialization and prompt loading."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from backend.agents import BaseAgent
from backend.agents.contracts import AdjudicatorResponse, DestinationRoute
from backend.llm import PromptLoader
from backend.orchestrator import TableOrchestrator
from backend.world import AdventureLoader


def test_prompt_loader():
    """Test that prompts can be loaded correctly."""
    loader = PromptLoader()

    # Load adjudicator system prompt
    adjudicator_prompt = loader.load_prompt("adjudicator", "system")
    assert len(adjudicator_prompt) > 0, "Adjudicator prompt is empty"
    assert "ruling" in adjudicator_prompt.lower(), "Adjudicator prompt missing expected content"
    assert "destination" in adjudicator_prompt.lower(), "Adjudicator prompt missing routing contract"
    assert "game_start" in adjudicator_prompt, "Adjudicator prompt should preserve the game_start status"
    assert "2-6 sentences" in adjudicator_prompt, "Adjudicator prompt should enforce concise rulings"
    assert "120 words" in adjudicator_prompt, "Adjudicator prompt should cap narrative length"
    print(f"✓ Adjudicator system prompt loaded: {len(adjudicator_prompt)} chars")

    # Load extractor system prompt
    extractor_prompt = loader.load_prompt("extractor", "system")
    assert len(extractor_prompt) > 0, "Extractor prompt is empty"
    assert "mutation" in extractor_prompt.lower(), "Extractor prompt missing expected content"
    assert "item_add" in extractor_prompt, "Extractor prompt should document inventory mutations"
    assert "looted" in extractor_prompt.lower(), "Extractor prompt should explain how to mark looted corpses"
    print(f"✓ Extractor system prompt loaded: {len(extractor_prompt)} chars")

    # Load intent system prompt
    intent_prompt = loader.load_prompt("intent", "system")
    assert len(intent_prompt) > 0, "Intent prompt is empty"
    assert "intent" in intent_prompt.lower(), "Intent prompt missing expected content"
    print(f"✓ Intent system prompt loaded: {len(intent_prompt)} chars")


def test_base_agent_initialization():
    """Test that BaseAgent can be initialized and configured."""
    # Create an adjudicator agent instance
    adjudicator = BaseAgent(
        agent_type="adjudicator",
        agent_name="DM Adjudicator",
        temperature=0.5,
        max_tokens=2000,
    )

    assert adjudicator.agent_type == "adjudicator"
    assert adjudicator.agent_name == "DM Adjudicator"
    assert adjudicator.temperature == 0.5
    assert adjudicator.max_tokens == 2000
    print("✓ Adjudicator agent initialized")

    # Verify prompt loading works
    system_prompt = adjudicator._load_system_prompt()
    assert len(system_prompt) > 0, "Loaded system prompt is empty"
    print(f"✓ Agent can load system prompt: {len(system_prompt)} chars")
    
    # Verify LLM client was initialized (but may not be usable without API key)
    assert adjudicator.llm_client is not None, "LLM client not initialized"
    print(f"✓ LLM client initialized (API key set: {adjudicator.llm_client.api_key_set})")


def test_base_agent_extractor():
    """Test extractor agent initialization."""
    extractor = BaseAgent(
        agent_type="extractor",
        agent_name="Mutation Extractor",
        temperature=0.3,
        max_tokens=1500,
    )

    assert extractor.agent_type == "extractor"
    assert extractor.agent_name == "Mutation Extractor"
    print("✓ Extractor agent initialized")

    # Verify prompt loading works
    system_prompt = extractor._load_system_prompt()
    assert "mutation" in system_prompt.lower()
    print(f"✓ Extractor agent can load system prompt")


def test_base_agent_intent():
    """Test intent agent initialization."""
    intent_agent = BaseAgent(
        agent_type="intent",
        agent_name="Intent Generator",
        temperature=0.4,
        max_tokens=1200,
    )

    assert intent_agent.agent_type == "intent"
    assert intent_agent.agent_name == "Intent Generator"
    system_prompt = intent_agent._load_system_prompt()
    assert "immediate next step" in system_prompt.lower()
    assert "roll" in system_prompt.lower()
    print("✓ Intent agent initialized")


def test_base_agent_fallback_when_llm_content_is_none(monkeypatch):
    """Ensure deterministic fallback is used when provider returns None content."""
    adjudicator = BaseAgent(agent_type="adjudicator", agent_name="Adjudicator")

    fake_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content=None),
            )
        ],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )

    monkeypatch.setattr(adjudicator.llm_client, "chat_completion", lambda **_: fake_response)

    adjudication = adjudicator.think_adjudication(user_input="Adventure Start")
    assert adjudication.status == "approved"
    assert any(route.actor == "extractor" for route in adjudication.destination)

    extractor = BaseAgent(agent_type="extractor", agent_name="Extractor")
    monkeypatch.setattr(extractor.llm_client, "chat_completion", lambda **_: fake_response)

    extraction = extractor.think_extraction(user_input="Extract mutations")
    assert len(extraction.root) >= 1


def test_trace_file_path_uses_session_metadata_from_payloads():
    """Trace filenames should use real session/loop values for both payload shapes."""
    assets_dir = Path(__file__).parent / "assets"
    loop_index = 7
    with TemporaryDirectory() as temp_dir:
        snapshot_dir = Path(temp_dir) / "snapshots"
        loader = AdventureLoader(assets_dir, snapshot_dir=snapshot_dir)
        world = loader.load_adventure(
            adventure_file="adventure_sunken_grotto.json",
            pc_files=["pc_aldric_stonehammer.json", "pc_sylara_nightveil.json"],
            rules_file="homebrew_rules.json",
        )

        adjudicator_payload = TableOrchestrator.build_adjudicator_payload(
            world,
            "aldric_stonehammer",
            "Adventure Start",
            loop_index=loop_index,
        )
        adjudicator_agent = BaseAgent(agent_type="adjudicator", agent_name="Adjudicator")
        adjudicator_path = adjudicator_agent._build_trace_file_path("system", adjudicator_payload)
        assert adjudicator_path.name == f"s_{world.game_session_id}_l_{loop_index:04d}_a_adjudicator.json"

        adjudication = AdjudicatorResponse(
            status="approved",
            ruling="Aldric steps forward into the cave.",
            destination=[
                DestinationRoute(
                    actor="extractor",
                    purpose="Apply resulting changes",
                    payload_hint="Use ruling and current world state",
                )
            ],
            reasoning="Legal movement.",
            suggested_alternatives=[],
        )
        extractor_payload = TableOrchestrator.build_extractor_payload(
            world,
            adjudication,
            loop_index=loop_index,
        )
        extractor_json = json.loads(extractor_payload)
        assert extractor_json["world_state"]["game_session_id"] == world.game_session_id
        assert extractor_json["world_state"]["session"]["loop_index"] == loop_index

        extractor_agent = BaseAgent(agent_type="extractor", agent_name="Extractor")
        extractor_path = extractor_agent._build_trace_file_path("system", extractor_payload)
        assert extractor_path.name == f"s_{world.game_session_id}_l_{loop_index:04d}_a_extractor.json"


if __name__ == "__main__":
    test_prompt_loader()
    test_base_agent_initialization()
    test_base_agent_extractor()
    test_base_agent_intent()
    test_trace_file_path_uses_session_metadata_from_payloads()
    print("\n✅ All agent tests passed!")
