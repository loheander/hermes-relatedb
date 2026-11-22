# ADR-0009: Dream Mode run lifecycle, checkpoint and DreamRun record

- Status: Proposed
- Date: 2026-11-22
- Relates to: ADR-0001, ADR-0005, ADR-0008

## Context

Dream Mode (#33) consolidates captured episodes into reviewed facts and profile proposals with an LLM. The requester's constraints: it is opt-in, it skips runs with no new material, its last run and pending work are easy to inspect, and a dry run leaves active memory, profile and the apply checkpoint unchanged. Hermes already provides `register_idle_task`, `register_auxiliary_task` and a plugin LLM (`ctx.llm.complete_structured`), so the plugin ships no scheduler and no LLM client. The e2e scenarios in `tests/e2e/features/dream_run_lifecycle.feature` (tagged `@pending_55`) express the behaviour; this ADR records the decisions behind them and the questions they cannot settle.

## Decision

### Entry point and coexistence with the memory provider

- A second, general-plugin entry point, `relatedb_memory.dream.register(ctx, *, embedder=None)`, is called from the plugin `register(ctx)` when the host context offers `register_idle_task`. It is independent of `register_memory_provider`: the provider keeps serving capture and recall and never imports the Dream code path.
- With `dream` false (the default) the entry point returns before registering anything: no idle task, no auxiliary task, no LLM call. Capture and recall are untouched.
- With `dream` true it registers one auxiliary task (so `ctx.llm` can route it) and one idle task with the configured `interval_hours` and `min_idle_hours`. It does not add a scheduler.
- Each run opens its own store handle, runs, and closes it, rather than borrowing the provider's. Single-writer access (ADR-0005) is therefore enforced between runs and provider writes by the store, not by shared state.

### Run lifecycle

1. Select episodes after the apply checkpoint, ordered by `(at, id)`, at most `dream_batch_size`.
2. None: record a `DreamRun` with outcome `skipped` and make no LLM call.
3. Otherwise call `ctx.llm.complete_structured` once for the batch with a closed JSON schema.
4. Validate each proposal. Valid ones are applied (unless dry run), invalid ones are rejected and recorded.
5. Publish all applied changes and advance the checkpoint in one write, then record the `DreamRun`. A failure before that write publishes nothing and leaves the checkpoint where it was; the run is recorded `failed` with the error.

The idle task and the manual command share this lifecycle. The manual command `hermes relatedb dream` ignores idle state; `--dry-run` runs steps 1 to 4, which includes the model call, and records the run but applies nothing and does not move the checkpoint. Its output warns that the call can incur charges. A user who wants no call at all uses `--status`; `--status` reads only.

### Apply checkpoint

The checkpoint is the `(at, id)` position of the last episode of the last completed, non-dry run, stored as `checkpointAfter` on that `DreamRun`. A run always starts from the latest such value. Because the checkpoint moves only together with the published changes, an interrupted run resumes without losing source episodes. Applying is idempotent: a proposed fact whose open slot already holds the same text is recorded as unchanged and creates no fact and no `DUPLICATE_OF` link (ADR-0008), so repeating a statement does not raise corroboration.

### DreamRun schema

`(:DreamRun {id, startedAt, finishedAt, mode, dryRun, outcome, checkpointBefore, checkpointAfter, episodes, proposals, applied, rejected, failures})`, linked `(:DreamRun)-[:PROCESSED]->(:Episode)`. `mode` is `scheduled` or `manual`; `outcome` is `completed`, `skipped` or `failed`. The list-valued fields are JSON-encoded strings because the store holds scalar properties. Applied facts carry `(:Fact)-[:PROPOSED_BY]->(:DreamRun)`; their provenance still reaches the source episodes through `FROM`.

### Closed proposal schema

The model may only return `{"proposals": [{"kind", "text", "slot", "source_episodes"}]}` with `kind` one of `fact` or `profile`, `slot` required for `fact`, and every source episode inside the batch. A `fact` proposal is applied through the normal fact write path. A `profile` proposal is stored for review and is never applied automatically. Anything else, including a kind such as deletion, a missing source or an episode outside the batch, is rejected and recorded. The model cannot retract or close facts.

### Inspection

`hermes relatedb dream --status` prints one JSON object: `last_run` (outcome, dry-run flag, counts, or null), `pending_episodes`, `checkpoint`, `profile_proposals` and `idle_seconds` (time since the newest episode). A busy instance that never got to run shows pending episodes with no last run.

### Configuration

Under `memory.relatedb-memory`, with matching `RELATEDB_*` variables: `dream` (bool, default `false`), `dream_interval_hours`, `dream_min_idle_hours`, `dream_batch_size`. Defaults are open questions below.

## Consequences

- Off costs nothing and changes nothing for existing users.
- Every run, including skipped, failed and dry runs, leaves an inspectable node, so "why did it not run" is answerable from the graph or `--status`.
- One LLM call per batch bounds cost per run; the backlog drains over several runs.
- A second plugin entry point means two registration paths to keep consistent, and `fact` origins need a new value (for example `dream`) in `schema.FACT_ORIGINS` so recall can rank them (ADR-0007).

## Open questions

The scenarios fix none of these.

1. **Batch size default.** Large enough to drain a backlog in a few runs, small enough for the model context. Proposal: 50 episodes, tuned by character budget rather than count.
2. **Cooldown defaults.** Proposal: `interval_hours` 24 and `min_idle_hours` 2, which matches the Hermes idle-task defaults. The host raises `interval_hours` to its own minimum of 1.
3. **What "idle" means for a gateway with many sessions.** The host measures idleness for the process; a gateway serving several users may never be idle. Options: process-wide idle as the host defines it, per-profile idle, or ignore idle and rely on `interval_hours`. `--status` exposes `idle_seconds` so the effect is visible.
4. **Manual run when the idle task is mid-run.** Serialise with a lock file, or fail the second run with a clear message.
5. **Command name.** The issue says `hermes relatedb dream`; the existing CLI is `hermes relatedb-memory`. Register a second top-level command or add `dream` to the existing one.
6. **How the CLI handler receives the plugin context.** The scenarios assume `cli.main(argv, ctx=..., embedder=...)`; the real wiring through `register_cli_command` may differ.
7. **Dream-created fact origin and confidence.** Whether dream facts need their own `origin`, and whether corroboration (`seen`) should ever grow from a re-run; the scenarios only require that it does not.
8. **Reprocessing.** Whether a flag should let a user re-run a batch from an earlier checkpoint.
