"""Unit and integration tests for the local vector embedding pipeline (#5)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from relatedb_memory import config as cfg
from relatedb_memory.embedder import (
    DEFAULT_EMBEDDING_DIM,
    FakeEmbedder,
    Model2VecEmbedder,
    format_vector,
)
from relatedb_memory.schema import DimensionMismatchError
from relatedb_memory.store import RelateStore


def test_fake_embedder_produces_exact_256_dim_float32_lists():
    embedder = FakeEmbedder(dim=DEFAULT_EMBEDDING_DIM)
    vecs = embedder.embed(["hello world", "another fact"])
    assert len(vecs) == 2
    for vec in vecs:
        assert isinstance(vec, list)
        assert len(vec) == 256
        assert all(isinstance(v, float) for v in vec)
    assert embedder.embed_one("hello world") == vecs[0]
    assert embedder.embed([]) == []


def test_format_vector_validates_dimension():
    arr = np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32)
    out = format_vector(arr, expected_dim=4)
    assert len(out) == 4
    assert all(isinstance(v, float) for v in out)
    with pytest.raises(ValueError, match="Expected embedding of dimension 8"):
        format_vector(arr, expected_dim=8)


def test_model2vec_embedder_lazy_loads_and_encodes():
    class StubModel:
        dim = 4

        def encode(self, sentences, show_progress_bar=False):
            assert show_progress_bar is False
            return np.ones((len(sentences), 4), dtype=np.float32)

    with patch("relatedb_memory.embedder._load_static_model", return_value=StubModel()):
        embedder = Model2VecEmbedder("stub/model")
        assert embedder.dim == 4
        vecs = embedder.embed(["a", "b"])
        assert len(vecs) == 2
        assert vecs[0] == [1.0, 1.0, 1.0, 1.0]


def test_importing_embedder_does_not_import_model2vec_eagerly():
    sys.modules.pop("relatedb_memory.embedder", None)
    was_loaded = "model2vec" in sys.modules
    importlib.import_module("relatedb_memory.embedder")
    if not was_loaded:
        assert "model2vec" not in sys.modules


def test_relate_vector_roundtrip_and_search(tmp_path: Path):
    embedder = FakeEmbedder(dim=256)
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

        query_vec = embedder.embed_one("User prefers dark mode in editors")
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
    with RelateStore.open(config, embedding_dim=256):
        pass

    with pytest.raises(DimensionMismatchError, match="256.*128"):
        RelateStore.open(config, embedding_dim=128)
