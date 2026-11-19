#!/usr/bin/env python3
"""Backfill ``Fact.origin`` on existing stores from the provenance episode kind.

Idempotent: only facts without an ``origin`` are touched, so a second run
changes nothing (ADR-0007). Facts with no provenance episode are left alone.

Usage:
    python tools/backfill_origins.py --db-path ~/.hermes/memory [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import relate

from relatedb_memory.schema import origin_for_episode_kind


@dataclass(frozen=True)
class BackfillResult:
    db_path: Path
    missing_count: int
    updated_count: int
    dry_run: bool


def backfill_store(db_path: str | Path, *, dry_run: bool = False) -> BackfillResult:
    """Set ``origin`` on every fact lacking one, derived from its episode kind."""
    path = Path(db_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Store not found: {path}")

    conn = relate.connect(str(path), read_only=dry_run)
    try:
        rows = [
            {"id": r["id"], "kind": r["kind"]}
            for r in conn.execute(
                "MATCH (f:Fact) WHERE f.origin IS NULL "
                "OPTIONAL MATCH (f)-[:FROM]->(ep:Episode) "
                "RETURN f.id AS id, ep.kind AS kind ORDER BY f.id"
            )
        ]
        # A fact may have several provenance rows; keep the first per id.
        by_id: dict[str, str | None] = {}
        for row in rows:
            by_id.setdefault(row["id"], row["kind"])
        missing = len(by_id)
        updated = 0
        if not dry_run:
            for kind in sorted({k for k in by_id.values()}, key=lambda k: str(k)):
                ids = [i for i, k in by_id.items() if k == kind]
                if not ids:
                    continue
                conn.execute(
                    "UNWIND $ids AS fid MATCH (f:Fact {id: fid}) "
                    "WHERE f.origin IS NULL SET f.origin = $origin",
                    {"ids": ids, "origin": origin_for_episode_kind(kind)},
                )
                updated += len(ids)
    finally:
        conn.close()
    return BackfillResult(path, missing, updated, dry_run)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill Fact.origin from episode kinds.")
    parser.add_argument("--db-path", required=True, help="Path to .rl file or parquet/json store directory.")
    parser.add_argument("--dry-run", action="store_true", help="Report the count without modifying the store.")
    args = parser.parse_args(argv)
    result = backfill_store(args.db_path, dry_run=args.dry_run)
    prefix = "[dry-run] " if result.dry_run else ""
    print(f"{prefix}store={result.db_path} missing={result.missing_count} updated={result.updated_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
