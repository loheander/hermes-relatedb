"""Near-duplicate flagging and recall collapse (#40)."""

from __future__ import annotations

import json
from pathlib import Path

import relate

from relatedb_memory import config as cfg
from relatedb_memory.provider import _format_recall_block
from relatedb_memory.store import RelateStore

T = "2026-03-01T00:00:00Z"
Q = [1.0, 0.0, 0.0, 0.0]
PARAPHRASE = [1.0, 0.1, 0.0, 0.0]  # cosine ~0.995 with Q
TABS = [1.0, 0.0, 0.0, 0.0]
SPACES = [0.6, 0.8, 0.0, 0.0]  # cosine 0.6 with TABS: differs in a key detail


def _open(tmp_path: Path) -> RelateStore:
    return RelateStore.open(cfg.resolve_config(tmp_path, env_get={}.get), embedding_dim=4)


def _episode(store, ep, kind="message", at=T):
    store.record_episode(episode_id=ep, session="s", kind=kind, at=at, text=ep)


def _fact(store, fid, vec, *, ep, slot=None, at=T, origin=None, text=None):
    store.record_fact(
        fact_id=fid, text=text or fid, slot=slot or f"turn/s/{fid}", valid_from=at, recorded_at=at,
        episode_id=ep, embedding=vec, origin=origin,
    )


def _edges(store):
    return store.run(
        "MATCH (a:Fact)-[r:DUPLICATE_OF]->(b:Fact) RETURN a.id AS dup, b.id AS canon, r.score AS score ORDER BY dup"
    )


def test_paraphrases_linked_and_key_detail_not(tmp_path):
    with _open(tmp_path) as store:
        for ep in ("e1", "e2", "e3"):
            _episode(store, ep)
        _fact(store, "tabs1", TABS, ep="e1", at="2026-03-01T00:00:01Z")
        _fact(store, "tabs2", PARAPHRASE, ep="e2", at="2026-03-01T00:00:02Z")
        _fact(store, "spaces", SPACES, ep="e3", at="2026-03-01T00:00:03Z")
        store.dedupe_facts(0.92)
        edges = _edges(store)
    assert [(e["dup"], e["canon"]) for e in edges] == [("tabs2", "tabs1")]
    assert edges[0]["score"] > 0.92


def test_rerun_is_idempotent(tmp_path):
    with _open(tmp_path) as store:
        for ep in ("e1", "e2", "e3"):
            _episode(store, ep)
        for i, ep in enumerate(("e1", "e2", "e3")):
            _fact(store, f"f{i}", [1.0, 0.01 * i, 0, 0], ep=ep, at=f"2026-03-01T00:00:0{i}Z")
        first = store.dedupe_facts(0.92)
        before = _edges(store)
        second = store.dedupe_facts(0.92)
        after = _edges(store)
    assert len(first) == 2 and second == []
    assert before == after


def test_dry_run_proposes_and_writes_nothing(tmp_path):
    with _open(tmp_path) as store:
        _episode(store, "e1")
        _episode(store, "e2")
        _fact(store, "a", Q, ep="e1", at="2026-03-01T00:00:01Z")
        _fact(store, "b", PARAPHRASE, ep="e2", at="2026-03-01T00:00:02Z")
        proposed = store.dedupe_facts(0.92, dry_run=True)
        assert _edges(store) == []
    assert [(c["fact_id"], c["canonical_id"], c["action"]) for c in proposed] == [("b", "a", "link")]
    assert proposed[0]["score"] > 0.92


def test_canonical_prefers_deliberate_then_earliest(tmp_path):
    with _open(tmp_path) as store:
        _episode(store, "e1")
        _episode(store, "e2", kind="tool_call")
        _fact(store, "turn-early", Q, ep="e1", at="2026-03-01T00:00:01Z")
        _fact(store, "remembered", PARAPHRASE, ep="e2", slot="pref/x", at="2026-03-01T00:00:09Z")
        store.dedupe_facts(0.92)
        edges = _edges(store)
    assert [(e["dup"], e["canon"]) for e in edges] == [("turn-early", "remembered")]


def test_different_explicit_slots_never_merge_and_closed_never_canonical(tmp_path):
    with _open(tmp_path) as store:
        _episode(store, "e1", kind="tool_call")
        _episode(store, "e2", kind="tool_call")
        _episode(store, "e3")
        _fact(store, "x", Q, ep="e1", slot="pref/a", at="2026-03-01T00:00:01Z")
        _fact(store, "y", PARAPHRASE, ep="e2", slot="pref/b", at="2026-03-01T00:00:02Z")
        store.dedupe_facts(0.92)
        assert _edges(store) == []
        store.retract_slot(slot="pref/a", valid_to=T, closed_at=T)
        _fact(store, "z", PARAPHRASE, ep="e3", at="2026-03-01T00:00:03Z")
        store.dedupe_facts(0.92)
        edges = _edges(store)
    assert [(e["dup"], e["canon"]) for e in edges] == [("z", "y")]


