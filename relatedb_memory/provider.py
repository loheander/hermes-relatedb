"""RelateDB memory provider entry point."""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import threading
import uuid
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config as _config
from .embedder import Embedder, get_embedder
from .store import RelateStore


try:  # Hermes runtime is optional at import time.
    from agent.memory_provider import (
        MemoryProvider as _Base,
        RecallStatus,
        is_trivial_prompt as _hermes_is_trivial_prompt,
        spawn_context_thread as _hermes_spawn_context_thread,
    )
except ImportError:  # pragma: no cover - exercised when Hermes is absent

    @dataclass(frozen=True)
    class RecallStatus:  # type: ignore[no-redef]
        provider_label: str
        count: int

    _hermes_is_trivial_prompt = None
    _hermes_spawn_context_thread = None

    class _Base(ABC):  # type: ignore[no-redef]
        """Minimal stand-in so the package imports without Hermes Agent."""

        @property
        @abstractmethod
        def name(self) -> str: ...

        @abstractmethod
        def is_available(self) -> bool: ...

        @abstractmethod
        def initialize(self, session_id: str, **kwargs: Any) -> None: ...

        @abstractmethod
        def get_tool_schemas(self) -> list[dict[str, Any]]: ...


_TRIVIAL_TOKENS = frozenset(
    {
        "ok",
        "okay",
        "k",
        "yes",
        "no",
        "thanks",
        "thank you",
        "thx",
        "ty",
        "hi",
        "hello",
        "hey",
        "bye",
        "sure",
        "cool",
        "great",
        "nice",
        "got it",
    }
)

_STATIC_SYSTEM_PROMPT = (
    "RelateDB bi-temporal memory is active. Use `relatedb_remember` to store durable "
    "facts, `relatedb_recall` to search active memories, `relatedb_as_of` to audit "
    "historical state, and `relatedb_provenance` to inspect supporting episodes."
)


_NON_PRIMARY_CONTEXTS = frozenset({"subagent", "cron", "flush"})

_MUTATING_CYPHER_RE = re.compile(
    r"\b(?:CREATE|MERGE|SET|DELETE|DETACH|REMOVE|DROP|LOAD)\b",
    re.IGNORECASE,
)


def _strip_cypher_literals_and_comments(query: str) -> str:
    # Remove single/double-quoted literals, backticked identifiers, and // or /* */ comments.
    cleaned = re.sub(r"//[^\n]*", " ", query)
    cleaned = re.sub(r"/\*.*?\*/", " ", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"'(?:\\.|[^'\\])*'", "''", cleaned)
    cleaned = re.sub(r'"(?:\\.|[^"\\])*"', '""', cleaned)
    cleaned = re.sub(r"`(?:\\.|[^`\\])*`", "``", cleaned)
    return cleaned


def _validate_read_only_cypher(query: str) -> None:
    if not query or not query.strip():
        raise ValueError("Cypher query must not be empty")
    stripped = _strip_cypher_literals_and_comments(query)
    if ";" in stripped.strip().rstrip(";"):
        raise ValueError("Multiple Cypher statements are not allowed")
    match = _MUTATING_CYPHER_RE.search(stripped)
    if match:
        raise ValueError(f"Mutating Cypher keyword {match.group(0).upper()!r} is not allowed in read-only mode")


