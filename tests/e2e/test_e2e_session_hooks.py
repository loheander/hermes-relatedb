"""Acceptance scenarios for turn sync, memory-write mirroring, and pre-compression hooks (#8).

The scenarios live in ``features/session_hooks.feature`` as Given/When/Then
text; this module binds each step to ``RelateDBMemoryProvider``.

The steps pin the contract #8 must implement::

    provider.sync_turn(user_message, assistant_response, *, agent_context="primary", ...)
    provider.on_memory_write(action, content, *, target=..., metadata=...)
    provider.on_pre_compress(messages)
    provider.on_session_switch(new_session_id, *, reset=False)
    provider.on_delegation(task, result, *, child_session_id=None)
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from relatedb_memory.embedder import FakeEmbedder
from relatedb_memory.provider import RelateDBMemoryProvider

scenarios("features/session_hooks.feature")

EMBEDDING_DIM = 4


@pytest.fixture
def world(tmp_path):
    state = SimpleNamespace(
        home=tmp_path,
        provider=None,
        embedder=FakeEmbedder(dim=EMBEDDING_DIM),
    )
    yield state
    if state.provider is not None:
        try:
            state.provider.shutdown()
        except Exception:
            pass


# -- Given --------------------------------------------------------------------


@given(parsers.parse('an initialized RelateDBMemoryProvider for session "{session_id}"'))
def initialized_provider_for_session(world, session_id):
    provider = RelateDBMemoryProvider()
    provider.initialize(session_id, hermes_home=str(world.home), embedder=world.embedder)
    world.provider = provider


# -- When ---------------------------------------------------------------------


@when(parsers.parse('a primary turn completes with user "{user_msg}" and assistant "{assistant_msg}"'))
def primary_turn_completes(world, user_msg, assistant_msg):
    world.provider.sync_turn(user_msg, assistant_msg, agent_context="primary")
    world.provider.flush_sync(timeout=5.0)


@when('sync_turn runs with agent_context "subagent", "cron", and "flush"')
def non_primary_sync_turns(world):
    for ctx in ("subagent", "cron", "flush"):
        world.provider.sync_turn("Remember this", "Ok", agent_context=ctx)
    world.provider.flush_sync(timeout=5.0)


@when(parsers.parse('on_memory_write "add" records "{content}" in target "{target}"'))
def memory_write_add(world, content, target):
    world.provider.on_memory_write("add", content, target=target)


@when(parsers.parse('on_memory_write "replace" updates "{target}" to "{content}"'))
def memory_write_replace(world, target, content):
    world.provider.on_memory_write(
        "replace",
        content,
        target=target,
        metadata={"previous_content": "User prefers vim"},
    )


@when(parsers.parse('on_memory_write "remove" closes "{target}"'))
def memory_write_remove(world, target):
    world.provider.on_memory_write("remove", "", target=target)


@when("on_pre_compress runs on messages about to be truncated")
def pre_compress_runs(world):
    messages = [
        {"role": "user", "content": "Always run make test before pushing"},
        {"role": "assistant", "content": "Understood, I will run make test."},
    ]
    world.provider.on_pre_compress(messages)


@when(parsers.parse('on_session_switch switches to "{new_session}" with reset=True'))
def session_switch_runs(world, new_session):
    world.provider.on_session_switch(new_session, reset=True)


@when(
    parsers.parse(
        'on_delegation runs for task "{task}" with result "{result}" and child_session_id "{child_id}"'
    )
)
def delegation_runs(world, task, result, child_id):
    world.provider.on_delegation(task, result, child_session_id=child_id)


# -- Then ---------------------------------------------------------------------


@then(parsers.parse('an Episode and active Fact are persisted for session "{session_id}"'))
def episode_and_fact_persisted(world, session_id):
    eps = world.provider.store.run(
        "MATCH (ep:Episode {session: $s}) RETURN ep.id AS id", s=session_id
    )
    facts = world.provider.store.run(
        "MATCH (f:Fact)-[:FROM]->(ep:Episode {session: $s}) "
        "WHERE f.closedAt IS NULL RETURN f.id AS id",
        s=session_id,
    )
    assert len(eps) >= 1
    assert len(facts) >= 1


@then("zero Episode or Fact nodes are written")
def zero_nodes_written(world):
    eps = world.provider.store.run("MATCH (ep:Episode) RETURN count(ep) AS c")[0]["c"]
    facts = world.provider.store.run("MATCH (f:Fact) RETURN count(f) AS c")[0]["c"]
    assert eps == 0
    assert facts == 0


@then(parsers.parse('the active fact for "{target}" is "{expected}" and the old fact is closed'))
def active_fact_updated_and_old_closed(world, target, expected):
    open_facts = world.provider.store.run(
        "MATCH (f:Fact {slot: $slot}) WHERE f.closedAt IS NULL RETURN f.text AS text",
        slot=target,
    )
    closed_facts = world.provider.store.run(
        "MATCH (f:Fact {slot: $slot}) WHERE f.closedAt IS NOT NULL RETURN f.text AS text",
        slot=target,
    )
    assert [r["text"] for r in open_facts] == [expected]
    assert len(closed_facts) == 1


@then(parsers.parse('"{target}" has zero active facts'))
def target_has_zero_active_facts(world, target):
    open_facts = world.provider.store.run(
        "MATCH (f:Fact {slot: $slot}) WHERE f.closedAt IS NULL RETURN f.id AS id",
        slot=target,
    )
    assert open_facts == []


@then(parsers.parse('a "{kind}" episode is recorded for "{session_id}"'))
@then(parsers.parse('a "{kind}" episode is recorded for session "{session_id}"'))
def kind_episode_recorded(world, kind, session_id):
    eps = world.provider.store.run(
        "MATCH (ep:Episode {session: $s, kind: $k}) RETURN ep.id AS id",
        s=session_id,
        k=kind,
    )
    assert len(eps) >= 1


@then(parsers.parse('the new episode is linked to session "{session_id}"'))
def new_episode_linked_to_session(world, session_id):
    eps = world.provider.store.run(
        "MATCH (ep:Episode {session: $s}) RETURN ep.id AS id", s=session_id
    )
    assert len(eps) >= 1
