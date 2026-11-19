"""Near-duplicate detection over open facts (#40, ADR-0008).

Deterministic and non-LLM: cosine similarity between the stored BGE embeddings.
Duplicates stay open facts; they are linked ``(dup)-[:DUPLICATE_OF {score,
detectedAt}]->(canonical)`` and collapsed only at recall time.

The planner is pure over a connection (``plan_links``), so a dry run can use a
read-only connection. All writes go through ``RelateStore`` (single writer).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .schema import DELIBERATE_ORIGINS, origin_for_episode_kind

DEFAULT_DEDUPE = True
DEFAULT_DEDUPE_THRESHOLD = 0.92
DEFAULT_TOP_N = 10
WRITE_BATCH = 50

#: Slot prefixes of auto-captured facts. Their slots are unique per capture, so
#: they carry no meaning and never block a merge.
_CAPTURE_SLOT_PREFIXES = ("turn/", "pre_compress/")


@dataclass(frozen=True)
class _Fact:
    id: str
    slot: str | None
    origin: str
    recorded_at: str


def validate_threshold(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        raise ValueError(f"dedupe_threshold must be a number between 0 and 1, got {value!r}")
    return float(value)


def _explicit_slot(slot: str | None) -> str | None:
    if slot is None or slot.startswith(_CAPTURE_SLOT_PREFIXES):
        return None
    return slot


def _compatible(a: _Fact, b: _Fact) -> bool:
    """Facts in different explicit slots are never merged."""
    sa, sb = _explicit_slot(a.slot), _explicit_slot(b.slot)
    return sa is None or sb is None or sa == sb


def _priority(f: _Fact) -> tuple[int, str, str]:
    """Canonical order: deliberate before captured, then earliest, then id."""
    return (0 if f.origin in DELIBERATE_ORIGINS else 1, f.recorded_at, f.id)


def _load_fact(conn: Any, fact_id: str) -> _Fact | None:
    rows = list(
        conn.execute(
            "MATCH (f:Fact {id: $id}) WHERE f.closedAt IS NULL AND f.embedding IS NOT NULL "
            "OPTIONAL MATCH (f)-[:FROM]->(ep:Episode) "
            "RETURN f.id AS id, f.slot AS slot, f.origin AS origin, f.recordedAt AS at, ep.kind AS kind",
            {"id": fact_id},
        )
    )
    if not rows:
        return None
    r = rows[0]
    return _Fact(r["id"], r["slot"], r["origin"] or origin_for_episode_kind(r["kind"]), r["at"] or "")


def _neighbours(conn: Any, fact_id: str, threshold: float, top_n: int) -> dict[str, tuple[_Fact, float]]:
    """Open facts whose cosine similarity to ``fact_id`` is at least ``threshold``."""
    rows = conn.execute(
        "MATCH (f:Fact {id: $id}) WHERE f.embedding IS NOT NULL "
        "MATCH (g:Fact) SEARCH g IN (VECTOR INDEX fact_embedding FOR f.embedding "
        "WHERE g.closedAt IS NULL LIMIT $n) SCORE AS score "
        "OPTIONAL MATCH (g)-[:FROM]->(ep:Episode) "
        "RETURN g.id AS id, g.slot AS slot, g.origin AS origin, g.recordedAt AS at, "
        "ep.kind AS kind, score",
        {"id": fact_id, "n": top_n + 1},
    )
    out: dict[str, tuple[_Fact, float]] = {}
    for r in rows:
        if r["id"] == fact_id or r["score"] < threshold or r["id"] in out:
            continue
        out[r["id"]] = (
            _Fact(r["id"], r["slot"], r["origin"] or origin_for_episode_kind(r["kind"]), r["at"] or ""),
            float(r["score"]),
        )
    return out


def _cluster_context(conn: Any, ids: set[str]) -> set[str]:
    """``ids`` plus the open canonicals and open members of the clusters they touch."""
    if not ids:
        return set()
    listed = sorted(ids)
    rows = conn.execute(
        "MATCH (s:Fact)-[:DUPLICATE_OF]->(t:Fact) "
        "WHERE (s.id IN $ids OR t.id IN $ids) AND s.closedAt IS NULL AND t.closedAt IS NULL "
        "RETURN s.id AS s, t.id AS t",
        {"ids": listed},
    )
    canonicals = set(ids)
    for r in rows:
        if r["s"] in ids:
            canonicals.add(r["t"])
    members = set(canonicals)
    rows = conn.execute(
        "MATCH (s:Fact)-[:DUPLICATE_OF]->(t:Fact) "
        "WHERE t.id IN $ids AND s.closedAt IS NULL AND t.closedAt IS NULL RETURN s.id AS s",
        {"ids": sorted(canonicals)},
    )
    members.update(r["s"] for r in rows)
    return members


def plan_links(
    conn: Any,
    threshold: float,
    *,
    fact_ids: list[str] | None = None,
    top_n: int = DEFAULT_TOP_N,
) -> list[dict[str, Any]]:
    """Return the changes that make ``DUPLICATE_OF`` edges match the current store.

    ``fact_ids=None`` plans over every open fact with an embedding; otherwise over
    those facts, their near neighbours and the clusters they touch. Each change is
    ``{"fact_id", "canonical_id", "score", "action"}`` with action ``link`` or
    ``unlink``. A store whose edges already match yields ``[]``.
    """
    threshold = validate_threshold(threshold)
    facts: dict[str, _Fact] = {}
    if fact_ids is None:
        for r in conn.execute(
            "MATCH (f:Fact) WHERE f.closedAt IS NULL AND f.embedding IS NOT NULL "
            "OPTIONAL MATCH (f)-[:FROM]->(ep:Episode) "
            "RETURN f.id AS id, f.slot AS slot, f.origin AS origin, f.recordedAt AS at, ep.kind AS kind"
        ):
            facts.setdefault(
                r["id"], _Fact(r["id"], r["slot"], r["origin"] or origin_for_episode_kind(r["kind"]), r["at"] or "")
            )
    else:
        seeds: set[str] = set()
        for fid in fact_ids:
            fact = _load_fact(conn, fid)
            if fact is None:
                continue
            seeds.add(fid)
            seeds.update(_neighbours(conn, fid, threshold, top_n))
        for fid in sorted(_cluster_context(conn, seeds)):
            fact = _load_fact(conn, fid)
            if fact is not None:
                facts[fid] = fact

    neighbours = {fid: _neighbours(conn, fid, threshold, top_n) for fid in facts}

    def score_of(a: str, b: str) -> float | None:
        hit = neighbours[a].get(b) or neighbours[b].get(a)
        return None if hit is None else hit[1]

    desired: dict[str, tuple[str, float]] = {}
    done: set[str] = set()
    for fid in sorted(facts, key=lambda i: _priority(facts[i])):
        if fid in done:
            continue
        done.add(fid)
        for oid in sorted(neighbours[fid], key=lambda i: _priority(facts[i]) if i in facts else (2, "", i)):
            if oid in done or oid not in facts or not _compatible(facts[fid], facts[oid]):
                continue
            score = score_of(fid, oid)
            if score is None:
                continue
            done.add(oid)
            desired[oid] = (fid, round(score, 4))

    existing: dict[str, dict[str, float | None]] = {}
    for r in conn.execute(
        "MATCH (s:Fact)-[r:DUPLICATE_OF]->(t:Fact) WHERE s.id IN $ids "
        "RETURN s.id AS s, t.id AS t, r.score AS score",
        {"ids": sorted(facts)},
    ):
        existing.setdefault(r["s"], {})[r["t"]] = r["score"]

    changes: list[dict[str, Any]] = []
    for fid in sorted(facts):
        want = desired.get(fid)
        have = existing.get(fid, {})
        for target in sorted(have):
            if want is None or want[0] != target:
                changes.append({"fact_id": fid, "canonical_id": target, "score": have[target], "action": "unlink"})
        if want is not None and want[0] not in have:
            changes.append({"fact_id": fid, "canonical_id": want[0], "score": want[1], "action": "link"})
    return changes


def apply_changes(conn: Any, changes: list[dict[str, Any]], detected_at: str) -> None:
    """Write ``plan_links`` output. Idempotent: ``MERGE`` links, delete only listed edges."""
    unlink = [{"s": c["fact_id"], "t": c["canonical_id"]} for c in changes if c["action"] == "unlink"]
    link = [
        {"s": c["fact_id"], "t": c["canonical_id"], "score": c["score"]}
        for c in changes
        if c["action"] == "link"
    ]
    if unlink:
        conn.execute(
            "UNWIND $rows AS row MATCH (s:Fact {id: row.s})-[r:DUPLICATE_OF]->(t:Fact {id: row.t}) DELETE r",
            {"rows": unlink},
        )
    if link:
        conn.execute(
            "UNWIND $rows AS row MATCH (s:Fact {id: row.s}), (t:Fact {id: row.t}) "
            "MERGE (s)-[r:DUPLICATE_OF]->(t) ON CREATE SET r.score = row.score, r.detectedAt = $at",
            {"rows": link, "at": detected_at},
        )
