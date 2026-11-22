# ADR-0010: Dream Mode model routing and transparency

- Status: Proposed
- Date: 2026-11-22
- Relates to: #33 (Dream Mode), #56

## Context

Dream Mode sends conversation excerpts to a language model to propose consolidations. Inference goes through Hermes (`ctx.llm.complete_structured`); the plugin owns no client and no keys. The requester's constraints are an explicit Dream Mode model choice and visibility of which provider and model receives the excerpts. A cloud provider already configured in Hermes is acceptable once chosen explicitly. Local-only is an option, not a requirement.

The harness models `ctx.register_auxiliary_task` and the `task=` argument of `complete_structured`. It does not model the user's Hermes configuration or the Hermes fallback chain.

## Decision

- **Dedicated slot.** The plugin registers one auxiliary task, key `relatedb_consolidation` (config path `auxiliary.relatedb_consolidation`), through `register_auxiliary_task` at registration time. Every Dream call passes `task="relatedb_consolidation"`. No Dream call uses the main chat model.
- **No inheritance.** The slot is registered without `inherit_from` and without a default provider or model. If the user has not set a provider and model for it, `dream` refuses before any call, exits non-zero, and names the slot and how to set it. This holds even when a chat model is configured.
- **Visibility.** `dream --dry-run` and `dream --status` print the slot key and the resolved provider and model, and send nothing. When the slot is unset they say that no model is chosen. A real run prints the same line in its report.
- **No fallback.** A failed call is not retried on another model. After the bounded retries on the same model, the run fails, exits non-zero and records the failure (error text, provider, model, time). `dream --status` shows the last failure. Nothing is written to the store as a proposal.
- **Timeout and retry.** Each call carries the configured timeout (`--timeout`, seconds). A timeout or transient provider error is retried on the same slot up to `--retries` times, so a run makes at most `1 + retries` calls. A run with `--retries 0` makes one.
- **Local and cloud are equal.** The plugin does not branch on the provider. A slot that resolves to a local model passes the same scenarios as a cloud one.
- **Excerpts only.** The batch is the oldest `--limit` unprocessed episodes. They go in `input` as mappings with `id` and `text`, never interpolated into `instructions` or `system_prompt`. No stored facts, entities or other episodes are sent beyond what the proposal schema needs.
- **Out of scope by decision.** Logging the exact data sent and received, and cost or usage accounting. Hermes core, OpenTelemetry, a logging proxy or a separate Hermes plugin cover those.

## Open questions the scenarios cannot settle

1. **Slot name and registration.** Is `relatedb_consolidation` the final key, and is registration in `register(ctx)` or lazily at first `dream`?
2. **Fallback chain.** Can the plugin bypass the Hermes fallback chain for this slot? If Hermes applies a configured fallback inside `complete_structured`, the plugin cannot see it. Either Hermes offers a per-call opt-out, or the run must refuse when a fallback is configured for the slot. The scenarios assume the plugin observes one call per attempt and that none lands on another model; the harness does not model the chain.
3. **How the resolved model is read.** The scenarios simulate the user's choice through the registered task's `defaults`. The real source (Hermes config, or a host API that resolves a task to provider and model) must be confirmed, including whether a lookup can send nothing.
4. **Batch selection.** The scenarios use "the `--limit` oldest episodes". The real rule belongs with the proposal and review design (#55) and may replace this.
5. **Retry classification.** Which errors count as transient besides timeouts, and whether to back off between attempts.
6. **CLI seam.** The scenarios call `cli.main(argv, ctx=ctx)`. The real CLI may receive the context differently.

## Consequences

- Dream Mode cannot start by accident on the chat model or a paid fallback, and the user can inspect the target before any excerpt leaves the machine.
- The plugin depends on Hermes exposing the resolved slot and, ideally, a no-fallback option. Without it, question 2 forces refusal when a fallback is configured.
- Data-sent auditing and cost accounting are left to other layers.