_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "relatedb_remember",
            "description": "Store or update a durable fact in RelateDB memory, superseding any open fact in the same slot.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The fact text to remember."},
                    "slot": {"type": "string", "description": "Unique slot key (e.g. 'project/owner')."},
                    "about": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional entity keys (e.g. note_id, citation_key, project_slug).",
                    },
                    "valid_from": {"type": "string", "description": "Optional ISO-8601 valid-from timestamp."},
                },
                "required": ["text", "slot"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "relatedb_forget",
            "description": "Close an active fact in a slot or by fact_id without deleting history.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slot": {"type": "string", "description": "Slot to retract."},
                    "fact_id": {"type": "string", "description": "Specific fact ID to close."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "relatedb_recall",
            "description": "Search active memories semantically using pre-filtered vector recall.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language query."},
                    "k": {"type": "integer", "description": "Maximum number of results.", "default": 8},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "relatedb_as_of",
            "description": "Audit bi-temporal state for a slot at timestamp 'on' (trueOn vs believedOn).",
            "parameters": {
                "type": "object",
                "properties": {
                    "slot": {"type": "string", "description": "Slot to inspect."},
                    "on": {"type": "string", "description": "ISO-8601 timestamp to query."},
                },
                "required": ["slot", "on"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "relatedb_provenance",
            "description": "Trace the supersession lineage and supporting episodes for a slot or fact_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "slot": {"type": "string", "description": "Slot to trace."},
                    "fact_id": {"type": "string", "description": "Fact ID to trace."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "relatedb_cypher",
            "description": "Execute a read-only Cypher query against the RelateDB memory graph.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Read-only Cypher query."},
                    "params": {"type": "object", "description": "Optional query parameters."},
                },
                "required": ["query"],
            },
        },
    },
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_trivial_prompt(query: str) -> bool:
    if _hermes_is_trivial_prompt is not None:
        return bool(_hermes_is_trivial_prompt(query))
    stripped = query.strip()
    if not stripped or stripped.startswith("/"):
        return True
    normalized = stripped.rstrip(".!?,").lower()
    return normalized in _TRIVIAL_TOKENS


def _spawn_bg(target: Any, name: str) -> threading.Thread:
    if _hermes_spawn_context_thread is not None:
        thread = _hermes_spawn_context_thread(target=target, name=name, daemon=True)
    else:
        thread = threading.Thread(target=target, name=name, daemon=True)
    thread.start()
    return thread


def _format_recall_block(hits: list[dict[str, Any]]) -> str:
    lines = ["[RelateDB Memory]"]
    for hit in hits:
        line = f"- {hit['text']}"
        meta: list[str] = []
        if hit.get("slot"):
            meta.append(f"slot={hit['slot']}")
        if hit.get("about"):
            meta.append(f"about={','.join(hit['about'])}")
        learned = hit.get("learnedFrom") or {}
        if learned.get("kind"):
            meta.append(f"from={learned['kind']}")
        if hit.get("replaced"):
            meta.append(f"replaces={'; '.join(hit['replaced'])}")
        if meta:
            line += f" ({'; '.join(meta)})"
        lines.append(line)
    return "\n".join(lines)


