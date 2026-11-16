# ADR-0001: Bi-temporal Entity-Episode-Fact memory schema

- Status: Accepted
- Date: 2026-11-16

## Context

The memory provider must answer "what did we believe at time T" and "what is
true now" for the same entity. Overwriting properties loses history, and a
flat note store cannot express that a fact was later corrected.

## Decision

Memory is stored as a bi-temporal graph with three node kinds: `Entity`
(a thing the agent talks about), `Episode` (a source event such as a chat
turn) and `Fact` (a claim linking entities). Facts carry `valid_from`,
`valid_to` (when the claim holds in the world) and `recorded_at` (when the
provider learned it). Corrections close the old fact instead of deleting it.
The schema lives in `relatedb_memory.schema`.

## Consequences

- History is queryable and nothing is destroyed on update.
- Retrieval must filter on `valid_to IS NULL` to see current facts.
- The store layer in `relatedb_memory.store` owns all writes to these nodes.
