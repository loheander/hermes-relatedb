"""Unit tests for bi-temporal write operations and validation (#6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from relatedb_memory import config as cfg
from relatedb_memory.store import RelateStore


def test_invalid_episode_kind_rejected(tmp_path: Path):
    config = cfg.resolve_config(tmp_path, env_get={}.get)
    with RelateStore.open(config, embedding_dim=4) as store:
        with pytest.raises(ValueError, match="Unsupported episode kind"):
            store.record_episode(
                episode_id="ep-bad",
                session="s1",
                kind="unknown",
                at="2026-03-01T00:00:00Z",
                text="bad",
            )


def test_retract_missing_slot_returns_zero(tmp_path: Path):
    config = cfg.resolve_config(tmp_path, env_get={}.get)
    with RelateStore.open(config, embedding_dim=4) as store:
        assert store.retract_slot(slot="nonexistent", valid_to="2026-03-01T00:00:00Z", closed_at="2026-03-01T00:00:00Z") == 0
        assert store.active_slots() == []


def test_fact_embedding_dimension_mismatch_rejected(tmp_path: Path):
    config = cfg.resolve_config(tmp_path, env_get={}.get)
    with RelateStore.open(config, embedding_dim=4) as store:
        store.record_episode(
            episode_id="ep-1",
            session="s1",
            kind="message",
            at="2026-03-01T00:00:00Z",
            text="hello",
        )
        with pytest.raises(ValueError, match="Expected embedding of dimension 4"):
            store.record_fact(
                fact_id="f1",
                text="hello",
                slot="s/1",
                valid_from="2026-03-01T00:00:00Z",
                recorded_at="2026-03-01T00:00:00Z",
                episode_id="ep-1",
                embedding=[1.0, 2.0],
            )
