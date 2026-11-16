# ADR-0005: Bounded single-writer queue for the store thread

- Status: Accepted
- Date: 2026-11-16
- Amends: ADR-0002

## Context

ADR-0002 introduced a dedicated worker thread but left the queue unbounded
and did not say how callers behave when the worker is busy.

## Decision

This ADR amends ADR-0002 in part. The queue between provider threads and the
worker thread in `relatedb_memory.store` is bounded, and a submit that cannot
enqueue within its timeout raises instead of blocking Hermes. The in-process
access decision of ADR-0002 is unchanged and still governs.

## Consequences

- Back-pressure is explicit and bounded.
- Callers must handle a timeout error from the store.
