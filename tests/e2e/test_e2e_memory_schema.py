"""Executable memory graph schema contract (#41).

The schema is stated in ``features/memory_schema.feature``; this module binds
its steps to the real write paths (``record_episode``, ``record_fact``,
``retract_slot``, ``dedupe_facts`` and ``relatedb_remember``) and checks the
result with Cypher introspection. Every check is exhaustive: an unlisted label,
property or relationship type fails the suite.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from relatedb_memory.embedder import FakeEmbedder
from relatedb_memory.provider import RelateDBMemoryProvider
from relatedb_memory.schema import FACT_ORIGINS
from relatedb_memory.store import EPISODE_KINDS

scenarios("features/memory_schema.feature")

EMBEDDING_DIM = 16
T0 = "2026-03-01T10:00:00Z"


def csv(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


@pytest.fixture
def world(tmp_path):
    provider = RelateDBMemoryProvider()
    embedder = FakeEmbedder(dim=EMBEDDING_DIM)
    provider.initialize("s-schema", hermes_home=str(tmp_path), embedder=embedder)
    state = SimpleNamespace(provider=provider, store=provider.store, embedder=embedder, remembered=None)
    yield state
    provider.shutdown()


def write_fact(world, fact_id, slot, recorded_at, valid_from=None, text=None, episode_id="ep-1"):
    text = text or f"{fact_id} text"
    world.store.record_fact(
        fact_id=fact_id,
        text=text,
        slot=slot,
        valid_from=valid_from or recorded_at,
        recorded_at=recorded_at,
        episode_id=episode_id,
        about=["ada"],
        embedding=world.embedder.embed_one(text),
    )


def fact(world, fact_id) -> dict:
    rows = world.store.run("MATCH (f:Fact {id: $id}) RETURN properties(f) AS p", id=fact_id)
    assert len(rows) == 1, f"fact {fact_id!r} not found"
    return rows[0]["p"]


def prop_keys(world, pattern: str, var: str) -> list[str]:
    rows = world.store.run(f"MATCH {pattern} UNWIND keys({var}) AS k RETURN DISTINCT k")
    return sorted(row["k"] for row in rows)


# -- Given --------------------------------------------------------------------


@given("an open schema store")
def open_schema_store(world):
    world.store.record_episode(episode_id="ep-1", session="s1", kind="message", at=T0, text="Ada leads", mentions=["ada"])


@given("a store written through every write path")
def store_with_every_write_path(world):
    s = world.store
    s.record_episode(episode_id="ep-1", session="s1", kind="message", at=T0, text="Ada leads", mentions=["ada"])
    write_fact(world, "f1", "team/lead", T0)
    # correction: closes f1, adds f2, links SUPERSEDES
    write_fact(world, "f2", "team/lead", "2026-03-20T09:00:00Z", valid_from="2026-03-10T00:00:00Z")
    # retraction of a slot with no replacement
    write_fact(world, "f3", "team/office", T0)
    s.retract_slot(slot="team/office", valid_to="2026-04-01T00:00:00Z", closed_at="2026-04-02T00:00:00Z")
    # a fact with no slot, a near-duplicate of f4, to get DUPLICATE_OF
    write_fact(world, "f4", "team/mascot", T0, text="the mascot is a heron")
    write_fact(world, "f5", None, "2026-03-02T10:00:00Z", text="the mascot is a heron")
    assert s.dedupe_facts(0.9, detected_at="2026-03-03T00:00:00Z"), "expected a DUPLICATE_OF link"
    # relatedb_remember
    json.loads(
        world.provider.handle_tool_call("relatedb_remember", {"slot": "team/pet", "text": "a cat", "about": ["cat"]})
    )


# -- When ---------------------------------------------------------------------


@when(
    parsers.parse(
        'fact "{fact_id}" is recorded on "{recorded_at}" in slot "{slot}" valid from "{valid_from}"'
    )
)
def when_fact_recorded(world, fact_id, recorded_at, slot, valid_from):
    write_fact(world, fact_id, slot, recorded_at, valid_from=valid_from)


@when(parsers.parse('the slot "{slot}" is retracted with validTo "{valid_to}" and closedAt "{closed_at}"'))
def when_retracted(world, slot, valid_to, closed_at):
    assert world.store.retract_slot(slot=slot, valid_to=valid_to, closed_at=closed_at) == 1


@when(parsers.parse('the agent remembers "{text}" in slot "{slot}" about "{about}"'))
def when_remembered(world, text, slot, about):
    raw = world.provider.handle_tool_call("relatedb_remember", {"slot": slot, "text": text, "about": [about]})
    world.remembered = json.loads(raw)["fact_id"]


@given(parsers.parse('fact "{fact_id}" recorded on "{recorded_at}" in slot "{slot}"'))
def given_fact_recorded(world, fact_id, recorded_at, slot):
    write_fact(world, fact_id, slot, recorded_at)


# -- Then ---------------------------------------------------------------------


@then(parsers.parse('the node labels are exactly "{labels}"'))
def then_labels(world, labels):
    rows = world.store.run("MATCH (n) UNWIND labels(n) AS l RETURN DISTINCT l")
    assert sorted(r["l"] for r in rows) == sorted(csv(labels))


@then(parsers.parse('the "{label}" nodes have exactly the properties "{keys}"'))
def then_node_properties(world, label, keys):
    assert prop_keys(world, f"(n:{label})", "n") == sorted(csv(keys))


@then(parsers.parse('the relationships are exactly "{expected}"'))
def then_relationships(world, expected):
    rows = world.store.run(
        "MATCH (a)-[r]->(b) RETURN DISTINCT type(r) AS t, labels(a) AS a, labels(b) AS b"
    )
    actual = sorted(f"{r['t']}:{'+'.join(r['a'])}>{'+'.join(r['b'])}" for r in rows)
    assert actual == sorted(csv(expected))


@then(parsers.parse('the "{rel}" relationships have exactly the properties "{keys}"'))
def then_rel_properties(world, rel, keys):
    assert prop_keys(world, f"()-[r:{rel}]->()", "r") == sorted(csv(keys))


@then(parsers.parse('the "{rel}" relationships have no properties'))
def then_rel_no_properties(world, rel):
    assert prop_keys(world, f"()-[r:{rel}]->()", "r") == []


@then(parsers.parse('the allowed episode kinds are exactly "{kinds}"'))
def then_episode_kinds(world, kinds):
    assert sorted(EPISODE_KINDS) == sorted(csv(kinds))
    for i, kind in enumerate(sorted(EPISODE_KINDS)):
        world.store.record_episode(episode_id=f"ep-kind-{i}", session="s1", kind=kind, at=T0, text="x")


@then(parsers.parse('the allowed fact origins are exactly "{origins}"'))
def then_fact_origins(world, origins):
    assert sorted(FACT_ORIGINS) == sorted(csv(origins))
    for i, origin in enumerate(sorted(FACT_ORIGINS)):
        world.store.record_fact(
            fact_id=f"f-origin-{i}", text="x", slot=None, valid_from=T0, recorded_at=T0,
            episode_id="ep-1", origin=origin,
        )
        assert fact(world, f"f-origin-{i}")["origin"] == origin


@then(parsers.parse('recording an episode of kind "{kind}" is rejected'))
def then_bad_kind(world, kind):
    with pytest.raises(ValueError):
        world.store.record_episode(episode_id="ep-bad", session="s1", kind=kind, at=T0, text="x")
    assert world.store.run("MATCH (ep:Episode {id: 'ep-bad'}) RETURN ep") == []


@then(parsers.parse('recording a fact with origin "{origin}" is rejected'))
def then_bad_origin(world, origin):
    with pytest.raises(ValueError):
        world.store.record_fact(
            fact_id="f-bad", text="x", slot=None, valid_from=T0, recorded_at=T0,
            episode_id="ep-1", origin=origin,
        )
    assert world.store.run("MATCH (f:Fact {id: 'f-bad'}) RETURN f") == []


@then(parsers.parse('fact "{fact_id}" is closed with validTo "{valid_to}" and closedAt "{closed_at}"'))
def then_closed(world, fact_id, valid_to, closed_at):
    f = fact(world, fact_id)
    assert f["validTo"] == valid_to
    assert f["closedAt"] == closed_at


@then(parsers.parse('fact "{fact_id}" is open'))
def then_open(world, fact_id):
    f = fact(world, fact_id)
    assert f.get("closedAt") is None
    assert f.get("validTo") is None


@then(parsers.parse('fact "{new}" supersedes fact "{old}"'))
def then_supersedes(world, new, old):
    rows = world.store.run(
        "MATCH (n:Fact {id: $new})-[:SUPERSEDES]->(o:Fact {id: $old}) RETURN count(*) AS c", new=new, old=old
    )
    assert rows[0]["c"] == 1


@then(parsers.parse("the graph holds {count:d} facts"))
def then_fact_count(world, count):
    assert world.store.run("MATCH (f:Fact) RETURN count(f) AS c")[0]["c"] == count


def remembered_row(world, query: str, **params):
    return world.store.run(query, id=world.remembered, **params)


@then(parsers.parse('the remembered fact is open with origin "{origin}"'))
def then_remembered_open(world, origin):
    f = fact(world, world.remembered)
    assert f["origin"] == origin
    assert f.get("closedAt") is None


@then(parsers.parse('the remembered fact comes from a "{kind}" episode'))
def then_remembered_from(world, kind):
    rows = remembered_row(world, "MATCH (f:Fact {id: $id})-[:FROM]->(ep:Episode) RETURN ep.kind AS kind")
    assert [r["kind"] for r in rows] == [kind]


@then(parsers.parse('the remembered fact is about "{key}"'))
def then_remembered_about(world, key):
    rows = remembered_row(world, "MATCH (f:Fact {id: $id})-[:ABOUT]->(e:Entity) RETURN e.key AS key")
    assert [r["key"] for r in rows] == [key]
