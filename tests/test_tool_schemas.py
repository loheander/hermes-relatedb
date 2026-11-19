"""The relatedb_remember schema steers the model to slot-keyed facts (#51)."""

from __future__ import annotations

from relatedb_memory.provider import RelateDBMemoryProvider


def _remember_schema() -> dict:
    schemas = RelateDBMemoryProvider().get_tool_schemas()
    return next(s["function"] for s in schemas if s["function"]["name"] == "relatedb_remember")


def test_remember_description_says_when_to_prefer_it():
    description = _remember_schema()["description"]
    assert "built-in `memory` tool" in description
    assert "natural key" in description
    assert "reuse its slot" in description


def test_slot_description_gives_convention_and_examples():
    slot = _remember_schema()["parameters"]["properties"]["slot"]["description"]
    assert "lowercase" in slot
    assert "'/'-separated" in slot
    assert "'prefs/editor'" in slot
    assert "'project/<slug>/owner'" in slot


def test_remember_contract_unchanged():
    params = _remember_schema()["parameters"]
    assert params["required"] == ["text", "slot"]
    assert set(params["properties"]) == {"text", "slot", "about", "valid_from"}
