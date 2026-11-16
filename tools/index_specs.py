#!/usr/bin/env python3
"""Index repository ADRs, specs and modules into a Relate directory store.

The store at ``docs/context-graph/`` is created with the ``json`` snapshot
codec so ``graph.json`` is reviewable in ``git diff`` (see ADR-0004).

The indexer is idempotent. It derives the desired graph from the Markdown and
Python sources, compares it with the stored graph through a read-only
connection, and opens a writer only when they differ. Writes use ``MERGE``.

Usage:
    python tools/index_specs.py                    # refresh the store
    python tools/index_specs.py --check            # exit 1 if the store is stale
    python tools/index_specs.py --query active-adrs
    python tools/index_specs.py --query chain --target ADR-0001
    python tools/index_specs.py --query blast --target relatedb_memory.store
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STORE = ROOT / "docs" / "context-graph"
PACKAGE = "relatedb_memory"

EXCERPT_CHARS = 160
ADR_REF = re.compile(r"\bADR-(\d{4})\b")
SPEC_REF = re.compile(r"\bspecs/([\w.-]+\.md)\b")
HEADER_FIELD = re.compile(r"^\s*(?:[-*]\s*)?(?:\*\*)?([A-Za-z]+)(?:\*\*)?\s*:\s*(.+?)\s*$")
TOKEN = re.compile(r"[a-z][a-z0-9_]{2,}")
STOP_WORDS = frozenset(
    "the and for that this with are was not but all can has have from into its "
    "than then them they their there these those which while will would you "
    "our out use used uses via per any one two".split()
)

SCHEMA_STATEMENTS = (
    "CREATE FULLTEXT INDEX terms IF NOT EXISTS FOR (n:Chunk|Module|Doc) ON EACH [n.terms]",
)

ACTIVE_ADRS = (
    "MATCH (a:ADR) "
    "WHERE a.status = 'Accepted' "
    "AND NOT EXISTS { (:ADR)-[:SUPERSEDES {partial: false}]->(a) } "
    "RETURN a.number AS number, a.title AS title, a.status AS status "
    "ORDER BY number"
)
SUPERSESSION_CHAIN = (
    "MATCH (a:ADR {number: $number})-[:SUPERSEDES]->{0,3}(b:ADR) "
    "RETURN DISTINCT b.number AS number, b.status AS status ORDER BY number"
)
BLAST_RADIUS = (
    "MATCH (m:Module {name: $target})-[:CITES|MENTIONS]-(a:ADR) "
    "WHERE a.status = 'Accepted' "
    "AND NOT EXISTS { (:ADR)-[:SUPERSEDES {partial: false}]->(a) } "
    "RETURN DISTINCT a.number AS number, a.title AS title "
    "UNION "
    "MATCH (m:Module {name: $target})<-[:MENTIONS]-(:Chunk)<-[:HAS_CHUNK]-(a:ADR) "
    "WHERE a.status = 'Accepted' "
    "AND NOT EXISTS { (:ADR)-[:SUPERSEDES {partial: false}]->(a) } "
    "RETURN DISTINCT a.number AS number, a.title AS title "
    "UNION "
    "MATCH (m:Module {name: $target})<-[:MENTIONS]-(:Chunk)-[:CITES]->(a:ADR) "
    "WHERE a.status = 'Accepted' "
    "AND NOT EXISTS { (:ADR)-[:SUPERSEDES {partial: false}]->(a) } "
    "RETURN DISTINCT a.number AS number, a.title AS title"
)


def terms_of(text: str) -> str:
    """Normalized, deduplicated, sorted search terms for ``text``."""
    words = {w for w in TOKEN.findall(text.lower()) if w not in STOP_WORDS}
    return " ".join(sorted(words))


def excerpt(text: str) -> str:
    return " ".join(text.split())[:EXCERPT_CHARS]


def _adr_ids(text: str) -> list[str]:
    return sorted(set(ADR_REF.findall(text)))


def parse_header(lines: list[str]) -> tuple[dict[str, str], int]:
    """Read ``Key: value`` lines directly after the title; return fields, next index."""
    fields: dict[str, str] = {}
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    while i < len(lines):
        if not lines[i].strip():
            if fields:
                break
            i += 1
            continue
        m = HEADER_FIELD.match(lines[i])
        if not m or lines[i].lstrip().startswith("#"):
            break
        fields[m.group(1).lower()] = m.group(2)
        i += 1
    return fields, i


def split_chunks(body_lines: list[str]) -> list[tuple[str, str]]:
    """Split on ``##`` headings into ``(heading, text)``; leading text is ``Overview``."""
    chunks: list[tuple[str, list[str]]] = [("Overview", [])]
    for line in body_lines:
        if line.startswith("## "):
            chunks.append((line[3:].strip(), []))
        else:
            chunks[-1][1].append(line)
    return [(h, "\n".join(t).strip()) for h, t in chunks if "\n".join(t).strip()]


