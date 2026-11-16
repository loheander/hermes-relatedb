# AGENTS.md

Guidance for coding agents and contributors working on `hermes-relatedb`.

## Decision context graph

Architecture Decision Records live in `docs/adr/` and specifications in
`specs/`. They are indexed in a committed Relate directory store at
`docs/context-graph/` (JSON snapshot codec, see ADR-0004 and
`specs/context-graph.md`). Query it before editing code, so you read only the
decisions that are still active instead of grepping every ADR.

### Query (read-only)

Always open the store read-only. A read-only connection never modifies the
working tree.

```sh
# Active decisions: Accepted and not fully superseded
uv run python tools/index_specs.py --query active-adrs
# Supersession chain from an ADR (up to 3 hops)
uv run python tools/index_specs.py --query chain --target ADR-0005
# Active ADRs governing a module (blast radius)
uv run python tools/index_specs.py --query blast --target relatedb_memory.store
```

With the Relate CLI installed, serve the graph over MCP. `--read-only=live`
follows the writer's WAL, so an agent sees refreshes while a contributor
re-indexes:

```sh
relate serve --mcp stdio --database ./docs/context-graph --read-only=live
```

Cypher for the same questions, from Python (`relate.connect(path, read_only=True)`)
or any MCP client:

```cypher
MATCH (a:ADR)
WHERE a.status = 'Accepted'
  AND NOT EXISTS { (:ADR)-[:SUPERSEDES {partial: false}]->(a) }
RETURN a.number, a.title

MATCH (:Module {name: $target})-[:CITES|MENTIONS]-(a:ADR) RETURN a.number, a.title
```

A partial amendment (`Amends: ADR-XXXX` in the ADR header) creates a
`SUPERSEDES {partial: true}` edge. The amended ADR stays active; read both.

### Refresh

After you add or edit `docs/adr/*.md`, `specs/*.md` or a module docstring:

```sh
make index-specs   # also runs `make setup-git`
git add docs/context-graph
```

`make setup-git` sets `git config diff.relate-json.textconv "jq ."` (install
`jq`) so `graph.json` diffs are readable. `.gitattributes` already maps the file
to that driver. The indexer is idempotent: with no Markdown change it writes
nothing and `git status --short` stays clean. `python tools/index_specs.py
--check` exits 1 when the store is stale.

### ADR format

```markdown
# ADR-0006: Short title

- Status: Accepted
- Date: 2026-11-16
- Supersedes: ADR-0003     (optional, full supersession)
- Amends: ADR-0002         (optional, partial amendment)
```

Mention other ADRs as `ADR-NNNN`, specs as `specs/name.md` and modules by
dotted name such as `relatedb_memory.store` so the indexer links them. Set the
status of a fully superseded ADR to `Superseded`.

## Tests

`make test` runs the suite.
