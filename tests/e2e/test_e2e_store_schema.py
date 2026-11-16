"""Acceptance scenarios for the bi-temporal schema and thread-affine store (#4).

Each test reads as a scenario: Given a profile, When something happens to the
store, Then the observable outcome holds. All plumbing lives in the helpers
below, and every scenario runs against a real embedded ``relate-db`` file.

The helpers pin the contract #4 must implement::

    relatedb_memory.store.RelateStore.open(config, embedding_dim=...) -> store
    store.run(cypher, **params) -> list[dict]   # safe from any thread
    store.close()                               # flush, then close on the owner thread

Every scenario is ``xfail(strict=True)`` until #4 lands; #4 removes the marker,
so a premature pass fails the suite instead of going unnoticed.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from relatedb_memory import config as cfg

pytestmark = pytest.mark.xfail(strict=True, reason="Pending #4")

ROOT = Path(__file__).resolve().parents[2]
EMBEDDING_DIM = 4
THREADS = 8
WRITES_PER_THREAD = 10


# -- scenario DSL -------------------------------------------------------------


def a_profile(tmp_path: Path, name: str = "default") -> Path:
    """Given a Hermes profile directory that has no memory store yet."""
    home = tmp_path / name
    home.mkdir()
    return home


def store_path(home: Path) -> Path:
    return cfg.resolve_config(home, env_get={}.get).db_path


def open_store(home: Path):
    """When the profile's store is opened (created on first open)."""
    from relatedb_memory.store import RelateStore

    config = cfg.resolve_config(home, env_get={}.get)
    return RelateStore.open(config, embedding_dim=EMBEDDING_DIM)


def remember(store, key: str) -> None:
    store.run("MERGE (:Entity {key: $key})", key=key)


def remembered_keys(store) -> set[str]:
    return {row["key"] for row in store.run("MATCH (e:Entity) RETURN e.key AS key")}


def constraint_names(store) -> set[str]:
    return {row["name"] for row in store.run("SHOW CONSTRAINTS")}


def indexes_by_name(store) -> dict[str, dict]:
    return {row["name"]: row for row in store.run("SHOW INDEXES")}


def in_threads(count: int, work) -> list[BaseException]:
    """Run ``work(i)`` on ``count`` simultaneous threads; return the errors raised."""
    barrier = threading.Barrier(count)

    def job(i: int):
        barrier.wait()
        work(i)

    with ThreadPoolExecutor(max_workers=count) as pool:
        futures = [pool.submit(job, i) for i in range(count)]
    return [err for f in futures if (err := f.exception()) is not None]


# -- scenarios ----------------------------------------------------------------


def test_fresh_profile_store_bootstraps_the_bitemporal_schema(tmp_path):
    # Given a profile with no store
    home = a_profile(tmp_path)
    assert not store_path(home).exists()

    # When its store is opened
    store = open_store(home)

    # Then the store file exists at <hermes_home>/memory.rl
    assert store_path(home) == home / "memory.rl"
    assert store_path(home).exists()

    # And the uniqueness constraints are in place
    assert {"entity_key", "episode_id", "fact_id"} <= constraint_names(store)

    # And facts are indexed by slot and by embedding, scoped by closedAt
    indexes = indexes_by_name(store)
    assert indexes["fact_slot"]["type"] == "RANGE"
    assert indexes["fact_slot"]["properties"] == ["slot"]
    assert indexes["fact_embedding"]["type"] == "VECTOR"
    assert indexes["fact_embedding"]["properties"] == ["embedding", "closedAt"]
    store.close()


def test_reopening_an_existing_store_is_idempotent(tmp_path):
    # Given a populated store that has been closed
    home = a_profile(tmp_path)
    first = open_store(home)
    remember(first, "ada")
    first.run(
        "MATCH (a:Entity {key: 'ada'}) CREATE (a)-[:SAID_IN]->(:Episode {id: 'ep-1'})"
    )
    schema_before = (constraint_names(first), set(indexes_by_name(first)))
    first.close()

    # When the store is opened again
    second = open_store(home)

    # Then opening did not fail on the existing constraints and indexes
    assert (constraint_names(second), set(indexes_by_name(second))) == schema_before

    # And the nodes and the relationship are preserved
    assert remembered_keys(second) == {"ada"}
    linked = second.run(
        "MATCH (:Entity {key: 'ada'})-[:SAID_IN]->(ep:Episode) RETURN ep.id AS id"
    )
    assert [row["id"] for row in linked] == ["ep-1"]
    second.close()


def test_agent_and_background_threads_share_one_store_without_losing_writes(tmp_path):
    # Given an open store
    home = a_profile(tmp_path)
    store = open_store(home)

    # When several threads write and read at the same time
    def work(i: int) -> None:
        for n in range(WRITES_PER_THREAD):
            remember(store, f"thread-{i}-fact-{n}")
            remembered_keys(store)

    errors = in_threads(THREADS, work)

    # Then no thread hit a thread-affinity violation or any other error
    assert errors == []

    # And every write is present
    assert len(remembered_keys(store)) == THREADS * WRITES_PER_THREAD
    store.close()


def test_a_store_closes_cleanly_after_threaded_use_and_can_be_reopened(tmp_path):
    # Given a store that background threads have written to
    home = a_profile(tmp_path)
    store = open_store(home)
    assert in_threads(THREADS, lambda i: remember(store, f"bg-{i}")) == []

    # When it is closed from a thread other than the one that opened it
    closer = threading.Thread(target=store.close)
    closer.start()
    closer.join(timeout=30)

    # Then close completed, and the flushed writes survive a re-open
    assert not closer.is_alive()
    reopened = open_store(home)
    assert remembered_keys(reopened) == {f"bg-{i}" for i in range(THREADS)}
    reopened.close()


def test_two_profiles_operate_concurrently_without_cross_talk(tmp_path):
    # Given two profiles, each with its own open store
    homes = {name: a_profile(tmp_path, name) for name in ("work", "personal")}
    stores = {name: open_store(home) for name, home in homes.items()}

    # When both are written to at the same time
    def work(i: int) -> None:
        name = ("work", "personal")[i % 2]
        for n in range(WRITES_PER_THREAD):
            remember(stores[name], f"{name}-{i}-{n}")

    errors = in_threads(THREADS, work)

    # Then neither raised, and each store holds only its own profile's data
    assert errors == []
    for name, store in stores.items():
        keys = remembered_keys(store)
        assert keys and all(key.startswith(f"{name}-") for key in keys)
        assert store_path(homes[name]).exists()
    assert store_path(homes["work"]) != store_path(homes["personal"])
    for store in stores.values():
        store.close()


def test_importing_the_store_module_creates_no_database(tmp_path):
    # Given a profile with no store
    home = a_profile(tmp_path)

    # When the store module is imported in a fresh interpreter
    result = subprocess.run(
        [sys.executable, "-c", "from relatedb_memory.store import RelateStore"],
        cwd=ROOT,
        env={"HERMES_HOME": str(home), "PATH": ""},
        capture_output=True,
        text=True,
    )

    # Then the import succeeds and leaves no database file or directory behind
    assert result.returncode == 0, result.stderr
    assert list(home.iterdir()) == []
