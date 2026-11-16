"""Bi-temporal Entity-Episode-Fact graph schema for RelateDB.

See ADR-0001 and specs/memory-schema.md.
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


def ensure_schema(conn: Any, embedding_dim: int) -> None:
    """Apply all bi-temporal schema constraints and indexes idempotently."""
    for stmt in ddl_statements(embedding_dim):
        conn.execute(stmt)
