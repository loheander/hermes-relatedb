# Codebase context graph

- Status: Accepted

Specification of the committed graph in `docs/context-graph/` that indexes the
repository's ADRs, specs and modules. Rationale is in ADR-0004.

## Schema

Nodes: `(:Doc:ADR {path, number, title, status, date, terms})`,
`(:Doc:Spec {path, title, status, terms})`,
`(:Chunk {id, ord, heading, text, terms})` and
`(:Module {name, description, terms})`. Relationships:
`SUPERSEDES {partial}`, `CITES`, `HAS_CHUNK` and `MENTIONS`.

## Refresh

`make index-specs` runs `tools/index_specs.py`. It is idempotent: a run with no
Markdown changes writes nothing. Agents read the graph with read-only
connections only.

## Retrieval

Agents ask for active ADRs first, then for the ADRs that cite the module they
are about to edit, such as `relatedb_memory.store`, which ADR-0002 and
ADR-0005 govern.
