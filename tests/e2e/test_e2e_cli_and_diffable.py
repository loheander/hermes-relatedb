"""Acceptance scenarios for diffable JSON store, MCP sidecar, and CLI (#10).

The scenarios live in ``features/cli_and_diffable.feature`` as Given/When/Then
text; this module binds each step to ``cli.main`` and ``git``.

The steps pin the contract #10 must implement::

    cli.build_parser() -> argparse.ArgumentParser
    cli.main(argv) -> int
      - init-diffable <path>
      - status [--path <path>]
      - verify [--path <path>]
      - mcp [--path <path>] [--read-only]
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("features/cli_and_diffable.feature")

ROOT = Path(__file__).resolve().parents[2]


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def world(tmp_path):
    return SimpleNamespace(
        repo=tmp_path / "repo",
        store_dir=None,
        exit_code=None,
        stdout="",
        stderr="",
    )


# -- Given --------------------------------------------------------------------


@given("an initialized temporary git repository")
def init_temp_git_repo(world):
    world.repo.mkdir(parents=True, exist_ok=True)
    _git(world.repo, "init")
    _git(world.repo, "config", "user.email", "test@example.com")
    _git(world.repo, "config", "user.name", "Test")


@given("an initialized diffable store committed in git")
def init_and_commit_diffable_store(world, monkeypatch, capsys):
    init_temp_git_repo(world)
    import cli

    monkeypatch.chdir(world.repo)
    assert cli.main(["init-diffable", "./memory"]) == 0
    capsys.readouterr()
    world.store_dir = world.repo / "memory"
    _write_sample_fact(world.store_dir, "f1", "ada/likes", "Ada likes RelateDB")
    _git(world.repo, "add", ".")
    _git(world.repo, "commit", "-m", "init store")


@given("an initialized diffable store with valid facts")
def init_diffable_store_with_facts(world, monkeypatch, capsys):
    init_and_commit_diffable_store(world, monkeypatch, capsys)


@given("an initialized diffable store")
def init_diffable_store_only(world, monkeypatch, capsys):
    init_temp_git_repo(world)
    import cli

    monkeypatch.chdir(world.repo)
    assert cli.main(["init-diffable", "./memory"]) == 0
    capsys.readouterr()
    world.store_dir = world.repo / "memory"


def _write_sample_fact(store_dir: Path, fact_id: str, slot: str, text: str) -> None:
    from relatedb_memory.config import RelateDBConfig
    from relatedb_memory.store import RelateStore

    cfg = RelateDBConfig(
        hermes_home=store_dir.parent,
        db_path=store_dir,
        snapshot_format="json",
    )
    with RelateStore.open(cfg, embedding_dim=4) as store:
        store.record_episode(
            episode_id=f"ep-{fact_id}",
            session="s1",
            kind="message",
            at="2026-03-01T00:00:00Z",
            text=text,
            mentions=["ada"],
        )
        store.record_fact(
            fact_id=fact_id,
            text=text,
            slot=slot,
            valid_from="2026-03-01T00:00:00Z",
            recorded_at="2026-03-01T00:00:00Z",
            episode_id=f"ep-{fact_id}",
            about=["ada"],
            embedding=[1.0, 0.0, 0.0, 0.0],
        )


# -- When ---------------------------------------------------------------------


@when(parsers.parse('hermes relatedb-memory init-diffable is run on "{rel_path}"'))
def run_init_diffable(world, rel_path, monkeypatch, capsys):
    import cli

    monkeypatch.chdir(world.repo)
    world.exit_code = cli.main(["init-diffable", rel_path])
    captured = capsys.readouterr()
    world.stdout = captured.out
    world.stderr = captured.err
    world.store_dir = world.repo / rel_path


@when("the initial store is committed and a new fact is written")
def commit_and_write_new_fact(world):
    _git(world.repo, "add", ".")
    _git(world.repo, "commit", "-m", "initial diffable store")
    _write_sample_fact(world.store_dir, "f2", "ada/editor", "Ada uses neovim")


@when("the exact same fact write is replayed")
def replay_same_fact(world):
    _write_sample_fact(world.store_dir, "f1", "ada/likes", "Ada likes RelateDB")


@when("hermes relatedb-memory status is run")
def run_status(world, monkeypatch, capsys):
    import cli

    monkeypatch.chdir(world.repo)
    world.exit_code = cli.main(["status", "--path", str(world.store_dir)])
    captured = capsys.readouterr()
    world.stdout = captured.out
    world.stderr = captured.err


@when("hermes relatedb-memory verify is run")
def run_verify(world, monkeypatch, capsys):
    import cli

    monkeypatch.chdir(world.repo)
    world.exit_code = cli.main(["verify", "--path", str(world.store_dir)])
    captured = capsys.readouterr()
    world.stdout = captured.out
    world.stderr = captured.err


@when("a duplicate open fact is injected into the same slot")
def inject_duplicate_open_fact(world, monkeypatch, capsys):
    import relate

    conn = relate.connect(str(world.store_dir))
    try:
        conn.execute(
            "CREATE (:Fact {id: 'f-dup', text: 'dup', slot: 'ada/likes', "
            "validFrom: '2026-03-02T00:00:00Z', recordedAt: '2026-03-02T00:00:00Z'})"
        )
    finally:
        conn.close()

    import cli

    monkeypatch.chdir(world.repo)
    world.exit_code = cli.main(["verify", "--path", str(world.store_dir)])
    captured = capsys.readouterr()
    world.stdout = captured.out
    world.stderr = captured.err


@when("hermes relatedb-memory mcp --read-only is run")
def run_mcp_readonly(world, monkeypatch, capsys):
    import cli

    monkeypatch.chdir(world.repo)
    world.exit_code = cli.main(["mcp", "--path", str(world.store_dir), "--read-only"])
    captured = capsys.readouterr()
    world.stdout = captured.out
    world.stderr = captured.err


# -- Then ---------------------------------------------------------------------


@then("the JSON-codec store, .gitattributes, and git textconv config are created")
def json_store_and_git_config_created(world):
    assert world.exit_code == 0
    assert (world.store_dir / "graph.json").exists()
    assert (world.store_dir / "manifest.json").exists()
    assert (world.store_dir / "wal").is_dir()
    attrs = (world.repo / ".gitattributes").read_text(encoding="utf-8")
    assert "diff=relate-json" in attrs
    textconv = _git(world.repo, "config", "diff.relate-json.textconv").stdout.strip()
    assert textconv == "jq ."


@then("git status and git diff show the added node and relationship")
def git_diff_shows_new_fact(world):
    status = _git(world.repo, "status", "--short").stdout
    assert "graph.json" in status
    if shutil.which("jq") is not None:
        diff = _git(world.repo, "diff", "--", str(world.store_dir / "graph.json")).stdout
        assert "Ada uses neovim" in diff


@then("graph.json has zero git diff")
def graph_json_zero_diff(world):
    diff = _git(world.repo, "diff", "--", str(world.store_dir / "graph.json")).stdout
    assert diff.strip() == ""


@then("status reports store path, codec, and node/relationship counts")
def status_reports_counts(world):
    assert world.exit_code == 0
    data = json.loads(world.stdout)
    assert data["codec"] == "json"
    assert data["nodes"] >= 1
    assert data["relationships"] >= 1
    assert str(world.store_dir) in data["path"]


@then("verify exits 0")
def verify_exits_zero(world):
    assert world.exit_code == 0


@then("verify exits non-zero")
def verify_exits_nonzero(world):
    assert world.exit_code != 0


@then("it outputs a valid relate serve --mcp stdio --read-only=live configuration")
def mcp_outputs_valid_config(world):
    assert world.exit_code == 0
    data = json.loads(world.stdout)
    assert data["command"] == "relate"
    assert data["args"] == [
        "serve",
        "--mcp",
        "stdio",
        "--database",
        str(world.store_dir),
        "--read-only=live",
    ]


@then("importing cli and building the parser does not load model2vec or numpy")
def cli_import_is_lightweight():
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, cli; cli.build_parser(); "
            "assert 'model2vec' not in sys.modules; "
            "assert 'numpy' not in sys.modules",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
