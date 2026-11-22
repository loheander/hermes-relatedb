# ADR-0014: Pattern inference as labelled inference

- Status: Proposed
- Date: 2026-11-22
- Amends: ADR-0001
- Related: #33 (Dream Mode), #60, ADR-0011 (typed observations, in review), ADR-0012 (corrections, in review), ADR-0013 (scoped decisions, in review)

## Context

Across conversations, the same tendency can recur without the user ever stating it ("wants the migration plan before the code"). Surfacing it helps recall, but a pattern is a guess. It must not be mistaken for a fact, must not turn into an instruction through repetition, and must lose to anything the user says explicitly.

ADR-0011, ADR-0012 and ADR-0013 are Proposed and not yet agreed; this ADR refers to them by number and only assumes what the scenarios state: a typed observation is a fact whose source episode it cites. Nothing here is implemented. The scenarios in `tests/e2e/features/dream_pattern_inference.feature` (tagged `@pending_60`, strict xfail) define the observable behaviour.

## Decision (proposed)

**Node shape.** A pattern is a `:Fact` with `kind = 'pattern'` in the slot `pattern/<topic>`. Reusing `:Fact` keeps embeddings, the vector index and bitemporal supersession (ADR-0001), so history and audit come for free. A pattern never shares a slot with a statement or decision, and its `kind` is set at creation and never rewritten, so repetition cannot promote it.

**Sources.** Each pattern has `DERIVED_FROM` edges to its supporting observation facts and to the episodes those observations cite.

**Support.** Support is computed by the code, never taken from the model: the number of distinct source episodes of the open (not superseded) observations the model cites. Several observations from one episode count once, and a summary observation cites the episode it summarises, so it adds nothing. A pattern is proposed only when support reaches `dream_pattern_min_episodes` (`RELATEDB_DREAM_PATTERN_MIN_EPISODES`, default 3). A later pass that finds more episodes raises `support` on the open pattern in place, without a version row; the scenarios only look at open rows.

**Uncertainty.** Uncertainty is the source count shown with an explicit label, not a score the model invents. Recall renders `Inference (not confirmed, N sources): <text>`. The label sits in front of the text and uses no imperative wording.

**Pass.** `dream.register(ctx, provider)` registers a second idle task, `relatedb-dream-patterns`, only when pattern inference is on. It calls `ctx.llm.complete_structured` once and receives `{"patterns": [{"topic", "text", "evidence": [observation ids]}], "retire": [{"pattern", "statement"}]}`.

**Read seam.** `provider.dream_proposals()` is the `USER.md` proposal list proposed in ADR-0013 (in review, not on main); a pattern never appears in it.

**Pattern list.** `provider.dream_patterns(include_closed=False)` lists `{"id", "topic", "text", "type": "pattern", "status", "support", "sources"}`.

**Never an instruction.** A pattern is not mirrored to `USER.md`, creates no `dream_proposals()` entry, and is excluded from `system_prompt_block()`. It reaches the model only through `prefetch`, as a labelled inference.

**Retirement.** A pattern is closed (its `closedAt` is set; it is never deleted) when (a) the pass reports that an explicit user statement contradicts it, and the code confirms the statement is a user-authored fact rather than a pattern or observation, or (b) its support, recomputed at the start of every pass without a model call, drops below the minimum because supporting observations were superseded. Closed patterns keep their `DERIVED_FROM` edges and stay readable through `relatedb_as_of`.

**Own opt-in.** `dream_patterns` (`RELATEDB_DREAM_PATTERNS`) is separate from `dream`. With it off, no pattern task is registered and no pattern call is made, while observation extraction continues. Default: off, because a pattern is the most speculative output of Dream Mode.

**Ranking in recall.** Patterns use the existing fact ranking and, like captured facts under ADR-0007, are capped to a share of `k` so they cannot crowd out deliberate facts. The scenarios do not fix the share.

## Open questions

- How should uncertainty be shown to the model without it reading as a rule? The fixed label is a first guess; wording is the review surface.
- Should a pattern ever be shown to the user for confirmation? If confirmed, it would become an explicit statement and leave this ADR's scope.
- Is the retirement judgement (explicit statement contradicts pattern) safe to leave to the model, with only the statement's origin checked in code?
- Should the default minimum be 3 episodes, and should it also require a minimum time span between them?
- Is pattern text from the model sanitised against imperative phrasing, or only labelled?
- Should the pattern cap share be fixed or configurable?
- Does a pattern valid in one scope (ADR-0013) stay within that scope?

## Consequences

- No new schema beyond `kind = 'pattern'` and `DERIVED_FROM` edges.
- The scenarios pin seam names (`relatedb-dream-patterns`, `dream_patterns`, `RELATEDB_DREAM_PATTERNS`, the `Inference (...)` label with `N sources`); if review changes them, the step module changes with them.
- Observations are modelled as facts in `observation/<id>` slots until ADR-0011 is agreed; the step module changes with it.
- Closing instead of deleting keeps patterns auditable at the cost of a growing history.
