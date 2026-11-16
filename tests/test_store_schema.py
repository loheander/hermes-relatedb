"""Unit tests for bi-temporal schema DDL and bounded store worker (#4)."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from relatedb_memory import config as cfg
from relatedb_memory.schema import ddl_statements, validate_embedding_dim
from relatedb_memory.store import (
    RelateStore,
    StoreClosedError,
    StoreQueueFullError,
)


def test_validate_embedding_dim_rejects_invalid():
    for bad in (0, -4, True, False, "4", 1.5):
        with pytest.raises(ValueError):
            validate_embedding_dim(bad)  # type: ignore[arg-type]
    assert validate_embedding_dim(4) == 4


def test_ddl_statements_include_all_constraints_and_indexes():
    stmts = ddl_statements(128)
    joined = "\n".join(stmts)
    assert "entity_key" in joined
    assert "episode_id" in joined
    assert "fact_id" in joined
    assert "fact_slot" in joined
    assert "fact_embedding" in joined
    assert "WITH [f.closedAt]" in joined
    assert "`vector.dimensions`: 128" in joined


def test_run_after_close_raises_and_close_is_idempotent(tmp_path: Path):
    config = cfg.resolve_config(tmp_path, env_get={}.get)
    with RelateStore.open(config, embedding_dim=4) as store:
        assert store.run("RETURN 1 AS x") == [{"x": 1}]
    assert store.closed
    store.close()  # idempotent
    with pytest.raises(StoreClosedError):
        store.run("RETURN 1 AS x")


def test_bounded_queue_raises_when_full(tmp_path: Path):
    config = cfg.resolve_config(tmp_path, env_get={}.get)
    gate = threading.Event()
    started = threading.Event()

    with RelateStore.open(
        config,
        embedding_dim=4,
        queue_size=1,
        enqueue_timeout=0.05,
        call_timeout=5.0,
    ) as store:
        def blocker(_conn):
            started.set()
            gate.wait(timeout=5.0)
            return "done"

        t1 = threading.Thread(target=lambda: store.submit(blocker))
        t2 = threading.Thread(target=lambda: store.run("RETURN 1 AS x"))
        t1.start()
        assert started.wait(timeout=2.0)
        t2.start()
        time.sleep(0.02)

        with pytest.raises(StoreQueueFullError):
            store.run("RETURN 2 AS y")

        gate.set()
        t1.join(timeout=2.0)
        t2.join(timeout=2.0)


def test_retryable_error_is_retried_until_success(tmp_path: Path):
    config = cfg.resolve_config(tmp_path, env_get={}.get)

    class RetryableConflict(RuntimeError):
        retryable = True

    attempts = {"count": 0}

    def flaky(conn):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RetryableConflict("transient write conflict")
        return list(conn.execute("RETURN 42 AS answer"))

    with RelateStore.open(config, embedding_dim=4, max_retries=3) as store:
        assert store.submit(flaky) == [{"answer": 42}]
        assert attempts["count"] == 3


def test_non_retryable_error_is_not_retried(tmp_path: Path):
    config = cfg.resolve_config(tmp_path, env_get={}.get)

    class FatalError(RuntimeError):
        retryable = False

    attempts = {"count": 0}

    def boom(_conn):
        attempts["count"] += 1
        raise FatalError("permanent failure")

    with RelateStore.open(config, embedding_dim=4, max_retries=3) as store:
        with pytest.raises(FatalError):
            store.submit(boom)
        assert attempts["count"] == 1
