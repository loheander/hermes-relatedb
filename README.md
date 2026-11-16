
## Development

- `make install` syncs the environment with `uv`.
- `make test` runs the test suite.
- Hermes discovers the plugin from this directory (`$HERMES_HOME/plugins/relatedb`) or via the `hermes_agent.memory_providers` entry point.
- `make index-specs` refreshes the committed ADR/spec context graph in `docs/context-graph/`; `make setup-git` makes its diffs readable. See `AGENTS.md`.
