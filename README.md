
## Development

- `make install` syncs the environment with `uv`.
- `make test` runs the test suite.
- Hermes discovers the plugin from this directory (`$HERMES_HOME/plugins/relatedb`) or via the `hermes_agent.memory_providers` entry point.
- `make index-specs` refreshes the committed ADR/spec context graph in `docs/context-graph/`; `make setup-git` makes its diffs readable. See `AGENTS.md`.

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
