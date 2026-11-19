"""Fact origin, capped recall of captured turns and origin backfill (#39)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from relatedb_memory import config as cfg
from relatedb_memory.embedder import FakeEmbedder
from relatedb_memory.provider import RelateDBMemoryProvider, _format_recall_block
from relatedb_memory.store import RelateStore
from tools.backfill_origins import backfill_store

T = "2026-03-01T00:00:00Z"


def _open(tmp_path: Path) -> RelateStore:
    return RelateStore.open(cfg.resolve_config(tmp_path, env_get={}.get), embedding_dim=4)


def _seed(store: RelateStore, *, turns: int, remembered: int) -> None:
    store.record_episode(episode_id="ep-t", session="s", kind="message", at=T, text="turn")
    store.record_episode(episode_id="ep-r", session="s", kind="tool_call", at=T, text="rem")
    for i in range(turns):
        store.record_fact(
            fact_id=f"t{i}", text=f"turn {i}", slot=f"turn/s/{i}", valid_from=T, recorded_at=T,
            episode_id="ep-t", embedding=[1.0, 0.001 * i, 0.0, 0.0],
        )
    for i in range(remembered):
        # Slightly further from the query than every turn.
        store.record_fact(
            fact_id=f"r{i}", text=f"remembered {i}", slot=f"topic/{i}", valid_from=T, recorded_at=T,
            episode_id="ep-r", embedding=[1.0, 0.5, 0.0, 0.0],
        )


def test_remembered_facts_survive_fifty_captured_turns(tmp_path):
    with _open(tmp_path) as store:
        _seed(store, turns=50, remembered=2)
        hits = store.vector_recall([1.0, 0.0, 0.0, 0.0], k=8)
    ids = [h["id"] for h in hits]
    assert {"r0", "r1"} <= set(ids)
    assert len(hits) == 6  # 4 captured (half of 8) + 2 deliberate


@pytest.mark.parametrize("k,share,cap", [(8, 0.5, 4), (10, 0.3, 3), (4, 0.0, 0), (6, 1.0, 6), (1, 0.5, 1)])
def test_captured_never_exceed_share(tmp_path, k, share, cap):
    with _open(tmp_path) as store:
        _seed(store, turns=30, remembered=0)
        hits = store.vector_recall([1.0, 0.0, 0.0, 0.0], k=k, captured_share=share)
    assert len(hits) == cap
    assert all(h["origin"] == "turn" for h in hits)


def test_origin_defaults_from_episode_kind_and_is_explicit_when_given(tmp_path):
    with _open(tmp_path) as store:
        _seed(store, turns=1, remembered=1)
        store.record_fact(
            fact_id="x", text="x", slot="x", valid_from=T, recorded_at=T, episode_id="ep-t",
            embedding=[0.0, 1.0, 0.0, 0.0], origin="memory_write",
        )
        rows = {r["id"]: r["origin"] for r in store.run("MATCH (f:Fact) RETURN f.id AS id, f.origin AS origin")}
        with pytest.raises(ValueError, match="Unsupported fact origin"):
            store.record_fact(
                fact_id="y", text="y", slot="y", valid_from=T, recorded_at=T, episode_id="ep-t", origin="bogus"
            )
    assert rows == {"t0": "turn", "r0": "remember", "x": "memory_write"}


def test_invalid_captured_share_rejected(tmp_path):
    with _open(tmp_path) as store:
        with pytest.raises(ValueError, match="captured_share"):
            store.vector_recall([1.0, 0.0, 0.0, 0.0], k=2, captured_share=1.5)


def test_provider_writes_set_origin_and_prefetch_marks_it(tmp_path):
    p = RelateDBMemoryProvider()
    p.initialize("s1", hermes_home=str(tmp_path), embedder=FakeEmbedder(dim=4), agent_context="primary")
    try:
        p.sync_turn("what is my editor?", "dunno")
        p.flush_sync()
        p.on_memory_write("add", "user", "editor is helix")
        p.handle_tool_call("relatedb_remember", {"text": "editor is helix", "slot": "pref/editor"})
        p.on_pre_compress([{"role": "user", "content": "compress me"}])
        origins = {r["origin"] for r in p.store.run("MATCH (f:Fact) RETURN f.origin AS origin")}
        assert origins == {"turn", "memory_write", "remember", "pre_compress"}
        out = json.loads(p.handle_tool_call("relatedb_recall", {"query": "editor", "k": 8}))
        assert all(h["origin"] in origins for h in out["results"])
        assert "from=" in p.prefetch("tell me about my editor please")
    finally:
        p.shutdown()


def test_recall_block_labels_captured_as_transcript():
    block = _format_recall_block(
        [
            {"text": "a", "origin": "turn", "learnedFrom": {"kind": "message"}},
            {"text": "b", "origin": "remember", "learnedFrom": {"kind": "tool_call"}},
        ]
    )
    assert "from=turn transcript, unconfirmed" in block
    assert "from=remember)" in block


def test_backfill_is_idempotent(tmp_path):
    config = cfg.resolve_config(tmp_path, env_get={}.get)
    with RelateStore.open(config, embedding_dim=4) as store:
        _seed(store, turns=2, remembered=1)
        store.run("MATCH (f:Fact) REMOVE f.origin")
    first = backfill_store(config.db_path, dry_run=True)
    assert (first.missing_count, first.updated_count) == (3, 0)
    done = backfill_store(config.db_path)
    assert (done.missing_count, done.updated_count) == (3, 3)
    again = backfill_store(config.db_path)
    assert (again.missing_count, again.updated_count) == (0, 0)
    with RelateStore.open(config, embedding_dim=4) as store:
        rows = {r["id"]: r["origin"] for r in store.run("MATCH (f:Fact) RETURN f.id AS id, f.origin AS origin")}
    assert rows == {"t0": "turn", "t1": "turn", "r0": "remember"}
