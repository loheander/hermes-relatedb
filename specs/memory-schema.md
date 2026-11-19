# Memory graph schema

- Status: Accepted

Specification of the graph that `relatedb_memory` persists. Rationale lives in
ADR-0001.

## Nodes

`Entity {name, kind}`, `Episode {id, source, recorded_at}` and
`Fact {id, text, valid_from, valid_to, recorded_at, embedding}`. The
definitions are implemented in `relatedb_memory.schema`.

`Fact.origin` is one of `turn`, `pre_compress`, `memory_write` or `remember`
and says how the fact was captured. Recall ranks by it as decided in ADR-0007.

## Relationships

`(:Episode)-[:ASSERTS]->(:Fact)` and `(:Fact)-[:ABOUT]->(:Entity)`. A
correction sets `valid_to` on the old fact and adds a new one; see ADR-0001.

## Access

All reads and writes go through `relatedb_memory.store` on its single worker
thread, as decided in ADR-0002 and amended by ADR-0005.
