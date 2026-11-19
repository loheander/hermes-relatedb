# ADR-0007: Origin-aware recall ranking

- Status: Accepted
- Date: 2026-11-19
- Amends: ADR-0001

## Context

`sync_turn` records every primary turn as an open fact in a unique slot, so these facts never close. Recall treated them like facts from `relatedb_remember` or `on_memory_write`, and 50 captured turns could fill the whole `prefetch_top_k` budget with raw user sentences.

## Decision

Each `:Fact` carries an `origin`: `turn`, `pre_compress`, `memory_write` or `remember`. The write path sets it; when absent, `record_fact` derives it from the episode kind. `tools/backfill_origins.py` sets it on existing stores and only touches facts without one, so it is idempotent.

Recall uses a share cap, not a score penalty. `memory_write` and `remember` facts are always eligible. `turn` and `pre_compress` facts fill at most `max(1, floor(k * captured_share))` results, with `captured_share` defaulting to `0.5` and configurable from 0 to 1 (`RELATEDB_CAPTURED_SHARE`). The store over-fetches candidates (at least 64) so deliberate facts are found behind many captured ones, then keeps score order within the caps. A cap is predictable and testable. A penalty needs a tuned constant per embedding model.

`_format_recall_block` prints `from=<origin>` and marks captured hits `transcript, unconfirmed`.

The optional `episodes_only` capture mode is not adopted. It needs a separate episode search path and can be decided later.

## Consequences

- Remembered facts reliably appear in the top `k` next to captured turns.
- With `k=1` the cap still admits one captured fact, so the single result is the best hit overall.
- Unfilled capacity is not backfilled with captured facts, so recall can return fewer than `k` hits.
- Recall hits gain an `origin` key.
