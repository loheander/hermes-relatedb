"""Unit and integration tests for the local vector embedding pipeline."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from relatedb_memory import config as cfg
from relatedb_memory.embedder import (
    DEFAULT_EMBEDDING_DIM,
    FakeEmbedder,
    FastEmbedEmbedder,
    format_vector,
)
from relatedb_memory.schema import DimensionMismatchError
from relatedb_memory.store import RelateStore


def test_fake_embedder_produces_exact_384_dim_float32_lists():
    embedder = FakeEmbedder(dim=DEFAULT_EMBEDDING_DIM)
    vecs = embedder.embed(["hello world", "another fact"])
    assert len(vecs) == 2
    for vec in vecs:
        assert isinstance(vec, list)
        assert len(vec) == 384
        assert all(isinstance(v, float) for v in vec)
    assert embedder.embed_one("hello world") == vecs[0]
    assert embedder.embed_query("hello world") == vecs[0]
    assert embedder.embed([]) == []


def test_format_vector_validates_dimension():
    arr = np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32)
    out = format_vector(arr, expected_dim=4)
    assert len(out) == 4
    assert all(isinstance(v, float) for v in out)
    with pytest.raises(ValueError, match="Expected embedding of dimension 8"):
        format_vector(arr, expected_dim=8)


def test_fastembed_embedder_lazy_loads_and_encodes():
    class StubTextEmbedding:
        def embed(self, documents):
            for _ in documents:
                yield np.ones(4, dtype=np.float32)

        def query_embed(self, query):
            for _ in query:
                yield np.full(4, 0.5, dtype=np.float32)

    with patch("relatedb_memory.embedder._load_fastembed_model", return_value=StubTextEmbedding()):
        embedder = FastEmbedEmbedder("stub/model")
        assert embedder.dim == 4
        vecs = embedder.embed(["a", "b"])
        assert len(vecs) == 2
        assert vecs[0] == [1.0, 1.0, 1.0, 1.0]
        qvec = embedder.embed_query("find a")
        assert qvec == [0.5, 0.5, 0.5, 0.5]


def test_importing_embedder_does_not_import_fastembed_eagerly():
    sys.modules.pop("relatedb_memory.embedder", None)
    was_fastembed_loaded = "fastembed" in sys.modules
    was_onnx_loaded = "onnxruntime" in sys.modules
    importlib.import_module("relatedb_memory.embedder")
    if not was_fastembed_loaded:
        assert "fastembed" not in sys.modules
    if not was_onnx_loaded:
        assert "onnxruntime" not in sys.modules


def test_relate_vector_roundtrip_and_search(tmp_path: Path):
    embedder = FakeEmbedder(dim=384)
    config = cfg.resolve_config(tmp_path, env_get={}.get)

    facts = [
        ("f1", "User prefers dark mode in editors"),
        ("f2", "User lives in Stockholm"),
    ]
    with RelateStore.open(config, embedding_dim=embedder.dim) as store:
        for fid, text in facts:
            vec = embedder.embed_one(text)
            store.run(
                "CREATE (:Fact {id: $id, text: $text, closedAt: null, embedding: vector($emb, $dim, FLOAT32)})",
                id=fid,
                text=text,
                emb=vec,
                dim=embedder.dim,
            )

        query_vec = embedder.embed_query("User prefers dark mode in editors")
        hits = store.run(
            "MATCH (f:Fact) "
            "SEARCH f IN (VECTOR INDEX fact_embedding FOR vector($q, $dim, FLOAT32) LIMIT 2) "
            "RETURN f.id AS id, f.text AS text",
            q=query_vec,
            dim=embedder.dim,
        )
        assert len(hits) >= 1
        assert hits[0]["id"] == "f1"


def test_dimension_mismatch_on_reopen_raises_clear_error(tmp_path: Path):
    config = cfg.resolve_config(tmp_path, env_get={}.get)
    with RelateStore.open(config, embedding_dim=384):
        pass

    with pytest.raises(DimensionMismatchError, match="384.*128"):
        RelateStore.open(config, embedding_dim=128)


def test_provider_uses_query_embeddings_for_recall_and_passage_for_writes(tmp_path: Path):
    import json
    from relatedb_memory.provider import RelateDBMemoryProvider

    calls: list[tuple[str, str]] = []

    class SpyEmbedder(FakeEmbedder):
        def embed_one(self, text: str) -> list[float]:
            calls.append(("embed_one", text))
            return super().embed_one(text)

        def embed_query(self, text: str) -> list[float]:
            calls.append(("embed_query", text))
            return FakeEmbedder.embed_one(self, text)

    embedder = SpyEmbedder(dim=16)
    config = cfg.resolve_config(tmp_path, env_get={}.get)
    provider = RelateDBMemoryProvider()
    provider.initialize("s1", hermes_home=str(tmp_path), agent_context="primary")
    provider._config = config
    provider._embedder = embedder

    try:
        provider.handle_tool_call(
            "relatedb_remember",
            {"text": "User drinks espresso", "slot": "drink"},
        )
        assert ("embed_one", "User drinks espresso") in calls
        assert not any(kind == "embed_query" for kind, _ in calls)

        calls.clear()
        res = json.loads(provider.handle_tool_call("relatedb_recall", {"query": "coffee preference"}))
        assert len(res["results"]) >= 1
        assert calls == [("embed_query", "coffee preference")]

        calls.clear()
        provider.prefetch("what coffee does user like?")
        assert calls == [("embed_query", "what coffee does user like?")]

        calls.clear()
        provider.sync_turn("I prefer pour-over now", "Noted.")
        provider.shutdown()
        assert any(kind == "embed_one" for kind, _ in calls)
        assert not any(kind == "embed_query" for kind, _ in calls)
    finally:
        provider.shutdown()

