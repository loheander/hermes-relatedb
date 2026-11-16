"""Thread-affine RelateDB store engine with a bounded single-writer queue.

See ADR-0002, ADR-0005, and specs/memory-schema.md.
"""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any

from .config import RelateDBConfig
from .embedder import format_vector
from .schema import ensure_schema, validate_embedding_dim

EPISODE_KINDS: frozenset[str] = frozenset(
    {"message", "tool_call", "memory_write", "delegation", "pre_compress"}
)

DEFAULT_QUEUE_SIZE = 256
DEFAULT_ENQUEUE_TIMEOUT = 5.0
DEFAULT_CALL_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 3
_RETRY_BASE_DELAY_S = 0.01


class StoreClosedError(RuntimeError):
    """Raised when an operation is submitted to a closed store."""


class StoreQueueFullError(TimeoutError):
    """Raised when the bounded worker queue cannot accept work within its timeout."""


class StoreTimeoutError(TimeoutError):
    """Raised when a submitted store operation does not complete within its timeout."""


@dataclass(frozen=True)
class _WorkItem:
    fn: Callable[[Any], Any]
    future: Future[Any]


_CLOSE_SENTINEL = object()


def _spawn_worker(target: Callable[[], None], name: str) -> threading.Thread:
    """Spawn a worker thread, propagating Hermes contextvars when available."""
    try:
        from agent.memory_provider import spawn_context_thread
    except ImportError:
        thread = threading.Thread(target=target, name=name, daemon=True)
        thread.start()
        return thread
    return spawn_context_thread(target=target, name=name, daemon=True)


def _is_retryable(exc: BaseException) -> bool:
    return getattr(exc, "retryable", False) is True


