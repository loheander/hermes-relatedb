#!/usr/bin/env python3
"""Standalone migration script to re-embed existing RelateDB memory stores.

Re-embeds existing 256-dim ``model2vec`` stores (``.rl``, ``parquet``, or
``json``) to 384-dim ``BAAI/bge-small-en-v1.5`` via ``fastembed`` without
requiring ``model2vec`` as a dependency.
"""

from __future__ import annotations

import argparse
import datetime as dt
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import relate

from relatedb_memory.config import DEFAULT_EMBEDDING_MODEL
from relatedb_memory.embedder import DEFAULT_EMBEDDING_DIM, Embedder, get_embedder
from relatedb_memory.schema import ensure_schema, get_vector_index_dim


@dataclass(frozen=True)
class MigrationResult:
    """Summary of a store re-embedding run."""

    db_path: Path
    current_dim: int | None
    target_dim: int
    fact_count: int
    updated_count: int
    backup_path: Path | None
    dry_run: bool


def _create_backup(db_path: Path) -> Path:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = db_path.with_name(f"{db_path.name}.bak-{stamp}")
    counter = 1
    while backup_path.exists():
        backup_path = db_path.with_name(f"{db_path.name}.bak-{stamp}-{counter}")
        counter += 1
    if db_path.is_dir():
        shutil.copytree(db_path, backup_path)
    else:
        shutil.copy2(db_path, backup_path)
    return backup_path


def migrate_store(
    db_path: str | Path,
    *,
    embedder: Embedder | None = None,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    batch_size: int = 64,
    backup: bool = True,
    dry_run: bool = False,
) -> MigrationResult:
    """Re-embed all ``Fact`` nodes in ``db_path`` and rebuild ``fact_embedding``."""
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
        raise ValueError(f"batch_size must be a positive integer, got {batch_size!r}")

    path = Path(db_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Store not found: {path}")

    if dry_run:
        target_dim = embedder.dim if embedder is not None else DEFAULT_EMBEDDING_DIM
        conn = relate.connect(str(path), read_only=True)
        try:
            current_dim = get_vector_index_dim(conn)
            rows = list(conn.execute("MATCH (f:Fact) RETURN count(f) AS c"))
            fact_count = int(rows[0]["c"]) if rows else 0
        finally:
            conn.close()
        return MigrationResult(
            db_path=path,
            current_dim=current_dim,
            target_dim=target_dim,
            fact_count=fact_count,
            updated_count=0,
            backup_path=None,
            dry_run=True,
        )

    backup_path = _create_backup(path) if backup else None
    active_embedder = embedder if embedder is not None else get_embedder(model_name)
    target_dim = active_embedder.dim

    conn = relate.connect(str(path))
    try:
        current_dim = get_vector_index_dim(conn)
        facts = [
            {"id": row["id"], "text": row["text"] or ""}
            for row in conn.execute("MATCH (f:Fact) RETURN f.id AS id, f.text AS text ORDER BY f.id")
        ]
        fact_count = len(facts)

        conn.execute("DROP INDEX fact_embedding IF EXISTS")

        updated_count = 0
        smoke_query_vec: list[float] | None = None
        for start in range(0, fact_count, batch_size):
            chunk = facts[start : start + batch_size]
            vectors = active_embedder.embed([item["text"] for item in chunk])
            if smoke_query_vec is None and vectors:
                smoke_query_vec = vectors[0]
            rows_param: list[dict[str, Any]] = [
                {"id": item["id"], "emb": vec}
                for item, vec in zip(chunk, vectors, strict=True)
            ]
            conn.execute(
                "UNWIND $rows AS row "
                "MATCH (f:Fact {id: row.id}) "
                "SET f.embedding = vector(row.emb, $dim, FLOAT32)",
                {"rows": rows_param, "dim": target_dim},
            )
            updated_count += len(chunk)

        ensure_schema(conn, target_dim)
        verified_dim = get_vector_index_dim(conn)
        if verified_dim != target_dim:
            raise RuntimeError(
                f"Expected recreated fact_embedding dimension {target_dim}, got {verified_dim}"
            )

        if fact_count > 0 and smoke_query_vec is not None:
            list(
                conn.execute(
                    "MATCH (f:Fact) "
                    "SEARCH f IN (VECTOR INDEX fact_embedding FOR vector($q, $dim, FLOAT32) LIMIT 1) "
                    "RETURN f.id AS id",
                    {"q": smoke_query_vec, "dim": target_dim},
                )
            )
    finally:
        conn.close()

    return MigrationResult(
        db_path=path,
        current_dim=current_dim,
        target_dim=target_dim,
        fact_count=fact_count,
        updated_count=updated_count,
        backup_path=backup_path,
        dry_run=False,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Re-embed an existing RelateDB memory store to a new embedding model/dimension.",
    )
    parser.add_argument(
        "--db-path",
        required=True,
        help="Path to .rl file or parquet/json store directory.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_EMBEDDING_MODEL,
        help=f"fastembed model name (default: {DEFAULT_EMBEDDING_MODEL}).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=64,
        help="Number of facts to embed per batch (default: 64).",
    )
    parser.add_argument(
        "--backup",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Create a timestamped backup before mutating the store (default: enabled).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report fact count and current vs. target index dimension without modifying the store.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = migrate_store(
        args.db_path,
        model_name=args.model,
        batch_size=args.batch_size,
        backup=args.backup,
        dry_run=args.dry_run,
    )
    if result.dry_run:
        print(
            f"[dry-run] store={result.db_path} facts={result.fact_count} "
            f"current_dim={result.current_dim} target_dim={result.target_dim}"
        )
    else:
        backup_note = f" backup={result.backup_path}" if result.backup_path else ""
        print(
            f"Migrated store={result.db_path} facts={result.updated_count}/{result.fact_count} "
            f"dim={result.current_dim}->{result.target_dim}{backup_note}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