def normalize_status(raw: str) -> str:
    word = raw.strip().split()[0].strip(".,;") if raw.strip() else "Unknown"
    return word.capitalize()


def parse_markdown(path: Path, root: Path) -> dict[str, Any]:
    rel = path.relative_to(root).as_posix()
    lines = path.read_text(encoding="utf-8").splitlines()
    title_line = next((i for i, ln in enumerate(lines) if ln.startswith("# ")), None)
    title = lines[title_line][2:].strip() if title_line is not None else path.stem
    fields, nxt = parse_header(lines[(title_line + 1) if title_line is not None else 0 :])
    start = (title_line + 1 if title_line is not None else 0) + nxt
    chunks = split_chunks(lines[start:])
    doc: dict[str, Any] = {
        "path": rel,
        "title": title,
        "status": normalize_status(fields.get("status", "Unknown")),
        "fields": fields,
        "chunks": chunks,
        "text": "\n".join(lines),
    }
    return doc


def parse_module(path: Path, root: Path) -> dict[str, Any]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    docstring = ast.get_docstring(tree) or ""
    rel = path.relative_to(root)
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    name = ".".join(parts)
    description = docstring.strip().splitlines()[0] if docstring.strip() else ""
    return {
        "name": name,
        "path": rel.as_posix(),
        "description": description,
        "source": source,
        "terms": terms_of(f"{name.replace('.', ' ')} {docstring}"),
    }


