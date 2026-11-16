"""Acceptance scenarios for the bi-temporal schema and thread-affine store (#4).

The scenarios live in ``features/store_schema.feature`` as Given/When/Then
text; this module only binds each step to the store. Every scenario runs
against a real embedded ``relate-db`` file.

The steps pin the contract #4 must implement::

    relatedb_memory.store.RelateStore.open(config, embedding_dim=...) -> store
    store.run(cypher, **params) -> list[dict]   # safe from any thread
    store.close()                               # flush, then close on the owner thread
"""

from __future__ import annotations

import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from relatedb_memory import config as cfg

scenarios("features/store_schema.feature")

ROOT = Path(__file__).resolve().parents[2]
EMBEDDING_DIM = 4
WRITES_PER_THREAD = 10


# -- helpers ------------------------------------------------------------------


def store_path(home: Path) -> Path:
    return cfg.resolve_config(home, env_get={}.get).db_path


def open_store(home: Path):
    from relatedb_memory.store import RelateStore

    config = cfg.resolve_config(home, env_get={}.get)
    return RelateStore.open(config, embedding_dim=EMBEDDING_DIM)


def remember(store, key: str) -> None:
    store.run("MERGE (:Entity {key: $key})", key=key)


def remembered_keys(store) -> set[str]:
    return {row["key"] for row in store.run("MATCH (e:Entity) RETURN e.key AS key")}


def schema_of(store) -> tuple[set[str], dict[str, dict]]:
    constraints = {row["name"] for row in store.run("SHOW CONSTRAINTS")}
    indexes = {row["name"]: row for row in store.run("SHOW INDEXES")}
    return constraints, indexes


def in_threads(count: int, work) -> list[BaseException]:
    """Run ``work(i)`` on ``count`` simultaneous threads; return the errors raised."""
    barrier = threading.Barrier(count)

    def job(i: int):
        barrier.wait()
        work(i)

    with ThreadPoolExecutor(max_workers=count) as pool:
        futures = [pool.submit(job, i) for i in range(count)]
    return [err for f in futures if (err := f.exception()) is not None]


def write_and_read(store, prefix: str, i: int) -> None:
    for n in range(WRITES_PER_THREAD):
        remember(store, f"{prefix}-{i}-{n}")
        remembered_keys(store)


# -- shared scenario state ----------------------------------------------------


@pytest.fixture
def world(tmp_path):
    """Mutable state passed between steps; stores are closed on teardown."""
    state = SimpleNamespace(
        tmp_path=tmp_path,
        homes={},
        stores={},
        store=None,
        errors=[],
        schema=None,
        result=None,
    )
    yield state
    for store in [state.store, *state.stores.values()]:
        try:
            store and store.close()
        except Exception:
            pass


def new_profile(world, name: str = "default") -> Path:
    home = world.tmp_path / name
    home.mkdir()
    world.homes[name] = home
    return home


def default_home(world) -> Path:
    return world.homes["default"]


# -- Given --------------------------------------------------------------------


@given("a profile with no memory store")
def profile_without_store(world):
    home = new_profile(world)
    assert not store_path(home).exists()


@given("a populated store that has been closed")
def populated_closed_store(world):
    home = new_profile(world)
    store = open_store(home)
    remember(store, "ada")
    store.run(
        "MATCH (a:Entity {key: 'ada'}) CREATE (a)-[:SAID_IN]->(:Episode {id: 'ep-1'})"
    )
    world.schema = schema_of(store)
    store.close()


@given("an open store")
def an_open_store(world):
    world.store = open_store(new_profile(world))


@given(
    parsers.parse("an open store that {count:d} background threads have written to")
)
def store_written_by_threads(world, count):
    world.store = open_store(new_profile(world))
    errors = in_threads(count, lambda i: remember(world.store, f"bg-{i}"))
    assert errors == []
    world.written = {f"bg-{i}" for i in range(count)}


@given(
    parsers.parse(
        'two profiles "{first}" and "{second}", each with its own open store'
    )
)
def two_profiles_with_stores(world, first, second):
    for name in (first, second):
        world.stores[name] = open_store(new_profile(world, name))


# -- When ---------------------------------------------------------------------


@when("the profile's store is opened")
def open_profile_store(world):
    world.store = open_store(default_home(world))