class RelateStore:
    """Single-writer, thread-safe wrapper around a thread-affine ``relate`` connection."""

    def __init__(
        self,
        *,
        config: RelateDBConfig,
        embedding_dim: int,
        queue_size: int = DEFAULT_QUEUE_SIZE,
        enqueue_timeout: float = DEFAULT_ENQUEUE_TIMEOUT,
        call_timeout: float = DEFAULT_CALL_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        if queue_size < 1:
            raise ValueError(f"queue_size must be >= 1, got {queue_size!r}")
        if enqueue_timeout <= 0:
            raise ValueError(f"enqueue_timeout must be > 0, got {enqueue_timeout!r}")
        if call_timeout <= 0:
            raise ValueError(f"call_timeout must be > 0, got {call_timeout!r}")
        if max_retries < 0:
            raise ValueError(f"max_retries must be >= 0, got {max_retries!r}")

        self._config = config
        self._embedding_dim = validate_embedding_dim(embedding_dim)
        self._enqueue_timeout = enqueue_timeout
        self._call_timeout = call_timeout
        self._max_retries = max_retries

        self._queue: queue.Queue[Any] = queue.Queue(maxsize=queue_size)
        self._state_lock = threading.Lock()
        self._closed = False
        self._ready: Future[None] = Future()
        self._thread = _spawn_worker(
            self._worker_loop,
            name=f"relatedb-store-{config.db_path.name}",
        )

    @classmethod
    def open(
        cls,
        config: RelateDBConfig,
        *,
        embedding_dim: int,
        queue_size: int = DEFAULT_QUEUE_SIZE,
        enqueue_timeout: float = DEFAULT_ENQUEUE_TIMEOUT,
        call_timeout: float = DEFAULT_CALL_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> RelateStore:
        """Open the store on its dedicated worker thread and ensure schema DDL."""
        store = cls(
            config=config,
            embedding_dim=embedding_dim,
            queue_size=queue_size,
            enqueue_timeout=enqueue_timeout,
            call_timeout=call_timeout,
            max_retries=max_retries,
        )
        try:
            store._ready.result(timeout=call_timeout)
        except BaseException:
            store.close()
            raise
        return store

    @property
    def config(self) -> RelateDBConfig:
        return self._config

    @property
    def closed(self) -> bool:
        with self._state_lock:
            return self._closed

    def _worker_loop(self) -> None:
        import relate

        conn = None
        try:
            self._config.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = relate.connect(str(self._config.db_path))
            ensure_schema(conn, self._embedding_dim)
            self._ready.set_result(None)
        except BaseException as exc:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
            if not self._ready.done():
                self._ready.set_exception(exc)
            return

        try:
            while True:
                item = self._queue.get()
                if item is _CLOSE_SENTINEL:
                    break
                self._execute_item(conn, item)
        finally:
            try:
                flush = getattr(conn, "flush", None)
                if callable(flush):
                    flush()
            finally:
                conn.close()

    def _execute_item(self, conn: Any, item: _WorkItem) -> None:
        if item.future.cancelled():
            return
        for attempt in range(self._max_retries + 1):
            try:
                result = item.fn(conn)
            except BaseException as exc:
                if _is_retryable(exc) and attempt < self._max_retries:
                    time.sleep(_RETRY_BASE_DELAY_S * (2**attempt))
                    continue
                item.future.set_exception(exc)
                return
            item.future.set_result(result)
            return

    def submit(self, fn: Callable[[Any], Any], *, timeout: float | None = None) -> Any:
        """Run ``fn(conn)`` on the owning worker thread and return its result."""
        call_timeout = self._call_timeout if timeout is None else timeout
        future: Future[Any] = Future()
        with self._state_lock:
            if self._closed:
                raise StoreClosedError("RelateStore is closed")
            try:
                self._queue.put(_WorkItem(fn=fn, future=future), timeout=self._enqueue_timeout)
            except queue.Full as exc:
                raise StoreQueueFullError(
                    f"Store worker queue is full (maxsize={self._queue.maxsize})"
                ) from exc

        try:
            return future.result(timeout=call_timeout)
        except TimeoutError as exc:
            future.cancel()
            raise StoreTimeoutError(f"Store operation timed out after {call_timeout}s") from exc

    def run(self, cypher: str, /, **params: Any) -> list[dict[str, Any]]:
        """Execute a Cypher statement on the worker thread and return row dicts."""
        bound = params or None

        def _query(conn: Any) -> list[dict[str, Any]]:
            cursor = conn.execute(cypher, bound)
            return list(cursor)

        return self.submit(_query)

    def record_episode(
        self,
        *,
        episode_id: str,
        session: str,
        kind: str,
        at: str,
        text: str,
        mentions: Sequence[str] = (),
    ) -> None:
        """Idempotently upsert an ``:Episode`` and its ``:MENTIONS`` entity links."""
        if kind not in EPISODE_KINDS:
            raise ValueError(f"Unsupported episode kind {kind!r}; expected one of {sorted(EPISODE_KINDS)}")
        mention_keys = list(dict.fromkeys(mentions))

        def _op(conn: Any) -> None:
            conn.execute(
                "MERGE (ep:Episode {id: $episode_id}) "
                "ON CREATE SET ep.session = $session, ep.kind = $kind, ep.at = $at, ep.text = $text",
                {
                    "episode_id": episode_id,
                    "session": session,
                    "kind": kind,
                    "at": at,
                    "text": text,
                },
            )
            for key in mention_keys:
                conn.execute(
                    "MATCH (ep:Episode {id: $episode_id}) "
                    "MERGE (e:Entity {key: $key}) "
                    "MERGE (ep)-[:MENTIONS]->(e)",
                    {"episode_id": episode_id, "key": key},
                )

        self.submit(_op)

    def record_fact(
        self,
        *,
        fact_id: str,
        text: str,
        slot: str | None,
        valid_from: str,
        recorded_at: str,
        episode_id: str,
        about: Sequence[str] = (),
        embedding: Sequence[float] | None = None,
    ) -> None:
        """Idempotently upsert a ``:Fact``, link provenance, and supersede prior open slot facts."""
        vec = (
            format_vector(embedding, expected_dim=self._embedding_dim)
            if embedding is not None
            else None
        )
        about_keys = list(dict.fromkeys(about))

        def _op(conn: Any) -> None:
            if vec is not None:
                conn.execute(
                    "MERGE (f:Fact {id: $fact_id}) "
                    "ON CREATE SET f.text = $text, f.slot = $slot, f.validFrom = $valid_from, "
                    "f.recordedAt = $recorded_at, f.embedding = vector($embedding, $dim, FLOAT32)",
                    {
                        "fact_id": fact_id,
                        "text": text,
                        "slot": slot,
                        "valid_from": valid_from,
                        "recorded_at": recorded_at,
                        "embedding": vec,
                        "dim": self._embedding_dim,
                    },
                )
            else:
                conn.execute(
                    "MERGE (f:Fact {id: $fact_id}) "
                    "ON CREATE SET f.text = $text, f.slot = $slot, f.validFrom = $valid_from, "
                    "f.recordedAt = $recorded_at",
                    {
                        "fact_id": fact_id,
                        "text": text,
                        "slot": slot,
                        "valid_from": valid_from,
                        "recorded_at": recorded_at,
                    },
                )
            conn.execute(
                "MATCH (f:Fact {id: $fact_id}), (ep:Episode {id: $episode_id}) "
                "MERGE (f)-[:FROM]->(ep)",
                {"fact_id": fact_id, "episode_id": episode_id},
            )
            for key in about_keys:
                conn.execute(
                    "MATCH (f:Fact {id: $fact_id}) "
                    "MERGE (e:Entity {key: $key}) "
                    "MERGE (f)-[:ABOUT]->(e)",
                    {"fact_id": fact_id, "key": key},
                )
            if slot is not None:
                conn.execute(
                    "MATCH (new:Fact {id: $fact_id}), (old:Fact) "
                    "WHERE old.slot = $slot AND old <> new "
                    "AND old.closedAt IS NULL AND old.recordedAt <= new.recordedAt "
                    "SET old.validTo = new.validFrom, old.closedAt = new.recordedAt "
                    "MERGE (new)-[:SUPERSEDES]->(old)",
                    {"fact_id": fact_id, "slot": slot},
                )

        self.submit(_op)

    def retract_slot(self, *, slot: str, valid_to: str, closed_at: str) -> int:
        """Close the active fact in ``slot`` without deleting it; return count closed."""

        def _op(conn: Any) -> int:
            rows = list(
                conn.execute(
                    "MATCH (f:Fact {slot: $slot}) "
                    "WHERE f.closedAt IS NULL "
                    "SET f.validTo = $valid_to, f.closedAt = $closed_at "
                    "RETURN count(f) AS retracted",
                    {"slot": slot, "valid_to": valid_to, "closed_at": closed_at},
                )
            )
            return int(rows[0]["retracted"]) if rows else 0

        return self.submit(_op)

    def active_slots(self) -> list[str]:
        """Return distinct slots that currently have an open fact."""
        rows = self.run(
            "MATCH (f:Fact) "
            "WHERE f.closedAt IS NULL AND f.slot IS NOT NULL "
            "RETURN DISTINCT f.slot AS slot "
            "ORDER BY slot"
        )
        return [row["slot"] for row in rows]

    def close(self, timeout: float | None = None) -> None:
        """Flush pending operations and close the connection on its owning thread."""
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            self._queue.put(_CLOSE_SENTINEL)

        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=timeout)

    def __enter__(self) -> RelateStore:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()
