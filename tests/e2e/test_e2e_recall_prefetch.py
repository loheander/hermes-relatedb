"""Acceptance scenarios for pre-filtered vector recall, prefetch lifecycle, and RecallStatus (#7).

The scenarios live in ``features/recall_prefetch.feature`` as Given/When/Then
text; this module binds each step to ``RelateStore`` and ``RelateDBMemoryProvider``.

The steps pin the contract #7 must implement::

    store.vector_recall(query_vec, k=...) -> list[dict]
    provider.queue_prefetch(query, ...)
    provider.prefetch(query, ...) -> str
    provider.recall_status() -> RecallStatus | None
    provider.system_prompt_block() -> str
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from relatedb_memory import config as cfg
from relatedb_memory.embedder import FakeEmbedder
from relatedb_memory.provider import RelateDBMemoryProvider
from relatedb_memory.store import RelateStore

scenarios("features/recall_prefetch.feature")

EMBEDDING_DIM = 4


@pytest.fixture
def world(tmp_path):
    state = SimpleNamespace(
        home=tmp_path,
        store=None,
        provider=None,
        embedder=FakeEmbedder(dim=EMBEDDING_DIM),
        hits=None,
        prefetched="",
        trivial_results=[],
        prompt_before=None,
        prompt_after=None,
    )
    yield state
    if state.provider is not None:
        try:
            state.provider.shutdown()
        except Exception:
            pass
    if state.store is not None:
        try:
            state.store.close()
        except Exception:
            pass


# -- Given --------------------------------------------------------------------


@given("an open store with a superseded fact closer to the query than the current fact")
def store_with_superseded_closer_fact(world):
    config = cfg.resolve_config(world.home, env_get={}.get)
    store = RelateStore.open(config, embedding_dim=EMBEDDING_DIM)
    world.store = store

    store.record_episode(
        episode_id="ep-1",
        session="s1",
        kind="message",
        at="2026-03-01T10:00:00Z",
        text="Grace reviews each relate release",
        mentions=["grace", "relate"],
    )
    # f1 is aligned with query [1, 0, 0, 0]
    store.record_fact(
        fact_id="f1",
        text="Grace reviews each relate release",
        slot="relate/release-reviewer",
        valid_from="2026-03-01T10:00:00Z",
        recorded_at="2026-03-01T10:00:00Z",
        episode_id="ep-1",
        about=["grace", "relate"],
        embedding=[1.0, 0.0, 0.0, 0.0],
    )

    store.record_episode(
        episode_id="ep-2",
        session="s2",
        kind="tool_call",
        at="2026-03-20T09:00:00Z",
        text="Ada took over relate release reviews",
        mentions=["ada", "relate"],
    )
    # f2 supersedes f1, further from query [1, 0, 0, 0]
    store.record_fact(
        fact_id="f2",
        text="Ada reviews each relate release",
        slot="relate/release-reviewer",
        valid_from="2026-03-10T00:00:00Z",
        recorded_at="2026-03-20T09:00:00Z",
        episode_id="ep-2",
        about=["ada", "relate"],
        embedding=[0.6, 0.8, 0.0, 0.0],
    )


@given("an initialized RelateDBMemoryProvider with a stored fact about release reviews")
def initialized_provider_with_fact(world):
    provider = RelateDBMemoryProvider()
    provider.initialize("s-e2e", hermes_home=str(world.home), embedder=world.embedder)
    world.provider = provider
    provider.store.record_episode(
        episode_id="ep-1",
        session="s-e2e",
        kind="message",
        at="2026-03-01T10:00:00Z",
        text="Ada reviews each relate release",
        mentions=["ada", "relate"],
    )
    provider.store.record_fact(
        fact_id="f1",
        text="Ada reviews each relate release",
        slot="relate/release-reviewer",
        valid_from="2026-03-01T10:00:00Z",
        recorded_at="2026-03-01T10:00:00Z",
        episode_id="ep-1",
        about=["ada", "relate"],
        embedding=world.embedder.embed_one("Who reviews relate releases?"),
    )


@given("an initialized RelateDBMemoryProvider")
def initialized_provider(world):
    provider = RelateDBMemoryProvider()
    provider.initialize("s-e2e", hermes_home=str(world.home), embedder=world.embedder)
    world.provider = provider
    world.prompt_before = provider.system_prompt_block()


# -- When ---------------------------------------------------------------------


@when("vector recall runs with k=1")
def vector_recall_k1(world):
    world.hits = world.store.vector_recall([1.0, 0.0, 0.0, 0.0], k=1)


@when(parsers.parse('queue_prefetch runs for "{query}" and completes'))
def queue_prefetch_and_wait(world, query):
    world.provider.queue_prefetch(query)
    world.provider.flush_prefetch(timeout=5.0)
    world.prefetched = world.provider.prefetch(query)


@when('prefetch runs for trivial prompts "ok", "thanks!", and "/help"')
def prefetch_trivial_prompts(world):
    for prompt in ("ok", "thanks!", "/help"):
        text = world.provider.prefetch(prompt)
        status = world.provider.recall_status()
        world.trivial_results.append((text, status))


@when("facts are written and prefetches run")
def write_and_prefetch(world):
    world.provider.store.record_episode(
        episode_id="ep-inv",
        session="s-e2e",
        kind="message",
        at="2026-03-01T10:00:00Z",
        text="Fact",
        mentions=["ada"],
    )
    world.provider.store.record_fact(
        fact_id="f-inv",
        text="Ada likes RelateDB",
        slot="ada/likes",
        valid_from="2026-03-01T10:00:00Z",
        recorded_at="2026-03-01T10:00:00Z",
        episode_id="ep-inv",
        about=["ada"],
        embedding=world.embedder.embed_one("Ada likes RelateDB"),
    )
    world.provider.prefetch("What does Ada like?")
    world.prompt_after = world.provider.system_prompt_block()


# -- Then ---------------------------------------------------------------------


@then("only the current fact is returned with its entities, episode evidence, and replaced text")
def only_current_fact_returned(world):
    assert len(world.hits) == 1
    hit = world.hits[0]
    assert hit["id"] == "f2"
    assert hit["text"] == "Ada reviews each relate release"
    assert set(hit["about"]) == {"ada", "relate"}
    assert hit["learnedFrom"]["id"] == "ep-2"
    assert hit["replaced"] == ["Grace reviews each relate release"]


@then('prefetch returns the formatted "[RelateDB Memory]" block')
def prefetch_returns_formatted_block(world):
    assert "[RelateDB Memory]" in world.prefetched
    assert "Ada reviews each relate release" in world.prefetched


@then('recall_status reports provider_label "relatedb" with count 1')
def recall_status_reports_count(world):
    status = world.provider.recall_status()
    assert status is not None
    assert status.provider_label == "relatedb"
    assert status.count == 1


@then("prefetch returns an empty string and recall_status is None")
def trivial_prompts_return_empty(world):
    assert world.trivial_results == [("", None), ("", None), ("", None)]


@then("system_prompt_block is byte-for-byte identical before and after")
def system_prompt_identical(world):
    assert world.prompt_before == world.prompt_after
    assert isinstance(world.prompt_before, str)
    assert len(world.prompt_before) > 0
