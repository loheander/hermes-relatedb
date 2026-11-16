# hermes-relatedb

Bi-temporal Entity-Episode-Fact memory provider for Hermes Agent, backed by embedded `relate-db` and local `model2vec` embeddings.

## Installation & Native MemoryProvider Usage

- Install dependencies: `make install` (or `uv sync`).
- Hermes discovers the plugin from `$HERMES_HOME/plugins/relatedb` (`__init__.py` registers `RelateDBMemoryProvider` and the `skills/relatedb-memory/SKILL.md` skill) or via the `hermes_agent.memory_providers` entry point.
- Once enabled, Hermes invokes `RelateDBMemoryProvider` for background `sync_turn`, `prefetch`, `on_memory_write` mirroring, `on_pre_compress`, and exposes the `relatedb_remember`, `relatedb_recall`, `relatedb_forget`, `relatedb_as_of`, `relatedb_provenance`, and read-only `relatedb_cypher` tools.

## Configuration

Each Hermes profile gets its own store, resolved from the `hermes_home` that
Hermes passes to `initialize()`. Settings resolve in this order: scoped
environment variable, `memory.relatedb` in `<hermes_home>/config.yaml`, default.

| Key | Env var | Default |
| --- | --- | --- |
| `snapshot_format` | `RELATEDB_SNAPSHOT_FORMAT` | `rl` (or `parquet`, `json` directory stores) |
| `db_path` | `RELATEDB_DB_PATH` | `<hermes_home>/memory.rl`, or `<hermes_home>/memory/` for directory formats; relative paths resolve against `hermes_home` |
| `embedding_model` | `RELATEDB_EMBEDDING_MODEL` | `minishlab/potion-science-8M` |
| `prefetch_top_k` | `RELATEDB_PREFETCH_TOP_K` | `8` |
| `auto_extract` | `RELATEDB_AUTO_EXTRACT` | `true` |

Set them with `hermes memory setup` or the Dashboard plugins panel
(`config_schema.py`). `is_available()` is false, with an install hint from
`unavailable_reason()`, when neither the `relate` module nor the `relate` CLI is
present.

## Diffable JSON Store & Git Workflow

Initialize a git-friendly JSON directory store (`graph.json`, `manifest.json`, `wal/`):

```sh
hermes relatedb init-diffable ./memory
```

This creates the JSON-codec Relate store, adds `graph.json diff=relate-json` to `.gitattributes`, and configures `git config diff.relate-json.textconv "jq ."`, so every session's learned facts appear as readable multi-line `git diff`s and idempotent `MERGE` replays produce zero diff.

## CLI Commands (`hermes relatedb`)

- `hermes relatedb init-diffable [path]` — initialize a diffable JSON store and git textconv config
- `hermes relatedb status [--path PATH]` — print store path, codec, node/relationship counts, and active/closed fact counts
- `hermes relatedb verify [--path PATH]` — verify bi-temporal slot-uniqueness invariants (exits non-zero on violation)
- `hermes relatedb cypher "<QUERY>" [--path PATH]` — run a read-only Cypher query
- `hermes relatedb mcp [--path PATH] [--read-only] [--launch]` — print or launch the stdio MCP sidecar

## Zero-Code MCP Sidecar

To expose an existing Relate memory store over stdio MCP without running the Python provider:

```sh
relate serve --mcp stdio --database ./memory --read-only=live
```

Or generate the MCP client config via `hermes relatedb mcp --path ./memory --read-only`.

## Development

- `make install` syncs the environment with `uv`.
- `make test` runs the test suite.
- `make index-specs` refreshes the committed ADR/spec context graph in `docs/context-graph/`; `make setup-git` makes its diffs readable. See `AGENTS.md`.
