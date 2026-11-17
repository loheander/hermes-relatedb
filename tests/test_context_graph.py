from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

spec = importlib.util.spec_from_file_location("index_specs", ROOT / "tools" / "index_specs.py")
index_specs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(index_specs)


def adr(num: str, title: str, status: str = "Accepted", extra: str = "", body: str = "Body.") -> str:
    return f"# ADR-{num}: {title}\n\n- Status: {status}\n- Date: 2026-01-01\n{extra}\n## Decision\n\n{body}\n"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    (tmp_path / "specs").mkdir()
    pkg = tmp_path / "relatedb_memory"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('"""Package."""\n')
    (pkg / "store.py").write_text('"""Store module. See ADR-0003."""\n')
    adrs = tmp_path / "docs" / "adr"
    (adrs / "0001-a.md").write_text(adr("0001", "Old way", "Superseded", body="Old design."))
    (adrs / "0002-b.md").write_text(
        adr("0002", "New way", extra="- Supersedes: ADR-0001\n", body="Uses relatedb_memory.store.")
    )
    (adrs / "0003-c.md").write_text(
        adr("0003", "Tweak", extra="- Amends: ADR-0002\n", body="Per ADR-0002 and specs/s.md.")
    )
    (tmp_path / "specs" / "s.md").write_text("# Spec S\n\n- Status: Draft\n\n## Rules\n\nSee ADR-0002.\n")
    return tmp_path


def test_second_run_writes_nothing(repo: Path):
    store = repo / "docs" / "context-graph"
    assert index_specs.index(repo, store) is True
    before = {p: p.read_bytes() for p in store.rglob("*") if p.is_file()}
    assert index_specs.index(repo, store) is False
    after = {p: p.read_bytes() for p in store.rglob("*") if p.is_file()}
    assert before == after


def test_store_is_directory_with_json_codec(repo: Path):
    store = repo / "docs" / "context-graph"
    index_specs.index(repo, store)
    for name in ("graph.json", "manifest.json", ".cypherlite/schema/schema.cypher"):
        assert (store / name).is_file()
    assert (store / "wal").is_dir()
    assert not list(store.rglob("*.rl"))
    assert '"codec": "json"' in (store / "manifest.json").read_text()
    assert "FULLTEXT INDEX `terms`" in (store / ".cypherlite/schema/schema.cypher").read_text()


def test_readonly_queries_do_not_dirty_store(repo: Path):
    store = repo / "docs" / "context-graph"
    index_specs.index(repo, store)
    before = {p: p.read_bytes() for p in store.rglob("*") if p.is_file()}
    index_specs.run_query(store, "active-adrs")
    index_specs.run_query(store, "chain", "ADR-0003")
    after = {p: p.read_bytes() for p in store.rglob("*") if p.is_file()}
    assert before == after


def test_active_adrs_exclude_fully_superseded_and_keep_amended(repo: Path):
    store = repo / "docs" / "context-graph"
    index_specs.index(repo, store)
    numbers = [r["number"] for r in index_specs.run_query(store, "active-adrs")]
    assert numbers == ["0002", "0003"]  # 0001 superseded; 0002 only amended


def test_supersession_chain(repo: Path):
    store = repo / "docs" / "context-graph"
    index_specs.index(repo, store)
    chain = [r["number"] for r in index_specs.run_query(store, "chain", "ADR-0003")]
    assert chain == ["0001", "0002", "0003"]


def test_blast_radius_returns_active_governing_adrs(repo: Path):
    store = repo / "docs" / "context-graph"
    index_specs.index(repo, store)
    got = {r["number"] for r in index_specs.run_query(store, "blast", "relatedb_memory.store")}
    assert got == {"0002", "0003"}  # 0003 via module docstring; 0002 via chunk mention


def test_reindex_after_change_updates_and_removes(repo: Path):
    store = repo / "docs" / "context-graph"
    index_specs.index(repo, store)
    (repo / "docs" / "adr" / "0003-c.md").unlink()
    assert index_specs.index(repo, store) is True
    assert [r["number"] for r in index_specs.run_query(store, "active-adrs")] == ["0002"]
    assert index_specs.index(repo, store) is False


def test_chunk_excerpt_is_capped(repo: Path):
    (repo / "docs" / "adr" / "0004-d.md").write_text(adr("0004", "Long", body="word " * 200))
    store = repo / "docs" / "context-graph"
    index_specs.index(repo, store)
    db = index_specs._connect(store, read_only=True)
    try:
        lengths = [len(r["t"]) for r in db.execute("MATCH (c:Chunk) RETURN c.text AS t")]
    finally:
        db.close()
    assert lengths and max(lengths) <= 160


def test_committed_store_is_current_and_covers_amendment():
    store = ROOT / "docs" / "context-graph"
    desired = index_specs.build_desired(ROOT)
    assert index_specs.is_current(store, desired)
    assert any(r[2] == "SUPERSEDES" and r[4] is True for r in desired["rels"])
    numbers = [r["number"] for r in index_specs.run_query(store, "active-adrs")]
    assert {"0001", "0002", "0004", "0005", "0006"} <= set(numbers)
    assert "0003" not in set(numbers)


def test_repo_conventions_for_git_diff():
    assert "docs/context-graph/graph.json diff=relate-json" in (ROOT / ".gitattributes").read_text()
    make = (ROOT / "Makefile").read_text()
    assert 'git config diff.relate-json.textconv "jq ."' in make
    assert "index-specs:" in make and "tools/index_specs.py" in make
    agents = (ROOT / "AGENTS.md").read_text()
    assert "--read-only=live" in agents and "read-only" in agents and "make index-specs" in agents
