"""Built-in memory mirroring keeps one slot per USER.md/MEMORY.md entry (#42)."""

from __future__ import annotations

import pytest

from relatedb_memory.embedder import FakeEmbedder
from relatedb_memory.provider import RelateDBMemoryProvider


@pytest.fixture
def provider(tmp_path):
    p = RelateDBMemoryProvider()
    p.initialize("s1", hermes_home=str(tmp_path), embedder=FakeEmbedder(dim=4))
    yield p
    p.shutdown()


def _open(provider):
    rows = provider.store.run(
        "MATCH (f:Fact) WHERE f.closedAt IS NULL AND f.slot STARTS WITH 'builtin/' "
        "RETURN f.text AS text ORDER BY text"
    )
    return [r["text"] for r in rows]


def _add3(provider):
    for text in ("alpha", "beta", "gamma"):
        provider.on_memory_write("add", "user", text)


def test_three_adds_leave_three_open(provider):
    _add3(provider)
    assert _open(provider) == ["alpha", "beta", "gamma"]


def test_replace_closes_only_that_entry_and_supersedes(provider):
    _add3(provider)
    provider.on_memory_write("replace", "user", "beta2", metadata={"previous_content": "beta"})
    assert _open(provider) == ["alpha", "beta2", "gamma"]
    rows = provider.store.run(
        "MATCH (n:Fact {text: 'beta2'})-[:SUPERSEDES]->(o:Fact {text: 'beta'}) "
        "MATCH (n)-[:FROM]->(ep:Episode) RETURN o.closedAt AS closed, ep.kind AS kind"
    )
    assert len(rows) == 1 and rows[0]["closed"] is not None
    assert rows[0]["kind"] == "memory_write"


def test_remove_closes_only_that_entry(provider):
    _add3(provider)
    provider.on_memory_write("remove", "user", "", metadata={"previous_content": "beta"})
    assert _open(provider) == ["alpha", "gamma"]


def test_old_text_fallback_needs_single_match(provider):
    _add3(provider)
    provider.on_memory_write("remove", "user", "", metadata={"old_text": "amm"})
    assert _open(provider) == ["alpha", "beta"]
    provider.on_memory_write("remove", "user", "", metadata={"old_text": "a"})  # ambiguous
    assert _open(provider) == ["alpha", "beta"]


def test_without_metadata_never_closes_more_than_one(provider):
    _add3(provider)
    provider.on_memory_write("remove", "user", "")
    provider.on_memory_write("replace", "user", "delta")
    assert _open(provider) == ["alpha", "beta", "delta", "gamma"]
    provider.on_memory_write("remove", "user", "alpha")  # legacy: content is the entry
    assert _open(provider) == ["beta", "delta", "gamma"]


def test_targets_with_identical_text_do_not_collide(provider):
    provider.on_memory_write("add", "user", "same")
    provider.on_memory_write("add", "memory", "same")
    assert _open(provider) == ["same", "same"]
    provider.on_memory_write("remove", "memory", "", metadata={"previous_content": "same"})
    assert _open(provider) == ["same"]


def test_explicit_slot_targets_behave_as_before(provider):
    provider.on_memory_write("add", "prefs/editor", "vim")
    provider.on_memory_write("add", "prefs/editor", "neovim")
    assert provider.store.active_slots() == ["prefs/editor"]
    provider.on_memory_write("remove", "prefs/editor", "")
    assert provider.store.active_slots() == []
