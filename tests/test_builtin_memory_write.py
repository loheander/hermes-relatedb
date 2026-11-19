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


def test_builtin_targets_are_case_insensitive(provider):
    provider.on_memory_write("add", " User ", "alpha")
    provider.on_memory_write("add", "MEMORY", "beta")
    assert _open(provider) == ["alpha", "beta"]
    slots = provider.store.run("MATCH (f:Fact) RETURN f.slot AS slot ORDER BY slot")
    assert [r["slot"].split("/")[1] for r in slots] == ["memory", "user"]


class _CountingEmbedder(FakeEmbedder):
    calls = 0

    def embed_one(self, text):
        type(self).calls += 1
        return super().embed_one(text)


def _all_open(provider):
    rows = provider.store.run("MATCH (f:Fact) WHERE f.closedAt IS NULL RETURN f.slot AS slot, f.text AS text")
    return {(r["slot"], r["text"]) for r in rows}


def _counts(provider):
    eps = provider.store.run("MATCH (e:Episode) RETURN count(e) AS n")[0]["n"]
    facts = provider.store.run("MATCH (f:Fact) RETURN count(f) AS n")[0]["n"]
    closed = provider.store.run("MATCH (f:Fact) WHERE f.closedAt IS NOT NULL RETURN count(f) AS n")[0]["n"]
    return eps, facts, closed


@pytest.mark.parametrize("target", ["prefs/editor", "memory/default", "", "users"])
def test_unknown_target_is_ignored_with_warning(tmp_path, caplog, target):
    _CountingEmbedder.calls = 0
    p = RelateDBMemoryProvider()
    p.initialize("s1", hermes_home=str(tmp_path), embedder=_CountingEmbedder(dim=4))
    try:
        # An explicit slot set through the tool stays untouched by the hook.
        p.handle_tool_call("relatedb_remember", {"slot": "prefs/editor", "text": "vim"})
        before = _counts(p)
        calls = _CountingEmbedder.calls
        caplog.clear()
        with caplog.at_level("WARNING", logger="relatedb_memory.provider"):
            for action, content in (
                ("add", "neovim"),
                ("replace", "helix"),
                ("patch", "kakoune"),
                ("remove", ""),
            ):
                p.on_memory_write(action, target, content, metadata={"previous_content": "vim"})
        assert _counts(p) == before
        assert _CountingEmbedder.calls == calls
        assert ("prefs/editor", "vim") in _all_open(p)
        warnings = [r for r in caplog.records if r.levelname == "WARNING" and "ignores target" in r.getMessage()]
        assert len(warnings) == 4
    finally:
        p.shutdown()


def test_target_is_required(provider):
    with pytest.raises(TypeError):
        provider.on_memory_write("add")  # type: ignore[call-arg]


def test_mirror_off_skips_builtin_and_keeps_existing(tmp_path, monkeypatch):
    monkeypatch.setenv("RELATEDB_MIRROR_BUILTIN_MEMORY", "true")
    p = RelateDBMemoryProvider()
    p.initialize("s1", hermes_home=str(tmp_path), embedder=FakeEmbedder(dim=4))
    p.on_memory_write("add", "user", "alpha")
    p.shutdown()

    monkeypatch.setenv("RELATEDB_MIRROR_BUILTIN_MEMORY", "false")
    _CountingEmbedder.calls = 0
    p = RelateDBMemoryProvider()
    p.initialize("s2", hermes_home=str(tmp_path), embedder=_CountingEmbedder(dim=4))
    try:
        p.on_memory_write("add", "user", "beta")
        p.on_memory_write("add", "memory", "gamma")
        p.on_memory_write("replace", "user", "alpha2", metadata={"previous_content": "alpha"})
        p.on_memory_write("patch", "memory", "gamma2", metadata={"previous_content": "gamma"})
        p.on_memory_write("remove", "user", "", metadata={"previous_content": "alpha"})
        assert _CountingEmbedder.calls == 0
        assert [t for t in _open(p)] == ["alpha"]
        eps = p.store.run("MATCH (e:Episode) WHERE e.kind = 'memory_write' RETURN count(e) AS n")
        assert eps[0]["n"] == 1  # only the earlier mirrored write
    finally:
        p.shutdown()
