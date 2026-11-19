# ADR-0008: Flag near-duplicate facts and collapse them in recall

- Status: Accepted
- Date: 2026-11-19
- Amends: ADR-0001

## Context

Only facts in the same slot supersede each other. The same statement repeated over several sessions lands in different slots, takes one recall slot per repetition and looks like corroboration. Every fact already has a local embedding (ADR-0006).

## Decision

A deterministic pass without an LLM links near-duplicate open facts: `(:Fact)-[:DUPLICATE_OF {score, detectedAt}]->(:Fact)`, pointing at a canonical fact. Duplicates stay open facts with their own provenance; nothing is closed or deleted.

- **Similarity:** cosine similarity from the fact vector index, at least `dedupe_threshold` (default `0.92`), among the top 10 neighbours of each fact.
- **Clustering:** facts are visited with deliberate origins first, then earliest, then by id. Each unvisited fact becomes a canonical and claims its unvisited neighbours. There are no chains, so a cluster never links two facts that are not both close to its canonical. This makes the canonical the earliest deliberate fact, else the earliest fact.
- **Safety:** facts in different explicit slots are never merged (slots under `turn/` and `pre_compress/` are capture bookkeeping and do not count). Only open facts take part, so a closed fact is never canonical, and a pass removes edges whose canonical has closed.
- **Idempotent:** the pass computes the desired edge set and writes only the difference, so a rerun over an unchanged store writes nothing. `detectedAt` is set when an edge is created.
- **When:** after each write that has an embedding, over the new fact, its neighbours and the clusters they touch; and `hermes relatedb-memory dedupe [--dry-run]` over the whole store. No scheduler. All writes use `RelateStore` in batches of 50. A dry run uses a read-only connection.
- **Recall:** with `dedupe` on, a duplicate is replaced by its canonical, once per cluster, with `seen`: the number of distinct episodes among the canonical and its open duplicates. Repeating a statement inside one episode adds nothing. With `dedupe` off the recall query and result are unchanged.
- **Config:** `dedupe` (default `true`, `RELATEDB_DEDUPE`) and `dedupe_threshold` (`RELATEDB_DEDUPE_THRESHOLD`).

## Consequences

- Repeated statements use one recall slot and report how many episodes support them.
- The on-write pass sees only a neighbourhood, so a full `dedupe` run can re-pick a canonical that the incremental pass left alone.
- Embedding similarity does not separate negation or one-word differences well; the threshold is a precision knob, and a fixture test guards the known case ("prefers tabs" against "prefers spaces").
