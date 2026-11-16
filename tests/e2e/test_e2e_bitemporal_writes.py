"""Acceptance scenarios for bi-temporal write path, slot supersession, and provenance (#6).

The scenarios live in ``features/bitemporal_writes.feature`` as Given/When/Then
text; this module binds each step to ``RelateStore``.

The steps pin the contract #6 must implement::

    store.record_episode(episode_id, session, kind, at, text, mentions=...)
    store.record_fact(fact_id, text, slot, valid_from, recorded_at, episode_id, about=..., embedding=...)
    store.retract_slot(slot, valid_to, closed_at)
    store.active_slots() -> list[str]
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from relatedb_memory import config as cfg
from relatedb_memory.embedder import FakeEmbedder
from relatedb_memory.store import RelateStore

scenarios("features/bitemporal_writes.feature")

EMBEDDING_DIM = 16


def assert_slot_uniqueness(store: RelateStore) -> None:
    """Invariant: at most one open fact (closedAt IS NULL) per slot."""
    dups = store.run(
        "MATCH (f:Fact) WHERE f.closedAt IS NULL AND f.slot IS NOT NULL "
        "WITH f.slot AS slot, count(*) AS c WHERE c > 1 RETURN slot, c"
    )
    assert dups == [], f"Slot uniqueness violated: {dups}"


@pytest.fixture
def world(tmp_path):
    config = cfg.resolve_config(tmp_path, env_get={}.get)
    store = RelateStore.open(config, embedding_dim=EMBEDDING_DIM)
    embedder = FakeEmbedder(dim=EMBEDDING_DIM)
    state = SimpleNamespace(
        store=store,
        embedder=embedder,
        counts_before=None,
        last_payload=None,
    )
    yield state
    try:
        assert_slot_uniqueness(store)
    finally:
        store.close()


# -- Given --------------------------------------------------------------------


@given("an open bi-temporal store")
def an_open_bitemporal_store(world):
    assert not world.store.closed


@given(
    parsers.parse(
        'session "{session}" recorded fact "{fact_id}" in slot "{slot}" on "{ts}"'
    )
)
def session_recorded_fact(world, session, fact_id, slot, ts):
    ep_id = f"ep-{session}"
    payload = {
        "episode_id": ep_id,
        "session": session,
        "kind": "message",
        "at": ts,
        "text": "Grace reviews each relate release",
        "mentions": ["grace", "relate"],
        "fact_id": fact_id,
        "fact_text": "Grace reviews each relate release",
        "slot": slot,
        "valid_from": ts,
        "recorded_at": ts,
        "about": ["grace", "relate"],
        "embedding": world.embedder.embed_one("Grace reviews each relate release"),
    }
    world.last_payload = payload
    world.store.record_episode(
        episode_id=payload["episode_id"],
        session=payload["session"],
        kind=payload["kind"],
        at=payload["at"],
        text=payload["text"],
        mentions=payload["mentions"],
    )
    world.store.record_fact(
        fact_id=payload["fact_id"],
        text=payload["fact_text"],
        slot=payload["slot"],
        valid_from=payload["valid_from"],
        recorded_at=payload["recorded_at"],
        episode_id=payload["episode_id"],
        about=payload["about"],
        embedding=payload["embedding"],
    )


# -- When ---------------------------------------------------------------------


@when(
    parsers.parse(
        'session "{session}" records a "{kind}" episode "{ep_id}" mentioning "{e1}" and "{e2}"'
    )
)
def record_episode_step(world, session, kind, ep_id, e1, e2):
    world.store.record_episode(
        episode_id=ep_id,
        session=session,
        kind=kind,
        at="2026-03-01T10:00:00Z",
        text=f"{e1} works on {e2}",
        mentions=[e1, e2],
    )


@when(
    parsers.parse(
        'fact "{fact_id}" is recorded in slot "{slot}" from "{ep_id}" about "{e1}" and "{e2}"'
    )
)
def record_fact_step(world, fact_id, slot, ep_id, e1, e2):
    text = f"{e1} reviews each {e2} release"
    world.store.record_fact(
        fact_id=fact_id,
        text=text,
        slot=slot,
        valid_from="2026-03-01T10:00:00Z",
        recorded_at="2026-03-01T10:00:00Z",
        episode_id=ep_id,
        about=[e1, e2],
        embedding=world.embedder.embed_one(text),
    )


@when(
    parsers.parse(
        'session "{session}" on "{recorded_at}" records a "{kind}" episode "{ep_id}" '
        'with fact "{fact_id}" in slot "{slot}" valid from "{valid_from}"'
    )
)
def record_correction_step(world, session, recorded_at, kind, ep_id, fact_id, slot, valid_from):
    text = "Ada took over relate release reviews"
    world.store.record_episode(
        episode_id=ep_id,
        session=session,
        kind=kind,
        at=recorded_at,
        text=text,
        mentions=["ada", "relate"],
    )
    world.store.record_fact(
        fact_id=fact_id,
        text=text,
        slot=slot,
        valid_from=valid_from,
        recorded_at=recorded_at,
        episode_id=ep_id,
        about=["ada", "relate"],
        embedding=world.embedder.embed_one(text),
    )


@when(parsers.parse('the exact same episode and fact payload for "{session}" is replayed'))
def replay_payload_step(world, session):
    nodes_before = world.store.run("MATCH (n) RETURN count(n) AS c")[0]["c"]
    rels_before = world.store.run("MATCH ()-[r]->() RETURN count(r) AS c")[0]["c"]
    world.counts_before = (nodes_before, rels_before)

    p = world.last_payload
    assert p["session"] == session
    world.store.record_episode(
        episode_id=p["episode_id"],
        session=p["session"],
        kind=p["kind"],
        at=p["at"],
        text=p["text"],
        mentions=p["mentions"],
    )
    world.store.record_fact(
        fact_id=p["fact_id"],
        text=p["fact_text"],
        slot=p["slot"],
        valid_from=p["valid_from"],
        recorded_at=p["recorded_at"],
        episode_id=p["episode_id"],
        about=p["about"],
        embedding=p["embedding"],
    )


@when(parsers.parse('slot "{slot}" is retracted at "{ts}"'))
def retract_slot_step(world, slot, ts):
    world.store.retract_slot(slot=slot, valid_to=ts, closed_at=ts)


@when(
    parsers.parse(
        'episode "{ep_id}" records fact "{fact_id}" about "{k1}", "{k2}", and "{k3}"'
    )
)
def record_zettel_fact(world, ep_id, fact_id, k1, k2, k3):
    text = f"Zettelkasten link {fact_id}"
    world.store.record_episode(
        episode_id=ep_id,
        session="s-zettel",
        kind="memory_write",
        at="2026-03-05T12:00:00Z",
        text=text,
        mentions=[k1, k2, k3],
    )
    world.store.record_fact(
        fact_id=fact_id,
        text=text,
        slot=f"zettel/{fact_id}",
        valid_from="2026-03-05T12:00:00Z",
        recorded_at="2026-03-05T12:00:00Z",
        episode_id=ep_id,
        about=[k1, k2, k3],
        embedding=world.embedder.embed_one(text),
    )


# -- Then ---------------------------------------------------------------------


@then(parsers.parse('the graph holds the provenance chain from "{fact_id}" to "{ep_id}" and its entities'))
def provenance_chain_exists(world, fact_id, ep_id):
    rows = world.store.run(
        "MATCH (f:Fact {id: $fid})-[:FROM]->(ep:Episode {id: $eid})-[:MENTIONS]->(m:Entity), "
        "(f)-[:ABOUT]->(a:Entity) "
        "RETURN count(DISTINCT m) AS m_cnt, count(DISTINCT a) AS a_cnt",
        fid=fact_id,
        eid=ep_id,
    )
    assert rows[0]["m_cnt"] == 2
    assert rows[0]["a_cnt"] == 2


@then(parsers.parse('"{slot}" is in active slots'))
def slot_in_active_slots(world, slot):
    assert slot in world.store.active_slots()


@then(parsers.parse('"{slot}" is not in active slots'))
def slot_not_in_active_slots(world, slot):
    assert slot not in world.store.active_slots()


@then(parsers.parse('fact "{fact_id}" is still present with validTo "{valid_to}" and closedAt "{closed_at}"'))
def fact_closed_with_timestamps(world, fact_id, valid_to, closed_at):
    rows = world.store.run(
        "MATCH (f:Fact {id: $fid}) RETURN f.validTo AS vt, f.closedAt AS ca",
        fid=fact_id,
    )
    assert len(rows) == 1
    assert rows[0]["vt"] == valid_to
    assert rows[0]["ca"] == closed_at


@then(parsers.parse('fact "{new_id}" supersedes fact "{old_id}"'))
def fact_supersedes(world, new_id, old_id):
    rows = world.store.run(
        "MATCH (:Fact {id: $nid})-[r:SUPERSEDES]->(:Fact {id: $oid}) RETURN count(r) AS c",
        nid=new_id,
        oid=old_id,
    )
    assert rows[0]["c"] == 1


@then("the node and relationship counts are unchanged")
def counts_unchanged(world):
    nodes_after = world.store.run("MATCH (n) RETURN count(n) AS c")[0]["c"]
    rels_after = world.store.run("MATCH ()-[r]->() RETURN count(r) AS c")[0]["c"]
    assert (nodes_after, rels_after) == world.counts_before


@then(parsers.parse('fact "{fact_id}" is closed with validTo "{valid_to}" and closedAt "{closed_at}"'))
def fact_retracted(world, fact_id, valid_to, closed_at):
    fact_closed_with_timestamps(world, fact_id, valid_to, closed_at)


@then("each shared entity key has exactly one Entity node with both facts attached")
def shared_entities_converge(world):
    for key in ("note_id:202611142237", "citation_key:ada2026", "project_slug:hermes-relatedb"):
        nodes = world.store.run("MATCH (e:Entity {key: $k}) RETURN count(e) AS c", k=key)
        assert nodes[0]["c"] == 1
        facts = world.store.run(
            "MATCH (f:Fact)-[:ABOUT]->(:Entity {key: $k}) RETURN f.id AS id",
            k=key,
        )
        assert {row["id"] for row in facts} == {"fz1", "fz2"}


@then("the slot-uniqueness invariant holds")
def slot_uniqueness_holds(world):
    assert_slot_uniqueness(world.store)
