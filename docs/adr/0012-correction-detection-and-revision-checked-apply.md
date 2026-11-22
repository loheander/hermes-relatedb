# ADR-0012: Correction detection and revision-checked apply

- Status: Proposed
- Date: 2026-11-22
- Relates to: ADR-0001, ADR-0005

## Context

The failure that matters most for Dream Mode (#33) is a successful run that silently changes meaning: an old decision reasserted over a newer correction, or two statements that only look contradictory merged into one. Agreed safeguards: a revision-checked apply through the single writer, explicit corrections outrank inferred observations, and rollback closes derived facts instead of deleting history. The scenarios in `tests/e2e/features/dream_correction_apply.feature` (tagged `@pending_58`) express the behaviour; this ADR records the decisions behind them and the questions they cannot settle. It constrains only how proposals are applied; it does not depend on the run lifecycle or model routing stories, and assumes only that a manual `dream` command runs one cycle and records a `(:DreamRun)`.

## Decision

- **Explicit vs inferred.** A fact is an *explicit correction* when the user states it through a deliberate seam: the new tool `relatedb_correct(slot, text)`. It gets `origin = "correction"`, supersedes the open facts of its slot immediately (the ADR-0001 mechanism, no Dream run involved) and keeps the old version closed, with provenance. Everything the Dream model derives is *inferred* (`origin = "dream"`, `runId` set). Captured and `remember` facts keep their ADR-0007 origins. Rank: `correction` > `remember` and `memory_write` > `dream` and captured.
- **Inferred never beats explicit.** A Dream proposal that would write or supersede in a slot whose open fact is an explicit correction, or whose text opposes one, is rejected with reason `contradicts_explicit_correction`, recorded in the run, and not retried. The revision check runs first, so a proposal made stale by a correction that landed in flight is rejected as `stale_revision` and retried, where the explicit-correction rule then rejects it for good.
- **Scope.** A statement supersedes only facts in its own slot. Slots under another project (`project/beta/...`) are another scope and never correspond.
- **Conflict representation: an edge.** `(:Fact)-[:CONFLICTS_WITH {detectedAt}]->(:Fact)`. Both facts stay open with their own provenance, nothing is closed. A node would add a record to maintain without carrying more information; the edge is created and removed like the `DUPLICATE_OF` edge of ADR-0008. A model correction with `certainty: "ambiguous"` writes its new fact in the slot it names and links it to its target this way. Recall marks both sides with `conflict` and does not choose.
- **Revision check.** The store keeps a monotonically increasing `revision` counter, bumped inside the writer's batch for each write that can change what a proposal assumed (fact write, supersession, retraction). A run records the revision it read. Each proposal is applied as one batch that first compares the revisions of the slots and facts it touches against the revision the run read; a mismatch rejects that proposal with `stale_revision`, is retried next cycle, and the other proposals apply. Retry is per proposal: an episode counts as processed only once every proposal citing it is applied or terminally rejected. A correction landing in flight is therefore never overwritten, and unaffected proposals still apply.
- **Single writer.** Apply goes through the provider's `RelateStore` writer (ADR-0005); the run opens no store handle of its own when a provider is given (the manual command takes the provider, plugin context and embedder by injection, as the e2e scenarios do). The model call happens outside the writer queue.
- **Correction proposals.** The proposal schema gains `{"kind": "correction", "corrects": [fact id], "certainty": "clear" | "ambiguous", ...}`. It is applied only when each fact in `corrects` exists (`source_missing`), is open (`source_closed`) and is not already covered by an open fact with the same meaning (`already_covered`). A `clear` correction supersedes in the target's slot.
- **Rollback.** `hermes relatedb-memory dream --rollback <run id>` closes every fact with that `runId` (setting `closedAt`) and removes the `CONFLICTS_WITH` edges it created. It reopens nothing it superseded and deletes nothing; originals stay as they were. The `(:DreamRun)` stays in history with `rolledBackAt` set.

## Open questions

- How recall presents an unresolved conflict beyond the word `conflict` (inline pairing, a separate section, a rank penalty), and how much room it takes of `k`.
- Whether the user can resolve a conflict from the CLI (for example `conflicts` and `resolve <fact id>`), and whether resolving counts as an explicit correction.
- Whether rollback should restore facts a rolled-back run superseded (this ADR says no: a run supersedes only through checked, rejectable proposals, and a restore could undo a later correction).
- How "opposes" is decided for the explicit-wins rule: slot equality is deterministic, text opposition needs the embedding threshold of ADR-0008 or the model.
- How "already covered" is decided: exact text, embedding similarity, or both.

## Consequences

- A correction takes effect at once and is never lost to a concurrent run, at the price of one revision counter in the schema.
- Rejections are visible in run history with a reason code, so a quiet run is distinguishable from a refused one.
- Ambiguity costs a recall slot for each side until a person or a later correction settles it.
