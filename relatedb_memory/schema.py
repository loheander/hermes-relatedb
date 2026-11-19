"""Bi-temporal Entity-Episode-Fact graph schema for RelateDB.

See ADR-0001 and tests/e2e/features/memory_schema.feature.
"""

from __future__ import annotations

from typing import Any

CONSTRAINTS: tuple[str, ...] = (
    "CREATE CONSTRAINT entity_key IF NOT EXISTS FOR (e:Entity) REQUIRE e.key IS UNIQUE",
    "CREATE CONSTRAINT episode_id IF NOT EXISTS FOR (ep:Episode) REQUIRE ep.id IS UNIQUE",
    "CREATE CONSTRAINT fact_id IF NOT EXISTS FOR (f:Fact) REQUIRE f.id IS UNIQUE",
)

RANGE_INDEXES: tuple[str, ...] = (
    "CREATE INDEX fact_slot IF NOT EXISTS FOR (f:Fact) ON (f.slot)",
)

VECTOR_INDEX_TEMPLATE = (
    "CREATE VECTOR INDEX fact_embedding IF NOT EXISTS "
    "FOR (f:Fact) ON (f.embedding) WITH [f.closedAt] "
    "OPTIONS {{indexConfig: {{`vector.dimensions`: {dim}, `vector.similarity_function`: 'cosine'}}}}"
)


#: Fact origin values (ADR-0007). Deliberate facts are always eligible in recall;
#: captured facts are capped at a share of ``k``.
DELIBERATE_ORIGINS: frozenset[str] = frozenset({"memory_write", "remember"})
CAPTURED_ORIGINS: frozenset[str] = frozenset({"turn", "pre_compress"})
FACT_ORIGINS: frozenset[str] = DELIBERATE_ORIGINS | CAPTURED_ORIGINS

#: ``Episode.kind`` -> ``Fact.origin``. Used to default and to backfill origins.
ORIGIN_BY_EPISODE_KIND: dict[str, str] = {
    "message": "turn",
    "delegation": "turn",
    "pre_compress": "pre_compress",
    "memory_write": "memory_write",
    "tool_call": "remember",
}


def origin_for_episode_kind(kind: str | None) -> str:
    """Return the fact origin implied by an episode kind (unknown kinds are deliberate)."""
    return ORIGIN_BY_EPISODE_KIND.get(kind or "", "remember")


class DimensionMismatchError(ValueError):
    """Raised when the configured embedding dimension differs from the store's vector index."""


def validate_embedding_dim(embedding_dim: int) -> int:
    """Validate that ``embedding_dim`` is a positive integer."""
    if isinstance(embedding_dim, bool) or not isinstance(embedding_dim, int) or embedding_dim < 1:
        raise ValueError(f"embedding_dim must be a positive integer, got {embedding_dim!r}")
    return embedding_dim


def ddl_statements(embedding_dim: int) -> tuple[str, ...]:
    """Return the idempotent DDL statements for the bi-temporal schema."""
    dim = validate_embedding_dim(embedding_dim)
    return (
        *CONSTRAINTS,
        *RANGE_INDEXES,
        VECTOR_INDEX_TEMPLATE.format(dim=dim),
    )


def get_vector_index_dim(conn: Any, index_name: str = "fact_embedding") -> int | None:
    """Return the configured ``vector.dimensions`` of ``index_name`` if present."""
    for row in conn.execute("SHOW INDEXES YIELD *"):
        if row.get("name") == index_name:
            config = (row.get("options") or {}).get("indexConfig") or {}
            dim = config.get("vector.dimensions")
            if dim is not None:
                return int(dim)
    return None


def ensure_schema(conn: Any, embedding_dim: int) -> None:
    """Apply all bi-temporal schema constraints and indexes idempotently."""
    dim = validate_embedding_dim(embedding_dim)
    existing_dim = get_vector_index_dim(conn)
    if existing_dim is not None and existing_dim != dim:
        raise DimensionMismatchError(
            f"Vector index 'fact_embedding' has dimension {existing_dim}, "
            f"but embedder/config specifies {dim}. Re-create the store or configure "
            f"embedding_model to match {existing_dim}-dim embeddings."
        )
    for stmt in ddl_statements(dim):
        conn.execute(stmt)
