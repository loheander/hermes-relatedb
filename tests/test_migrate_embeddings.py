"""Tests for tools/migrate_embeddings.py (#34)."""

from __future__ import annotations

from pathlib import Path

import pytest

from relatedb_memory import config as cfg
from relatedb_memory.embedder import FakeEmbedder
from relatedb_memory.store import RelateStore
from tools.migrate_embeddings import migrate_store


def _seed_256_store(tmp_path: Path, snapshot_format: str) -> tuple[Path, list[tuple[str, str, str]]]:
    old_embedder = FakeEmbedder(dim=256)
    db_name = "memory.rl" if snapshot_format == "rl" else "memory"
    config = cfg.resolve_config(
        tmp_path,
        env_get={
            "RELATEDB_SNAPSHOT_FORMAT": snapshot_format,
            "RELATEDB_DB_PATH": str(tmp_path / db_name),
        }.get,
    )
    facts = [
        ("f1", "pref:editor", "User prefers dark mode in editors"),
        ("f2", "loc:city", "User lives in Stockholm"),
        ("f3", "lang:primary", "User writes Python and Cypher"),
    ]
    with RelateStore.open(config, embedding_dim=256) as store:
        store.record_episode(
            episode_id="ep-1",
            session="s1",
            kind="message",
            at="2026-11-17T00:00:00Z",
            text="seed",
        )
        for fid, slot, text in facts:
            store.record_fact(
                fact_id=fid,
                text=text,
                slot=slot,
                valid_from="2026-11-17T00:00:00Z",
                recorded_at="2026-11-17T00:00:00Z",
                episode_id="ep-1",
                embedding=old_embedder.embed_one(text),
            )
    return config.db_path, facts


@pytest.mark.parametrize("snapshot_format", ["rl", "parquet", "json"])
def test_migrate_256_to_384_preserves_facts_and_recalls(tmp_path: Path, snapshot_format: str):
    db_path, _facts = _seed_256_store(tmp_path, snapshot_format)
    new_embedder = FakeEmbedder(dim=384)

    result = migrate_store(
        db_path,
        embedder=new_embedder,
        batch_size=2,
        backup=True,
        dry_run=False,
    )
    assert result.current_dim == 256
    assert result.target_dim == 384
    assert result.fact_count == 3
    assert result.updated_count == 3
    assert result.backup_path is not None and result.backup_path.exists()
    assert result.dry_run is False

    reopened_cfg = cfg.resolve_config(
        tmp_path,
        env_get={
            "RELATEDB_SNAPSHOT_FORMAT": snapshot_format,
            "RELATEDB_DB_PATH": str(db_path),
        }.get,
    )
    with RelateStore.open(reopened_cfg, embedding_dim=384) as store:
        hits = store.vector_recall(new_embedder.embed_query("User lives in Stockholm"), k=2)
        assert any(h["text"] == "User lives in Stockholm" for h in hits)


def test_migrate_dry_run_does_not_modify_store_or_create_backup(tmp_path: Path):
    db_path, _ = _seed_256_store(tmp_path, "parquet")
    before_entries = sorted(p.name for p in tmp_path.iterdir())

    result = migrate_store(db_path, dry_run=True)
    assert result.dry_run is True
    assert result.current_dim == 256
    assert result.target_dim == 384
    assert result.fact_count == 3
    assert result.updated_count == 0
    assert result.backup_path is None

    after_entries = sorted(p.name for p in tmp_path.iterdir())
    assert after_entries == before_entries


def test_migrate_missing_store_raises_file_not_found(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        migrate_store(tmp_path / "does-not-exist.rl", dry_run=True)