@when("the store is opened again")
def reopen_store(world):
    world.store = open_store(default_home(world))


@when(
    parsers.parse("{count:d} threads each write {writes:d} facts and read at the same time")
)
def threads_write_and_read(world, count, writes):
    assert writes == WRITES_PER_THREAD
    world.errors = in_threads(count, lambda i: write_and_read(world.store, "t", i))
    world.expected_facts = count * writes


@when("the store is closed from a thread other than the one that opened it")
def close_from_other_thread(world):
    world.closer = threading.Thread(target=world.store.close)
    world.closer.start()
    world.closer.join(timeout=30)


@when(parsers.parse("both stores are written to by {count:d} threads at the same time"))
def both_stores_written(world, count):
    names = list(world.stores)

    def work(i: int) -> None:
        name = names[i % len(names)]
        write_and_read(world.stores[name], name, i)

    world.errors = in_threads(count, work)


@when("the store module is imported in a fresh interpreter")
def import_store_module(world):
    world.result = subprocess.run(
        [sys.executable, "-c", "from relatedb_memory.store import RelateStore"],
        cwd=ROOT,
        env={"HERMES_HOME": str(default_home(world)), "PATH": ""},
        capture_output=True,
        text=True,
    )


# -- Then ---------------------------------------------------------------------


@then(parsers.parse('the store file exists at "<hermes_home>/{name}"'))
def store_file_exists(world, name):
    home = default_home(world)
    assert store_path(home) == home / name
    assert store_path(home).exists()


@then("the uniqueness constraints entity_key, episode_id and fact_id exist")
def uniqueness_constraints_exist(world):
    constraints, _ = schema_of(world.store)
    assert {"entity_key", "episode_id", "fact_id"} <= constraints


@then("facts are indexed by slot with a range index")
def fact_slot_index(world):
    _, indexes = schema_of(world.store)
    assert indexes["fact_slot"]["type"] == "RANGE"
    assert indexes["fact_slot"]["properties"] == ["slot"]


@then("facts are indexed by embedding with a vector index scoped by closedAt")
def fact_embedding_index(world):
    _, indexes = schema_of(world.store)
    assert indexes["fact_embedding"]["type"] == "VECTOR"
    assert indexes["fact_embedding"]["properties"] == ["embedding", "closedAt"]


@then("opening did not fail on the existing constraints and indexes")
def opening_did_not_fail(world):
    assert world.store is not None


@then("the schema is unchanged")
def schema_unchanged(world):
    constraints, indexes = schema_of(world.store)
    before_constraints, before_indexes = world.schema
    assert (constraints, set(indexes)) == (before_constraints, set(before_indexes))


@then(parsers.parse('the entity "{key}" and its episode "{episode}" are preserved'))
def entity_and_episode_preserved(world, key, episode):
    assert remembered_keys(world.store) == {key}
    linked = world.store.run(
        "MATCH (:Entity {key: $key})-[:SAID_IN]->(ep:Episode) RETURN ep.id AS id",
        key=key,
    )
    assert [row["id"] for row in linked] == [episode]


@then("no thread raised an error")
def no_thread_raised(world):
    assert world.errors == []


@then(parsers.parse("all {count:d} facts are present"))
def all_facts_present(world, count):
    assert len(remembered_keys(world.store)) == count == world.expected_facts


@then("the close completes")
def close_completes(world):
    assert not world.closer.is_alive()


@then("the flushed writes survive a re-open")
def writes_survive_reopen(world):
    reopened = open_store(default_home(world))
    try:
        assert remembered_keys(reopened) == world.written
    finally:
        reopened.close()


@then("each store holds only its own profile's facts")
def stores_hold_only_own_facts(world):
    for name, store in world.stores.items():
        keys = remembered_keys(store)
        assert keys and all(key.startswith(f"{name}-") for key in keys)


@then("the two stores live in different files")
def stores_in_different_files(world):
    paths = {store_path(home) for home in world.homes.values()}
    assert len(paths) == len(world.homes)
    assert all(path.exists() for path in paths)


@then("the import succeeds")
def import_succeeds(world):
    assert world.result.returncode == 0, world.result.stderr


@then("no database file or directory is left behind")
def no_database_left(world):
    assert list(default_home(world).iterdir()) == []