class RelateDBMemoryProvider(_Base):
    """Per-instance state only; no module-level mutable profile state."""

    def __init__(self) -> None:
        self._session_id: str | None = None
        self._agent_context: str = "primary"
        self._init_kwargs: dict[str, Any] = {}
        self._config: _config.RelateDBConfig | None = None
        self._embedder: Embedder | None = None
        self._store: RelateStore | None = None
        self._prefetch_lock = threading.Lock()
        self._sync_lock = threading.Lock()
        self._store_lock = threading.Lock()
        self._prefetch_thread: threading.Thread | None = None
        self._sync_threads: list[threading.Thread] = []
        self._prefetch_cache: tuple[str, list[dict[str, Any]]] | None = None
        self._last_recall_status: RecallStatus | None = None

    @property
    def name(self) -> str:
        return _config.PROVIDER_NAME

    def is_available(self) -> bool:
        """True when the ``relate`` module or CLI is present; never imports it or touches the network."""
        return self._relate_installed()

    @staticmethod
    def _relate_installed() -> bool:
        try:
            if importlib.util.find_spec("relate") is not None:
                return True
        except (ImportError, ValueError):
            pass
        return shutil.which("relate") is not None

    def unavailable_reason(self) -> str:
        if self._relate_installed():
            return ""
        return "relate-db is not installed: run `pip install relate-db` (or `uv add relate-db`) in the Hermes environment."

    @property
    def config(self) -> _config.RelateDBConfig:
        if self._config is None:
            raise RuntimeError("relatedb provider not initialized with hermes_home")
        return self._config

    def _ensure_store(self) -> RelateStore:
        with self._store_lock:
            if self._store is None:
                if self._config is None:
                    raise RuntimeError("relatedb store not initialized with hermes_home")
                embedder = self._embedder
                if embedder is None:
                    embedder = get_embedder(self._config.embedding_model)
                    self._embedder = embedder
                self._store = RelateStore.open(self._config, embedding_dim=embedder.dim)
            return self._store

    @property
    def store(self) -> RelateStore:
        return self._ensure_store()

    def initialize(self, session_id: str, **kwargs: Any) -> None:
        self._session_id = session_id
        self._agent_context = str(kwargs.get("agent_context", "primary"))
        self._init_kwargs = dict(kwargs)
        hermes_home = kwargs.get("hermes_home")
        embedder = kwargs.get("embedder")
        # Bind strictly to the profile Hermes passes in; never fall back to ~/.hermes.
        self._config = _config.resolve_config(hermes_home) if hermes_home else None
        self._embedder = embedder
        if self._config is not None and self._embedder is None:
            self._embedder = get_embedder(self._config.embedding_model)

    def system_prompt_block(self) -> str:
        return _STATIC_SYSTEM_PROMPT

    def queue_prefetch(self, query: str, session_id: str | None = None) -> None:
        if self._config is None:
            return
        if _is_trivial_prompt(query):
            with self._prefetch_lock:
                self._prefetch_cache = None
            return

        store = self._ensure_store()
        embedder = self._embedder
        if embedder is None:
            return
        top_k = self._config.prefetch_top_k

        def _worker() -> None:
            try:
                vec = embedder.embed_one(query)
                hits = store.vector_recall(vec, k=top_k)
            except Exception:
                return
            with self._prefetch_lock:
                self._prefetch_cache = (query, hits)

        with self._prefetch_lock:
            self._prefetch_thread = _spawn_bg(_worker, name="relatedb-prefetch")

    def flush_prefetch(self, timeout: float | None = 5.0) -> None:
        with self._prefetch_lock:
            thread = self._prefetch_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)

    def prefetch(self, query: str, session_id: str | None = None) -> str:
        if _is_trivial_prompt(query):
            self._last_recall_status = None
            return ""
        if self._config is None:
            self._last_recall_status = None
            return ""

        store = self._ensure_store()
        embedder = self._embedder
        if embedder is None:
            self._last_recall_status = None
            return ""

        self.flush_prefetch(timeout=2.0)
        hits: list[dict[str, Any]] | None = None
        with self._prefetch_lock:
            if self._prefetch_cache is not None and self._prefetch_cache[0] == query:
                hits = self._prefetch_cache[1]
                self._prefetch_cache = None

        if hits is None:
            vec = embedder.embed_one(query)
            hits = store.vector_recall(vec, k=self._config.prefetch_top_k)

        if not hits:
            self._last_recall_status = None
            return ""

        self._last_recall_status = RecallStatus(provider_label=_config.PROVIDER_NAME, count=len(hits))
        return _format_recall_block(hits)

    def recall_status(self) -> RecallStatus | None:
        return self._last_recall_status

    def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str | None = None,
        agent_context: str | None = None,
        messages: Any = None,
        turn_author: str | None = None,
    ) -> None:
        ctx = agent_context if agent_context is not None else self._agent_context
        if ctx in _NON_PRIMARY_CONTEXTS or ctx != "primary":
            return
        if self._config is None or not self._config.auto_extract:
            return
        if not (user_content or "").strip() and not (assistant_content or "").strip():
            return

        store = self._ensure_store()
        embedder = self._embedder
        if embedder is None:
            return
        active_session = session_id or self._session_id or "default"
        now = _utc_now_iso()
        uid = uuid.uuid4().hex[:12]
        combined = f"User: {user_content}\nAssistant: {assistant_content}".strip()

        def _worker() -> None:
            _ = store.active_slots()
            store.record_episode(
                episode_id=f"ep-{uid}",
                session=active_session,
                kind="message",
                at=now,
                text=combined,
            )
            store.record_fact(
                fact_id=f"f-{uid}",
                text=user_content.strip() or assistant_content.strip(),
                slot=f"turn/{active_session}/{uid}",
                valid_from=now,
                recorded_at=now,
                episode_id=f"ep-{uid}",
                embedding=embedder.embed_one(combined),
            )

        thread = _spawn_bg(_worker, name="relatedb-sync-turn")
        with self._sync_lock:
            self._sync_threads = [t for t in self._sync_threads if t.is_alive()]
            self._sync_threads.append(thread)

    def flush_sync(self, timeout: float | None = 5.0) -> None:
        with self._sync_lock:
            threads = list(self._sync_threads)
            self._sync_threads.clear()
        for thread in threads:
            if thread.is_alive():
                thread.join(timeout=timeout)

    def on_memory_write(
        self,
        action: str,
        target: str = "memory/default",
        content: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if self._config is None:
            return
        store = self._ensure_store()
        embedder = self._embedder
        slot = target or "memory/default"
        now = _utc_now_iso()
        uid = uuid.uuid4().hex[:12]
        active_session = self._session_id or "default"

        store.record_episode(
            episode_id=f"ep-mw-{uid}",
            session=active_session,
            kind="memory_write",
            at=now,
            text=f"{action} {slot}: {content}".strip(),
        )
        normalized_action = action.strip().lower()
        if normalized_action in {"add", "replace", "patch"}:
            vec = embedder.embed_one(content) if embedder is not None else None
            store.record_fact(
                fact_id=f"f-mw-{uid}",
                text=content,
                slot=slot,
                valid_from=now,
                recorded_at=now,
                episode_id=f"ep-mw-{uid}",
                embedding=vec,
            )
        elif normalized_action == "remove":
            store.retract_slot(slot=slot, valid_to=now, closed_at=now)
        else:
            raise ValueError(f"Unsupported memory_write action: {action!r}")

    def on_pre_compress(self, messages: Sequence[dict[str, Any]]) -> None:
        self.flush_sync(timeout=2.0)
        if self._config is None or not messages:
            return
        store = self._ensure_store()
        embedder = self._embedder
        now = _utc_now_iso()
        uid = uuid.uuid4().hex[:12]
        active_session = self._session_id or "default"
        summary_lines = [
            f"{m.get('role', 'unknown')}: {m.get('content', '')}"
            for m in messages
            if m.get("content")
        ]
        if not summary_lines:
            return
        summary = "\n".join(summary_lines)
        store.record_episode(
            episode_id=f"ep-pc-{uid}",
            session=active_session,
            kind="pre_compress",
            at=now,
            text=summary,
        )
        vec = embedder.embed_one(summary) if embedder is not None else None
        store.record_fact(
            fact_id=f"f-pc-{uid}",
            text=summary_lines[0],
            slot=f"pre_compress/{active_session}/{uid}",
            valid_from=now,
            recorded_at=now,
            episode_id=f"ep-pc-{uid}",
            embedding=vec,
        )

    def on_session_switch(self, new_session_id: str, *, reset: bool = False) -> None:
        if reset:
            self.flush_sync(timeout=2.0)
            self.flush_prefetch(timeout=2.0)
            with self._prefetch_lock:
                self._prefetch_cache = None
            self._last_recall_status = None
        self._session_id = new_session_id

    def on_delegation(
        self,
        task: str,
        result: str,
        *,
        child_session_id: str | None = None,
    ) -> None:
        if self._config is None:
            return
        store = self._ensure_store()
        now = _utc_now_iso()
        uid = uuid.uuid4().hex[:12]
        active_session = self._session_id or "default"
        mentions = [child_session_id] if child_session_id else []
        store.record_episode(
            episode_id=f"ep-del-{uid}",
            session=active_session,
            kind="delegation",
            at=now,
            text=f"Task: {task}\nResult: {result}",
            mentions=mentions,
        )

    def shutdown(self) -> None:
        self.flush_prefetch(timeout=2.0)
        self.flush_sync(timeout=2.0)
        if self._store is not None:
            self._store.close()
            self._store = None

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return list(_TOOL_SCHEMAS)

    def handle_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any] | str,
        **kwargs: Any,
    ) -> str:
        args = json.loads(arguments) if isinstance(arguments, str) else dict(arguments)
        store = self._ensure_store()
        embedder = self._embedder
        now = _utc_now_iso()
        active_session = self._session_id or "default"

        if tool_name == "relatedb_remember":
            text = str(args["text"])
            slot = str(args["slot"])
            about = list(args.get("about") or [])
            valid_from = str(args.get("valid_from") or now)
            uid = uuid.uuid4().hex[:12]
            ep_id = f"ep-tool-{uid}"
            fact_id = f"f-tool-{uid}"
            store.record_episode(
                episode_id=ep_id,
                session=active_session,
                kind="tool_call",
                at=now,
                text=text,
                mentions=about,
            )
            vec = embedder.embed_one(text) if embedder is not None else None
            store.record_fact(
                fact_id=fact_id,
                text=text,
                slot=slot,
                valid_from=valid_from,
                recorded_at=now,
                episode_id=ep_id,
                about=about,
                embedding=vec,
            )
            return json.dumps({"status": "ok", "fact_id": fact_id, "slot": slot})

        if tool_name == "relatedb_forget":
            slot = args.get("slot")
            fact_id = args.get("fact_id")
            if slot:
                count = store.retract_slot(slot=str(slot), valid_to=now, closed_at=now)
                return json.dumps({"status": "ok", "retracted": count, "slot": slot})
            if fact_id:
                rows = store.run(
                    "MATCH (f:Fact {id: $fid}) WHERE f.closedAt IS NULL "
                    "SET f.validTo = $now, f.closedAt = $now RETURN count(f) AS c",
                    fid=str(fact_id),
                    now=now,
                )
                return json.dumps({"status": "ok", "retracted": rows[0]["c"] if rows else 0})
            return json.dumps({"error": "Either 'slot' or 'fact_id' is required"})

        if tool_name == "relatedb_recall":
            query = str(args["query"])
            k = int(args.get("k") or (self._config.prefetch_top_k if self._config else 8))
            if embedder is None:
                return json.dumps({"results": []})
            vec = embedder.embed_one(query)
            hits = store.vector_recall(vec, k=k)
            return json.dumps({"results": hits}, default=str)

        if tool_name == "relatedb_as_of":
            slot = str(args["slot"])
            on = str(args["on"])
            rows = store.run(
                "MATCH (f:Fact {slot: $slot}) "
                "RETURN f.id AS id, f.text AS text, f.validFrom AS validFrom, "
                "f.validTo AS validTo, f.recordedAt AS recordedAt, f.closedAt AS closedAt "
                "ORDER BY f.recordedAt ASC",
                slot=slot,
            )
            true_on = [
                r["text"]
                for r in rows
                if r["validFrom"] <= on and (r["validTo"] is None or on < r["validTo"])
            ]
            believed_on = [
                r["text"]
                for r in rows
                if r["recordedAt"] <= on and (r["closedAt"] is None or on < r["closedAt"])
            ]
            return json.dumps(
                {
                    "slot": slot,
                    "on": on,
                    "trueOn": true_on,
                    "believedOn": believed_on,
                    "timeline": rows,
                },
                default=str,
            )

        if tool_name == "relatedb_provenance":
            slot = args.get("slot")
            fact_id = args.get("fact_id")
            if slot:
                rows = store.run(
                    "MATCH (f:Fact {slot: $slot})-[:FROM]->(ep:Episode) "
                    "RETURN f.id AS id, f.text AS text, f.slot AS slot, "
                    "f.validFrom AS validFrom, f.validTo AS validTo, "
                    "f.recordedAt AS recordedAt, f.closedAt AS closedAt, "
                    "ep.id AS ep_id, ep.kind AS ep_kind, ep.session AS ep_session, "
                    "ep.at AS ep_at, ep.text AS ep_text, "
                    "COLLECT { MATCH (f)-[:SUPERSEDES]->(old:Fact) RETURN old.id } AS supersedes "
                    "ORDER BY f.recordedAt DESC",
                    slot=str(slot),
                )
            elif fact_id:
                rows = store.run(
                    "MATCH (f:Fact {id: $fid})-[:FROM]->(ep:Episode) "
                    "RETURN f.id AS id, f.text AS text, f.slot AS slot, "
                    "f.validFrom AS validFrom, f.validTo AS validTo, "
                    "f.recordedAt AS recordedAt, f.closedAt AS closedAt, "
                    "ep.id AS ep_id, ep.kind AS ep_kind, ep.session AS ep_session, "
                    "ep.at AS ep_at, ep.text AS ep_text, "
                    "COLLECT { MATCH (f)-[:SUPERSEDES]->(old:Fact) RETURN old.id } AS supersedes",
                    fid=str(fact_id),
                )
            else:
                return json.dumps({"error": "Either 'slot' or 'fact_id' is required"})

            lineage = [
                {
                    "id": r["id"],
                    "text": r["text"],
                    "slot": r["slot"],
                    "validFrom": r["validFrom"],
                    "validTo": r["validTo"],
                    "recordedAt": r["recordedAt"],
                    "closedAt": r["closedAt"],
                    "supersedes": r["supersedes"],
                    "episode": {
                        "id": r["ep_id"],
                        "kind": r["ep_kind"],
                        "session": r["ep_session"],
                        "at": r["ep_at"],
                        "text": r["ep_text"],
                    },
                }
                for r in rows
            ]
            return json.dumps({"lineage": lineage}, default=str)

        if tool_name == "relatedb_cypher":
            query = str(args["query"])
            params = args.get("params") or {}
            try:
                _validate_read_only_cypher(query)
                rows = store.run(query, **params)
            except Exception as exc:
                return json.dumps({"error": str(exc)})
            return json.dumps({"rows": rows}, default=str)

        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    # -- setup / dashboard configuration --

    def get_config_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "key": "snapshot_format",
                "description": "Store format: rl (single file), parquet or json (directory)",
                "default": _config.DEFAULT_SNAPSHOT_FORMAT,
                "choices": list(_config.SNAPSHOT_FORMATS),
            },
            {
                "key": "db_path",
                "description": "Store path (directory for parquet/json, .rl file for rl)",
                "default": "",
                "default_from": {
                    "field": "snapshot_format",
                    "map": {
                        "parquet": "memory/",
                        "json": "memory/",
                        "rl": "memory.rl",
                    },
                },
            },
            {
                "key": "embedding_model",
                "description": "model2vec embedding model",
                "default": _config.DEFAULT_EMBEDDING_MODEL,
            },
            {
                "key": "prefetch_top_k",
                "description": "Maximum facts injected per turn",
                "default": _config.DEFAULT_PREFETCH_TOP_K,
                "type": "integer",
                "minimum": 1,
            },
            {
                "key": "auto_extract",
                "description": "Extract facts from turns in the background",
                "default": _config.DEFAULT_AUTO_EXTRACT,
                "type": "boolean",
            },
        ]

    def save_config(self, values: dict[str, Any], hermes_home: str) -> None:
        _config.write_yaml_section(hermes_home, values)

    def read_config_fields(self, hermes_home: str) -> dict[str, Any]:
        stored = _config.read_yaml_section(hermes_home)
        values = {k: v for k, v in stored.items() if k in _config.ENV_VARS}
        resolved = _config.resolve_config(hermes_home)
        return {"values": values, "placeholders": {"db_path": str(resolved.db_path)}}

    def write_config_fields(self, values: dict[str, Any], hermes_home: str) -> None:
        _config.write_yaml_section(hermes_home, values)

    # -- backup and profile lifecycle (work on an uninitialized instance) --

    def backup_paths(self) -> list[str]:
        """Store path when it lives outside HERMES_HOME; paths inside it are backed up by Hermes itself."""
        cfg = self._config
        if cfg is None:
            return []
        try:
            cfg.db_path.resolve().relative_to(cfg.hermes_home.resolve())
        except ValueError:
            return [str(cfg.db_path)]
        return []

    def on_profile_created(self, profile_name: str, hermes_home: str) -> None:
        cfg = _config.resolve_config(hermes_home)
        target = cfg.db_path if cfg.snapshot_format in _config.DIRECTORY_FORMATS else cfg.db_path.parent
        Path(target).mkdir(parents=True, exist_ok=True)

    def on_profile_renamed(self, old_name: str, new_name: str, hermes_home: str) -> None:
        """Nothing to re-key: the store path is derived from ``hermes_home``, not the profile name."""
