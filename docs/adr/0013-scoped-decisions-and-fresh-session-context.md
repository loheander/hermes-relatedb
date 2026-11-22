# ADR-0013: Scoped decisions and fresh-session context for Dream Mode

- Status: Proposed
- Date: 2026-11-22
- Amends: ADR-0001
- Related: #33 (Dream Mode), #42 (USER.md and MEMORY.md mirroring), #59

## Context

Dream Mode consolidates what happened in past sessions. A fresh session should pick up the latest confirmed decision in the right project, without the user repeating it, without a stale summary, and without one project's choices leaking into another. `USER.md` is already the compact always-present profile, so Dream Mode must not keep a second profile: it proposes updates through the existing Hermes memory approval flow.

The scenarios in `tests/e2e/features/dream_scoped_context.feature` (tagged `@pending_59`, strict xfail) define the observable behaviour. This ADR proposes the mechanism they bind to and lists what they cannot settle. Nothing here is implemented.

## Decision (proposed)

**Scope representation.** A scope is a short string such as `project-a`. Decisions are facts in the slot `dream/<scope>/<topic>`, so the existing bitemporal supersession (ADR-0001) gives "latest wins within a scope" and keeps the earlier decision readable through `relatedb_as_of`. Durable personal preferences have no scope and are never stored under `dream/`.

**Scope detection.** The session declares its scope through metadata: `provider.initialize(..., project="<scope>")`. During a Dream Mode pass the model proposes a scope per observation (`null` for a personal preference), and the proposal is trusted in this phase: the model's scope is used as given. Validating it against session metadata is an open question.

**Bitemporal stamps.** Dream Mode derives `valid_from` and `recorded_at` of a decision from the source episode that the observation cites (here the newest episode not yet consolidated), never from the wall clock. A later decision in the same slot therefore closes the earlier one at its own `valid_from`, and `relatedb_as_of` answers "what held on 3 March". Re-reading an already consolidated episode produces no new fact.

**Scope selection at recall.** `prefetch` for a session with a scope returns facts in that scope plus unscoped facts, and no facts from another scope. Dream Mode off leaves recall unchanged. A superseded decision must not appear in the recalled text: for facts in a `dream/` slot, `prefetch` omits the `replaces=<old text>` annotation that Phase 1 appends to a superseding fact (the earlier decision stays readable through `relatedb_as_of`). Facts outside `dream/` keep the Phase 1 format, so recall with Dream Mode off is unchanged.

**Pass.** `dream.register(ctx, provider)` registers one idle task, `relatedb-dream`, which reads recent episodes, calls `ctx.llm.complete_structured` once and receives `{"observations": [{"scope", "kind", "topic", "text"}]}` with `kind` one of `decision` or `preference`. Decisions are written as scoped facts. Preferences become proposals.

**USER.md proposals.** `provider.dream_proposals()` lists `{"id", "target": "USER.md", "text", "status"}`; `provider.approve_dream_proposal(id)` is the only path that writes `USER.md`, so an unapproved proposal leaves the file unchanged. On approval the text is also mirrored as an unscoped fact through the `on_memory_write` path (#42), which is how an approved preference reaches `prefetch` in every scope; `prefetch` itself does not read `USER.md`. A project decision is never turned into a proposal.

**Context size budget.** The maintained context per scope (`provider.dream_context()`) is capped at `dream_context_chars` (`RELATEDB_DREAM_CONTEXT_CHARS`, default 2000). Over budget, the oldest and least recently recalled entries are dropped from the context; the facts themselves stay in the store.

**Config.** `dream` (`RELATEDB_DREAM`) turns the feature on or off. Off means no idle task, no model call, and recall identical to Phase 1.

## Open questions

- What does a session with no clear project scope see: only unscoped facts, or every scope ranked by similarity?
- Can the user correct a scope after the fact (move a decision to another project), and through which surface (CLI, tool, or editing the proposal)?
- Is `project=` metadata available from Hermes at `initialize`, or must scope be inferred from the working directory?
- Should the default budget count characters or tokens?
- Should the model's scope be validated against session metadata, and what counts as a known scope?
- Are `USER.md` proposals deduplicated against facts already in `USER.md`, and by what comparison?

## Consequences

- Reuses bitemporal slots instead of a new schema, so history and audit come for free.
- The scenarios pin seam names (`dream.register`, `dream_proposals`, `approve_dream_proposal`, `dream_context`, `project=`); if review changes them, the step module changes with them.
- Recall formatting changes only for `dream/` facts (no `replaces=` annotation); the scenarios 'latest decision' and 'fresh session' assert the superseded text is absent from the whole recalled block.
- Unresolved scope detection means early implementations may need an explicit `project=` and fall back to unscoped recall.