def build_desired(root: Path) -> dict[str, Any]:
    """Derive nodes and relationships from the sources under ``root``."""
    adrs: dict[str, dict[str, Any]] = {}
    specs: dict[str, dict[str, Any]] = {}
    for p in sorted((root / "docs" / "adr").glob("*.md")):
        doc = parse_markdown(p, root)
        m = re.match(r"ADR-(\d{4})\b", doc["title"]) or re.match(r"(\d{4})", p.stem)
        if not m:
            continue
        doc["number"] = m.group(1)
        adrs[doc["number"]] = doc
    for p in sorted((root / "specs").glob("*.md")):
        specs[p.relative_to(root).as_posix()] = parse_markdown(p, root)
    modules = [
        parse_module(p, root)
        for p in sorted((root / PACKAGE).glob("*.py"))
        if p.is_file()
    ]
    module_names = sorted(m["name"] for m in modules)

    docs: dict[str, dict[str, Any]] = {}
    chunks: dict[str, dict[str, Any]] = {}
    rels: set[tuple[str, str, str, str, bool | None]] = set()

    def mentions(text: str) -> list[str]:
        return [n for n in module_names if re.search(rf"(?<![\w.]){re.escape(n)}(?![\w])", text)]

    all_docs = [("ADR", d) for d in adrs.values()] + [("Spec", d) for d in specs.values()]
    for kind, d in all_docs:
        labels = ("Doc", kind)
        props: dict[str, Any] = {
            "path": d["path"],
            "title": d["title"],
            "status": d["status"],
            "terms": terms_of(d["title"] + " " + d["text"]),
        }
        if kind == "ADR":
            props["number"] = d["number"]
            props["date"] = d["fields"].get("date", "")
        docs[d["path"]] = {"labels": labels, "props": props, "kind": kind, "doc": d}

    for kind, d in all_docs:
        if kind == "ADR":
            for field, partial in (("supersedes", False), ("amends", True)):
                for num in _adr_ids(d["fields"].get(field, "")):
                    if num in adrs and num != d["number"]:
                        rels.add(("Doc", d["path"], "SUPERSEDES", "Doc:" + adrs[num]["path"], partial))
        body_refs = set(_adr_ids(d["text"])) - {d.get("number", "")}
        for num in body_refs:
            if num in adrs:
                rels.add(("Doc", d["path"], "CITES", "Doc:" + adrs[num]["path"], None))
        for ref in SPEC_REF.findall(d["text"]):
            sp = f"specs/{ref}"
            if sp in specs and sp != d["path"]:
                rels.add(("Doc", d["path"], "CITES", "Doc:" + sp, None))
        for ord_, (heading, text) in enumerate(d["chunks"]):
            cid = f"{d['path']}#{ord_}"
            chunks[cid] = {
                "id": cid,
                "ord": ord_,
                "heading": heading,
                "text": excerpt(text),
                "terms": terms_of(heading + " " + text),
            }
            rels.add(("Doc", d["path"], "HAS_CHUNK", "Chunk:" + cid, None))
            for num in _adr_ids(text):
                if num in adrs and num != d.get("number"):
                    rels.add(("Chunk", cid, "CITES", "Doc:" + adrs[num]["path"], None))
            for ref in SPEC_REF.findall(text):
                sp = f"specs/{ref}"
                if sp in specs and sp != d["path"]:
                    rels.add(("Chunk", cid, "CITES", "Doc:" + sp, None))
            for name in mentions(text):
                rels.add(("Chunk", cid, "MENTIONS", "Module:" + name, None))

    mods = {}
    for m in modules:
        mods[m["name"]] = {
            "name": m["name"],
            "description": m["description"],
            "terms": m["terms"],
        }
        for num in _adr_ids(m["source"]):
            if num in adrs:
                rels.add(("Module", m["name"], "CITES", "Doc:" + adrs[num]["path"], None))

    return {
        "docs": {k: {"labels": list(v["labels"]), "props": v["props"]} for k, v in docs.items()},
        "chunks": chunks,
        "modules": mods,
        "rels": sorted(rels, key=lambda r: tuple(str(x) for x in r)),
    }


def _connect(store: Path, *, read_only: bool):
    os.environ.setdefault("RELATE_SNAPSHOT_FORMAT", "json")
    import relate

    return relate.connect(str(store), read_only=read_only)


def read_current(store: Path) -> dict[str, Any] | None:
    """Return the stored graph in the shape of :func:`build_desired`'s keys, or ``None``."""
    if not (store / "manifest.json").exists():
        return None
    db = _connect(store, read_only=True)
    try:
        docs = {
            r["path"]: {"labels": sorted(r["labels"]), "props": dict(r["props"])}
            for r in db.execute(
                "MATCH (d:Doc) RETURN d.path AS path, labels(d) AS labels, properties(d) AS props"
            )
        }
        chunks = {
            r["id"]: dict(r["props"])
            for r in db.execute("MATCH (c:Chunk) RETURN c.id AS id, properties(c) AS props")
        }
        mods = {
            r["name"]: dict(r["props"])
            for r in db.execute("MATCH (m:Module) RETURN m.name AS name, properties(m) AS props")
        }
        rels = {
            (r["sl"], r["sk"], r["type"], r["ek"], r["partial"])
            for r in db.execute(
                "MATCH (s)-[r:SUPERSEDES|CITES|HAS_CHUNK|MENTIONS]->(e) "
                "RETURN head([l IN labels(s) WHERE l IN ['Doc','Chunk','Module']]) AS sl, "
                "coalesce(s.path, s.id, s.name) AS sk, type(r) AS type, "
                "head([l IN labels(e) WHERE l IN ['Doc','Chunk','Module']]) + ':' "
                "+ coalesce(e.path, e.id, e.name) AS ek, r.partial AS partial"
            )
        }
    finally:
        db.close()
    return {"docs": docs, "chunks": chunks, "modules": mods, "rels": rels}


