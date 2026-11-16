"""Acceptance scenarios for agent memory tools (#9).

The scenarios live in ``features/agent_tools.feature`` as Given/When/Then
text; this module binds each step to ``RelateDBMemoryProvider.get_tool_schemas``
and ``RelateDBMemoryProvider.handle_tool_call``.

The steps pin the contract #9 must implement::

    provider.get_tool_schemas() -> list[dict]
    provider.handle_tool_call(tool_name, arguments) -> str (JSON)
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from relatedb_memory.embedder import FakeEmbedder
from relatedb_memory.provider import RelateDBMemoryProvider

scenarios("features/agent_tools.feature")

EMBEDDING_DIM = 4


def call_tool(provider: RelateDBMemoryProvider, name: str, **args) -> dict:
    raw = provider.handle_tool_call(name, args)
    return json.loads(raw)


@pytest.fixture
def world(tmp_path):
    state = SimpleNamespace(
        home=tmp_path,
        provider=None,
        embedder=FakeEmbedder(dim=EMBEDDING_DIM),
        last_result=None,
        mutation_results=[],
    )
    yield state
    if state.provider is not None:
        try:
            state.provider.shutdown()
        except Exception:
            pass


# -- Given --------------------------------------------------------------------


@given("an initialized RelateDBMemoryProvider with agent tools enabled")
def provider_with_tools(world):
    provider = RelateDBMemoryProvider()
    provider.initialize("s-tools", hermes_home=str(world.home), embedder=world.embedder)
    schemas = provider.get_tool_schemas()
    names = {s["function"]["name"] for s in schemas}
    assert {
        "relatedb_remember",
        "relatedb_recall",
        "relatedb_forget",
        "relatedb_as_of",
        "relatedb_provenance",
        "relatedb_cypher",
    } <= names
    world.provider = provider


@given(parsers.parse('Grace was recorded on "{recorded_at}" as reviewer since "{valid_from}"'))
def grace_recorded(world, recorded_at, valid_from):
    world.provider.store.record_episode(
        episode_id="ep-grace",
        session="s1",
        kind="message",
        at=recorded_at,
        text="Grace reviews each relate release.",
        mentions=["grace", "relate"],
    )
    world.provider.store.record_fact(
        fact_id="f-grace",
        text="Grace reviews each relate release.",
        slot="relate/release-reviewer",
        valid_from=valid_from,
        recorded_at=recorded_at,
        episode_id="ep-grace",
        about=["grace", "relate"],
        embedding=world.embedder.embed_one("Grace reviews each relate release."),
    )


@given(parsers.parse('Ada was recorded on "{recorded_at}" as taking over on "{valid_from}"'))
def ada_recorded(world, recorded_at, valid_from):
    world.provider.store.record_episode(
        episode_id="ep-ada",
        session="s2",
        kind="tool_call",
        at=recorded_at,
        text="Ada took over relate release reviews.",
        mentions=["ada", "relate"],
    )
    world.provider.store.record_fact(
        fact_id="f-ada",
        text="Ada reviews each relate release.",
        slot="relate/release-reviewer",
        valid_from=valid_from,
        recorded_at=recorded_at,
        episode_id="ep-ada",
        about=["ada", "relate"],
        embedding=world.embedder.embed_one("Ada reviews each relate release."),
    )


# -- When ---------------------------------------------------------------------


@when(parsers.parse('the agent calls relatedb_remember for slot "{slot}" with "{text}"'))
def call_remember(world, slot, text):
    world.last_result = call_tool(world.provider, "relatedb_remember", slot=slot, text=text)


@when(parsers.parse('the agent calls relatedb_recall for "{query}"'))
def call_recall(world, query):
    world.last_result = call_tool(world.provider, "relatedb_recall", query=query)


@when(parsers.parse('the agent calls relatedb_forget for slot "{slot}"'))
def call_forget(world, slot):
    world.last_result = call_tool(world.provider, "relatedb_forget", slot=slot)


@when(parsers.parse('the agent calls relatedb_as_of for slot "{slot}" on "{on}"'))
def call_as_of(world, slot, on):
    world.last_result = call_tool(world.provider, "relatedb_as_of", slot=slot, on=on)


@when(parsers.parse('the agent calls relatedb_provenance for slot "{slot}"'))
def call_provenance(world, slot):
    world.last_result = call_tool(world.provider, "relatedb_provenance", slot=slot)


@when(parsers.parse('the agent calls relatedb_cypher with a read query "{query}"'))
def call_cypher_read(world, query):
    world.last_result = call_tool(world.provider, "relatedb_cypher", query=query)


@when("the agent calls relatedb_cypher with mutating queries CREATE, MERGE, SET, DELETE, REMOVE, and DROP")
def call_cypher_mutations(world):
    queries = [
        "CREATE (:Entity {key: 'evil'})",
        "MERGE (:Entity {key: 'evil'})",
        "MATCH (n) SET n.hacked = true",
        "MATCH (n) DELETE n",
        "MATCH (n) REMOVE n.key",
        "DROP INDEX fact_slot IF EXISTS",
    ]
    world.mutation_results = [
        call_tool(world.provider, "relatedb_cypher", query=q) for q in queries
    ]


# -- Then ---------------------------------------------------------------------


@then(parsers.parse('the recalled tool result contains "{expected}"'))
def recall_contains(world, expected):
    texts = [item["text"] for item in world.last_result["results"]]
    assert expected in texts


@then(parsers.parse('the recalled tool result contains "{expected}" and replaced "{old_text}"'))
def recall_contains_with_replaced(world, expected, old_text):
    matching = [item for item in world.last_result["results"] if item["text"] == expected]
    assert len(matching) == 1
    assert old_text in matching[0]["replaced"]


@then("the recalled tool result has zero active facts")
def recall_empty(world):
    assert world.last_result["results"] == []


@then('trueOn is ["Ada reviews each relate release."] and believedOn is ["Grace reviews each relate release."]')
def as_of_divergence(world):
    assert world.last_result["trueOn"] == ["Ada reviews each relate release."]
    assert world.last_result["believedOn"] == ["Grace reviews each relate release."]


@then("provenance includes both facts in lineage with their Episode kind, session, at, and text")
def provenance_lineage(world):
    lineage = world.last_result["lineage"]
    assert len(lineage) == 2
    for entry in lineage:
        ep = entry["episode"]
        assert {"kind", "session", "at", "text"} <= set(ep)


@then("the Cypher tool returns JSON rows")
def cypher_returns_rows(world):
    assert "rows" in world.last_result
    assert isinstance(world.last_result["rows"], list)


@then("every mutating Cypher query is rejected without modifying the store")
def mutating_cypher_rejected(world):
    assert len(world.mutation_results) == 6
    for res in world.mutation_results:
        assert "error" in res
    evil = world.provider.store.run("MATCH (e:Entity {key: 'evil'}) RETURN count(e) AS c")
    assert evil[0]["c"] == 0
