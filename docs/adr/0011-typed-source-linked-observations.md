# ADR-0011: Typed, source-linked observations derived from captured turns

- Status: Proposed
- Date: 2026-11-22
- Relates to: ADR-0001, ADR-0007, ADR-0008

## Context

Dream Mode (#33) reads captured episodes with an LLM. Captured turns mix what the user said, what the assistant inferred, questions, hypotheticals and real decisions. Storing all of it as plain facts would let "Maybe we should use Postgres" read as a decision on recall. The requester's constraints: types must survive storage and show in recall, the user's own words must outrank an assistant's interpretation of them, every observation must be traceable to evidence, originals are never modified, re-runs add nothing, and text inside an episode is data, never instructions.

The e2e scenarios in `tests/e2e/features/dream_observations.feature` (tagged `@pending_57`) express the behaviour. This ADR records the proposed decisions and the questions the scenarios cannot settle. It does not depend on the run lifecycle ADR (ADR-0009, itself Proposed): the scenarios assume only that each derivation leaves one `DreamRun` node with a `rejected` list.

## Decision

### Type set

An observation has one `kind`: `statement` (something a speaker asserted), `interpretation` (an inference about what was said), `question`, `assumption` (a hypothetical or unconfirmed premise) or `decision` (a choice the user confirmed). It also has a `speaker`, `user` or `assistant`: whose words or inference it records.

### Mapping onto `Fact`

Both a label and properties. An observation is a `:Fact` that also carries the label `:Observation`, with properties `kind`, `speaker`, `support` and `origin: "dream"`. Rationale:

- It reuses the existing fact vector index, recall path, bi-temporal fields and supersession (ADR-0001) without a second search path.
- The extra label lets queries and the schema scenario separate observations from deliberate and captured facts without comparing property values.
- `kind` is a property, not a label per type, so adding a type is a data change and a type is never confused with an episode kind.

`FACT_ORIGINS` gains `dream` as a third class beside deliberate and captured origins.

### Sources

`(:Observation)-[:DERIVED_FROM]->(:Episode | :Fact)`, at least one link, every target existing and, for a fact, open. `support` is the number of distinct source episodes: a fact source counts through its own `FROM` episode. Episodes never close, so a closed source can only be a fact.

### Proposal schema

The model may return only `{"observations": [{"kind", "speaker", "text", "derived_from"}]}`: the five kinds, the two speakers, non-empty `text`, non-empty `derived_from` of existing ids. The schema is closed: an extra field, an unknown kind or speaker, a missing or closed source, or an item that is not an observation (a free-form tool call, say) rejects that item only. Rejected items are recorded in the `DreamRun` as `{"reason", "proposal"}`; the rest of the batch is handled normally. Nothing in the schema can close, retract, rewrite or delete a fact or episode, so a model that follows quoted text cannot cause such a write.

Episode text reaches the model only as input data, never in `instructions` or the system prompt. A `decision` must have `speaker: "user"`: an assistant cannot make a decision on the user's behalf, and a suggestion the user has not accepted is an `assumption`. This is a plugin check, not a model instruction.

### Idempotence

An observation id is derived from `(kind, speaker, normalised text, sorted source ids)`, and the write is a merge, so identical output creates nothing. Summaries of evidence that is already cited must not add support: a proposal whose `kind`, `speaker` and set of source episodes match an existing observation is treated as the same observation and discarded, whatever its wording. `support` counts distinct source episodes only, so a rewording of the same evidence leaves it unchanged. Derivation never writes to an `Episode` or a non-observation `Fact`.

### Recall

Observations are recalled through the same vector search and are printed with `kind=<type>` and `speaker=<who>`. Ranking against deliberate memories (ADR-0007): observations are neither deliberate nor captured, so they take their own share cap, `observation_share` (proposal: `0.25` of `k`), after deliberate facts. Within observations, user-speaker observations sort ahead of assistant-speaker ones at any similarity, so an interpretation never outranks the words it interprets. An `assumption` or `question` is never presented as a decision.

### Duplicate flagging (ADR-0008)

Observations take part in duplicate flagging only against observations of the same `kind`: "should we use Postgres?" and "we use Postgres" are near in embedding space and must not collapse. A duplicate observation counts toward `seen` by distinct source episodes, as ADR-0008 does for facts.

## Consequences

- A hypothetical, a question and a confirmed decision stay distinguishable in storage and in the recall block.
- Observations are traceable: every one answers "what did you read to conclude this".
- The graph schema scenario (`memory_schema.feature`) lists labels and relationships exhaustively and must gain `Observation`, `DreamRun` and `DERIVED_FROM` in the implementing story.
- The closed schema costs flexibility: a useful but unforeseen output kind is rejected until the schema is extended by a new ADR.
- Collapsing proposals by evidence set can hide a genuinely different observation derived from the same episodes with the same kind and speaker. The kind and speaker bound that risk.

## Open questions

The scenarios fix none of these.

1. **Type change: supersession or new observation.** If a later episode turns an `assumption` into a `decision`, either the decision supersedes the assumption (same slot, the assumption closes, history stays bi-temporal) or both exist and the decision links to the assumption. Supersession keeps recall short; a new observation keeps the audit trail without relying on bi-temporal queries. Proposal: supersede, with a `SUPERSEDES` link.
2. **Slots.** Whether observations get slots at all. Without slots nothing supersedes them and a changed mind accumulates; with model-chosen slots the model controls what closes, which sits badly with a closed schema.
3. **Observation share default.** `0.25` is a guess; it needs a corpus.
4. **Whether `decision` may be derived from an assistant turn alone** when the user's next turn accepts it. The proposal above says no, which means a decision needs a user turn as a source.
5. **How the proposal schema is expressed to the host** (`json_schema` against `json_mode`), and whether the host validates it before the plugin does.
6. **Reprocessing after a prompt or schema change.** Idempotence by evidence set means an improved prompt cannot refine existing observations without a new `kind` or an explicit reprocess flag.
7. **Entry point name.** The scenarios assume `relatedb_memory.dream.derive_observations(ctx, *, embedder=None)`; the real wiring (idle task, CLI command) belongs to the lifecycle story.
