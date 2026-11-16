---
name: relatedb-memory
description: Bi-temporal RelateDB memory graph for Hermes Agent (remember, recall, as-of audit, provenance, read-only Cypher).
---

# RelateDB Bi-Temporal Memory

Use the `relatedb_*` tools to store and audit durable knowledge without overwriting history:

- **`relatedb_remember(text, slot, about?, valid_from?)`**: Store or update a fact in a named `slot` (e.g. `project/owner`, `prefs/editor`). Supersedes any open fact in that slot non-destructively.
- **`relatedb_recall(query, k?)`**: Semantic vector search over open facts (`closedAt IS NULL`), returning `about` entities, `learnedFrom` episode provenance, and `replaced` prior facts.
- **`relatedb_forget(slot? | fact_id?)`**: Close an active fact without deleting history.
- **`relatedb_as_of(slot, on)`**: Audit `trueOn` (world validity) vs `believedOn` (agent belief at `on`).
- **`relatedb_provenance(slot? | fact_id?)`**: Inspect the `(:Fact)-[:FROM]->(:Episode)` and `[:SUPERSEDES]` lineage.
- **`relatedb_cypher(query, params?)`**: Run read-only Cypher (`MATCH`, `SEARCH`, `CALL db.schema.visualization()`).

## Shared Zettelkasten Entity Keys

Use canonical entity keys (`note_id:<id>`, `citation_key:<key>`, `project_slug:<slug>`) in `about` so facts across conversations converge on the same `:Entity` nodes.