def is_current(store: Path, desired: dict[str, Any]) -> bool:
    current = read_current(store)
    if current is None:
        return False
    want_docs = {
        k: {"labels": sorted(v["labels"]), "props": v["props"]} for k, v in desired["docs"].items()
    }
    return (
        current["docs"] == want_docs
        and current["chunks"] == desired["chunks"]
        and current["modules"] == desired["modules"]
        and current["rels"] == {tuple(r) for r in desired["rels"]}
    )


def apply(store: Path, desired: dict[str, Any]) -> None:
    """Write ``desired`` into ``store`` with MERGE; delete entries no longer present."""
    store.mkdir(parents=True, exist_ok=True)
    db = _connect(store, read_only=False)
    try:
        for stmt in SCHEMA_STATEMENTS:
            db.execute(stmt)
        for path, d in desired["docs"].items():
            labels = ":".join(d["labels"])
            db.execute(f"MERGE (n:{labels} {{path: $path}}) SET n += $props", {"path": path, "props": d["props"]})
        for cid, props in desired["chunks"].items():
            db.execute("MERGE (n:Chunk {id: $id}) SET n += $props", {"id": cid, "props": props})
        for name, props in desired["modules"].items():
            db.execute("MERGE (n:Module {name: $name}) SET n += $props", {"name": name, "props": props})
        db.execute("MATCH (n:Doc) WHERE NOT n.path IN $keep DETACH DELETE n", {"keep": list(desired["docs"])})
        db.execute("MATCH (n:Chunk) WHERE NOT n.id IN $keep DETACH DELETE n", {"keep": list(desired["chunks"])})
        db.execute("MATCH (n:Module) WHERE NOT n.name IN $keep DETACH DELETE n", {"keep": list(desired["modules"])})
        db.execute("MATCH ()-[r:SUPERSEDES|CITES|HAS_CHUNK|MENTIONS]->() DELETE r")
        keyprop = {"Doc": "path", "Chunk": "id", "Module": "name"}
        for sl, sk, rtype, ek, partial in desired["rels"]:
            el, ekey = ek.split(":", 1)
            rel = f"{rtype} {{partial: $partial}}" if partial is not None else rtype
            db.execute(
                f"MATCH (s:{sl} {{{keyprop[sl]}: $sk}}), (e:{el} {{{keyprop[el]}: $ek}}) "
                f"MERGE (s)-[:{rel}]->(e)",
                {"sk": sk, "ek": ekey, "partial": partial},
            )
    finally:
        db.close()


def index(root: Path = ROOT, store: Path | None = None) -> bool:
    """Refresh the store. Return True when anything was written."""
    store = store or (root / "docs" / "context-graph")
    desired = build_desired(root)
    if is_current(store, desired):
        return False
    apply(store, desired)
    return True


def run_query(store: Path, name: str, target: str | None = None) -> list[dict[str, Any]]:
    """Run a named read-only helper query against ``store``."""
    db = _connect(store, read_only=True)
    try:
        if name == "active-adrs":
            cur = db.execute(ACTIVE_ADRS)
        elif name == "chain":
            number = (target or "").removeprefix("ADR-")
            cur = db.execute(SUPERSESSION_CHAIN, {"number": number})
        elif name == "blast":
            cur = db.execute(BLAST_RADIUS, {"target": target})
        else:
            raise ValueError(f"unknown query: {name}")
        return [r.data() for r in cur]
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", type=Path, default=DEFAULT_STORE)
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--check", action="store_true", help="exit 1 if the store is stale; write nothing")
    ap.add_argument("--query", choices=["active-adrs", "chain", "blast"])
    ap.add_argument("--target", help="ADR-NNNN for chain, module name for blast")
    args = ap.parse_args(argv)

    if args.query:
        print(json.dumps(run_query(args.store, args.query, args.target), indent=2))
        return 0
    if args.check:
        stale = not is_current(args.store, build_desired(args.root))
        print("stale" if stale else "current")
        return 1 if stale else 0
    changed = index(args.root, args.store)
    print("updated" if changed else "unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
