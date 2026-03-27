"""Tests for typed adjudicator/extractor response contracts."""

from backend.agents.contracts import (
    ContractParseError,
    parse_adjudicator_response,
    parse_extractor_response,
)


def test_adjudicator_contract_valid():
    """Adjudicator JSON with extractor route validates successfully."""
    raw = """
    {
      "status": "approved",
      "ruling": "Aldric surges forward and strikes the goblin captain.",
      "destination": [
        {
          "actor": "extractor",
          "purpose": "Map ruling to world mutations",
          "payload_hint": "Use world ids and emit mutation array"
        }
      ],
      "reasoning": "Movement and attack are legal from current room state.",
      "suggested_alternatives": []
    }
    """
    result = parse_adjudicator_response(raw)
    assert result.status == "approved"
    assert result.destination[0].actor == "extractor"
    print("✓ Adjudicator approved contract validated")


def test_adjudicator_contract_invalid_missing_alternatives():
    """Rejected adjudicator responses must include alternatives."""
    raw = """
    {
      "status": "rejected",
      "ruling": "You cannot reach that target this turn.",
      "destination": [
        {
          "actor": "aldric_stonehammer",
          "purpose": "Choose another action",
          "payload_hint": "Select a legal target"
        }
      ],
      "reasoning": "Target is out of movement range.",
      "suggested_alternatives": []
    }
    """
    try:
        parse_adjudicator_response(raw)
        raise AssertionError("Expected ContractParseError for missing alternatives")
    except ContractParseError:
        print("✓ Adjudicator rejection validation works")


def test_extractor_contract_valid():
    """Extractor mutation array validates and enforces required fields."""
    raw = """
    [
      {"type": "move_entity", "entity_id": "aldric_stonehammer", "to_room_id": "goblin_barracks"},
      {"type": "apply_damage", "target_id": "encounter_1_enemy_1", "amount": 9},
      {"type": "append_log_entry", "entry": "[WORLD] Aldric hits goblin for 9 damage."},
      {"type": "increment_turn"}
    ]
    """
    result = parse_extractor_response(raw)
    assert len(result.root) == 4
    assert result.root[0].type.value == "move_entity"
    print("✓ Extractor contract validated")


def test_extractor_contract_invalid_negative_damage():
    """Extractor mutation validation rejects invalid payload values."""
    raw = """
    [
      {"type": "apply_damage", "target_id": "encounter_1_enemy_1", "amount": -3}
    ]
    """
    try:
        parse_extractor_response(raw)
        raise AssertionError("Expected ContractParseError for negative damage")
    except ContractParseError:
        print("✓ Extractor payload validation works")


if __name__ == "__main__":
    test_adjudicator_contract_valid()
    test_adjudicator_contract_invalid_missing_alternatives()
    test_extractor_contract_valid()
    test_extractor_contract_invalid_negative_damage()
    print("\n✅ All contract tests passed!")
