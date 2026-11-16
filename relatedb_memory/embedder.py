"""Local vector embedding pipeline using model2vec.

See ADR-0003. This is the only module in ``relatedb_memory`` that imports
``model2vec``.
"""

from __future__ import annotations

import hashlib
import math
import struct
import threading
from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from .config import DEFAULT_EMBEDDING_MODEL

DEFAULT_EMBEDDING_DIM = 256

_MODEL_LOCK = threading.Lock()
_MODEL_CACHE: dict[str, Any] = {}
_EMBEDDER_CACHE: dict[str, Model2VecEmbedder] = {}


@runtime_checkable
class Embedder(Protocol):
    """Protocol implemented by local and test embedders."""

    @property
    def dim(self) -> int: ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_one(self, text: str) -> list[float]: ...


def _warmup_numpy() -> Any:
    """Import numpy via Hermes's warm-up contract when available."""
    try:
        from agent.memory_provider import import_memory_provider_module
    except ImportError:
        import numpy as np

        return np
    return import_memory_provider_module("numpy")


def format_vector(values: Sequence[float] | Any, expected_dim: int | None = None) -> list[float]:
    """Convert an embedding array/sequence to a ``FLOAT32``-compatible ``list[float]``."""
    if hasattr(values, "tolist"):
        raw = values.tolist()
    else:
        raw = list(values)
    # Round-trip through float32 so values match Relate FLOAT32 storage precision.
    vec = [struct.unpack("!f", struct.pack("!f", float(x)))[0] for x in raw]
    if expected_dim is not None and len(vec) != expected_dim:
        raise ValueError(f"Expected embedding of dimension {expected_dim}, got {len(vec)}")
    return vec


def _load_static_model(model_name: str) -> Any:
    with _MODEL_LOCK:
        cached = _MODEL_CACHE.get(model_name)
        if cached is not None:
            return cached
        _warmup_numpy()
        from model2vec import StaticModel

        model = StaticModel.from_pretrained(model_name)
        _MODEL_CACHE[model_name] = model
        return model


class Model2VecEmbedder:
    """Lazy, thread-safe wrapper around ``model2vec.StaticModel``."""

    def __init__(self, model_name: str = DEFAULT_EMBEDDING_MODEL) -> None:
        self.model_name = model_name
        self._dim: int | None = None

    @property
    def dim(self) -> int:
        if self._dim is None:
            model = _load_static_model(self.model_name)
            dim = getattr(model, "dim", None)
            if dim is None:
                sample = model.encode(["dimension probe"], show_progress_bar=False)
                dim = len(sample[0])
            self._dim = int(dim)
        return self._dim

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        items = list(texts)
        if not items:
            return []
        model = _load_static_model(self.model_name)
        encoded = model.encode(items, show_progress_bar=False)
        expected = self.dim
        return [format_vector(row, expected_dim=expected) for row in encoded]

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]


class FakeEmbedder:
    """Deterministic, zero-network embedder for unit and integration tests."""

    def __init__(self, dim: int = DEFAULT_EMBEDDING_DIM) -> None:
        if isinstance(dim, bool) or not isinstance(dim, int) or dim < 1:
            raise ValueError(f"dim must be a positive integer, got {dim!r}")
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed_one(text) for text in texts]

    def embed_one(self, text: str) -> list[float]:
        raw: list[float] = []
        counter = 0
        while len(raw) < self._dim:
            digest = hashlib.sha256(f"{counter}:{text}".encode("utf-8")).digest()
            for i in range(0, len(digest), 4):
                if len(raw) >= self._dim:
                    break
                word = int.from_bytes(digest[i : i + 4], "big", signed=False)
                raw.append((word / 0xFFFFFFFF) * 2.0 - 1.0)
            counter += 1
        norm = math.sqrt(sum(v * v for v in raw)) or 1.0
        return format_vector([v / norm for v in raw], expected_dim=self._dim)


def get_embedder(model_name: str = DEFAULT_EMBEDDING_MODEL) -> Model2VecEmbedder:
    """Return a cached ``Model2VecEmbedder`` for ``model_name``."""
    with _MODEL_LOCK:
        embedder = _EMBEDDER_CACHE.get(model_name)
        if embedder is None:
            embedder = Model2VecEmbedder(model_name)
            _EMBEDDER_CACHE[model_name] = embedder
        return embedder
