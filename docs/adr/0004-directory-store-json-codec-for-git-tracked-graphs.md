# ADR-0004: Directory store with JSON codec for git-tracked graphs

- Status: Accepted
- Date: 2026-11-16

## Context

The repository indexes its own ADRs and specs in a Relate graph so agents can
retrieve active constraints (see `specs/context-graph.md`). A single-file `.rl`
store is opaque binary in git, produces unreviewable diffs, and blocks
concurrent readers while a writer holds it.

## Decision

The context graph lives in the directory store `docs/context-graph/`,
created with the `json` snapshot codec (`RELATE_SNAPSHOT_FORMAT=json`, the
`--snapshot-format json` CLI option). `graph.json` is text, so
`.gitattributes` marks it `diff=relate-json` and `make setup-git` configures
`git config diff.relate-json.textconv "jq ."`. A directory store also allows
live read-only access (`--read-only=live`) alongside a writer.

## Consequences

- Graph changes are reviewable in `git diff`.
- The indexer in `tools/index_specs.py` must be idempotent so a run without
  Markdown changes leaves the working tree clean.
- Runtime memory stores (ADR-0002) are not git-tracked and are unaffected.