def test_on_write_pass_links_new_fact(tmp_path):
    with _open(tmp_path) as store:
        _episode(store, "e1")
        _episode(store, "e2")
        _fact(store, "a", Q, ep="e1", at="2026-03-01T00:00:01Z")
        _fact(store, "b", PARAPHRASE, ep="e2", at="2026-03-01T00:00:02Z")
        store.dedupe_facts(0.92, fact_ids=["b"])
        assert [(e["dup"], e["canon"]) for e in _edges(store)] == [("b", "a")]
        assert store.dedupe_facts(0.92, fact_ids=["b"]) == []


def _cluster_store(store):
    for ep in ("e1", "e2", "e3"):
        _episode(store, ep)
    _fact(store, "a", Q, ep="e1", at="2026-03-01T00:00:01Z")
    _fact(store, "b", PARAPHRASE, ep="e2", at="2026-03-01T00:00:02Z")
    _fact(store, "c", [1.0, 0.05, 0, 0], ep="e2", at="2026-03-01T00:00:03Z")  # same episode as b
    _fact(store, "other", [0.0, 0.0, 1.0, 0.0], ep="e3", at="2026-03-01T00:00:04Z")
    store.dedupe_facts(0.92)


def test_recall_collapses_clusters_and_counts_distinct_episodes(tmp_path):
    with _open(tmp_path) as store:
        _cluster_store(store)
        hits = store.vector_recall(Q, k=8, captured_share=1.0, dedupe=True)
    by_id = {h["id"]: h for h in hits}
    assert set(by_id) == {"a", "other"}
    assert by_id["a"]["seen"] == 2  # e1 and e2; b and c share e2
    assert by_id["other"]["seen"] == 1
    assert "seen=2" in _format_recall_block(hits)
    assert "seen=1" not in _format_recall_block(hits)


def test_recall_returns_canonical_even_when_only_duplicate_is_in_pool(tmp_path):
    with _open(tmp_path) as store:
        _cluster_store(store)
        # k=1 with a tiny pool is not forced here; collapse must still surface the canonical.
        hits = store.vector_recall([1.0, 0.1, 0, 0], k=1, captured_share=1.0, dedupe=True)
    assert [h["id"] for h in hits] == ["a"]


def test_disabled_dedupe_keeps_recall_exactly(tmp_path):
    with _open(tmp_path) as store:
        _cluster_store(store)
        plain = store.vector_recall(Q, k=8, captured_share=1.0)
        off = store.vector_recall(Q, k=8, captured_share=1.0, dedupe=False)
    assert plain == off
    assert {"a", "b", "c", "other"} == {h["id"] for h in plain}
    assert all("seen" not in h for h in plain)


def test_cli_dry_run_writes_nothing_then_dedupe_links(tmp_path, monkeypatch, capsys):
    import importlib.util
    import sys

    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("relatedb_cli_under_test", root / "cli.py")
    cli = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = cli
    spec.loader.exec_module(cli)

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    config = cfg.resolve_config(home, env_get={}.get)
    with RelateStore.open(config, embedding_dim=4) as store:
        _episode(store, "e1")
        _episode(store, "e2")
        _fact(store, "a", Q, ep="e1", at="2026-03-01T00:00:01Z")
        _fact(store, "b", PARAPHRASE, ep="e2", at="2026-03-01T00:00:02Z")

    assert cli.main(["dedupe", "--dry-run"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True
    assert [(c["fact_id"], c["canonical_id"]) for c in out["links"]] == [("b", "a")]
    conn = relate.connect(str(config.db_path), read_only=True)
    try:
        assert list(conn.execute("MATCH ()-[r:DUPLICATE_OF]->() RETURN count(r) AS c"))[0]["c"] == 0
    finally:
        conn.close()

    assert cli.main(["dedupe"]) == 0
    capsys.readouterr()
    assert cli.main(["dedupe"]) == 0
    again = json.loads(capsys.readouterr().out)
    assert again["links"] == [] and again["unlinks"] == []


def test_provider_flags_repeated_turns_and_respects_dedupe_off(tmp_path):
    from relatedb_memory.embedder import FakeEmbedder
    from relatedb_memory.provider import RelateDBMemoryProvider

    def run(home: Path, env: dict[str, str]) -> list[dict]:
        import os

        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            p = RelateDBMemoryProvider()
            p.initialize("s1", hermes_home=str(home), embedder=FakeEmbedder(dim=4), agent_context="primary")
            for _ in range(2):
                p.sync_turn("same statement", "ok", session_id="s1")
                p.flush_sync()
            out = json.loads(p.handle_tool_call("relatedb_recall", {"query": "same statement", "k": 8}))
            edges = p.store.run("MATCH ()-[r:DUPLICATE_OF]->() RETURN count(r) AS c")[0]["c"]
            p.shutdown()
            return [len(out["results"]), edges]
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    assert run(tmp_path / "on", {}) == [1, 1]
    assert run(tmp_path / "off", {"RELATEDB_DEDUPE": "false"}) == [2, 0]
