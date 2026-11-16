# hermes-relatedb

Bi-temporal Entity-Episode-Fact `MemoryProvider` for [Hermes Agent](https://github.com/NousResearch/hermes-agent), backed by embedded [`relate-db`](https://pypi.org/project/relate-db/) and local [`model2vec`](https://pypi.org/project/model2vec/) embeddings.

---

## Background

Most agent memory backends store flat notes or overwrite key-value pairs in place. When a fact changes—a project owner rotates, a preference shifts, or an earlier claim is corrected—overwriting destroys what the agent previously knew and why.

`hermes-relatedb` models memory as a **bi-temporal property graph** with three node kinds:

- **`Entity`** (`key`, `name`, `kind`): A canonical subject the agent talks about (e.g. `project_slug:hermes-relatedb`, `note_id:202611160900`).
- **`Episode`** (`id`, `source`, `recorded_at`): A source event such as a chat turn or memory write that introduced or updated knowledge.
- **`Fact`** (`id`, `slot`, `text`, `valid_from`/`valid_to`, `recorded_at`/`closedAt`, `embedding`): A timestamped claim linked via `(:Fact)-[:FROM]->(:Episode)` and `(:Fact)-[:ABOUT]->(:Entity)`.

Updating a `slot` (for example `project/owner`) closes the active `Fact` and links the replacement with `[:SUPERSEDES]` instead of deleting history. This lets the agent answer both *"what is true now?"* and *"what did we believe on date T?"* while tracing every claim back to its source episode.

### Architecture

- **In-process graph engine**: `relatedb_memory.store` embeds `relate-db` directly on a dedicated single-writer worker thread with a bounded queue, avoiding subprocess overhead per profile while enforcing RelateDB's single-writer rule.
- **Local CPU embeddings**: `relatedb_memory.embedder` computes 256-dimensional vectors locally using `model2vec` (`minishlab/potion-science-8M` by default), so personal memory never leaves the machine after the initial model download.
- **Pluggable storage formats**: Stores persist as a Parquet directory (default), a git-diffable JSON directory store, or a single `.rl` file.

---

## Pros and Cons

### Pros

- **Non-destructive bi-temporal history**: Corrections close prior facts rather than overwriting them, enabling `relatedb_as_of` point-in-time audits and `relatedb_provenance` lineage queries.
- **Local-first and private**: Runs embedded `relate-db` and CPU-only `model2vec` with no external database server, no hosted embedding API, and no API keys.
- **Multi-profile isolation**: Each Hermes profile resolves its own store and settings from its `HERMES_HOME` and scoped environment variables.
- **Git-friendly option**: The `json` directory codec (`graph.json`, `manifest.json`, `wal/`) pairs with `jq` textconv so learned facts produce readable `git diff`s and idempotent replays produce zero diff.
- **Read-only Cypher and MCP sidecar**: Inspect memory directly via `relatedb_cypher`, `hermes relatedb cypher`, or a live read-only stdio MCP server (`relate serve --mcp stdio --read-only=live`).

### Cons and Trade-offs

- **Static embedding quality**: `model2vec` is fast and runs on CPU without a GPU, but its static embeddings have lower semantic nuance than large hosted embedding models.
- **Fixed vector dimension per store**: Changing `embedding_model` to a model with a different dimension triggers a `DimensionMismatchError` until the store is recreated or re-embedded.
- **Single-writer concurrency**: Writes serialize through a bounded in-process worker queue; external processes cannot open the same store for writing concurrently.
- **Python 3.12+ requirement**: Requires Python `>=3.12` and `relate-db >= 1.0.1`.

---

## Installation

### Prerequisites

- **Python** `>= 3.12`
- **`uv`** (recommended for dependency management)
- **`jq`** (optional, for readable `git diff`s on JSON directory stores)

### 1. Install Dependencies

Clone the repository and sync dependencies:

```sh
git clone https://github.com/loheander/hermes-relatedb.git
cd hermes-relatedb
make sync      # runs `uv sync` for local development/tests
make install   # copies the plugin into all existing Hermes profile directories
```

### 2. Register with Hermes Agent

Hermes discovers `hermes-relatedb` in either of two ways:

1. **Plugin directory** (recommended for local checkouts): Place or symlink the repository at `$HERMES_HOME/plugins/relatedb`. Hermes loads `__init__.py`, which registers `RelateDBMemoryProvider` and the bundled `skills/relatedb-memory/SKILL.md` skill.
2. **Python entry point**: Installing the package into Hermes's Python environment exposes the `hermes_agent.memory_providers` entry point (`relatedb = "relatedb_memory.provider:RelateDBMemoryProvider"`).

Once enabled, Hermes invokes `RelateDBMemoryProvider` for background `sync_turn`, `prefetch`, `on_memory_write` mirroring, and `on_pre_compress`, and exposes six agent tools:

- `relatedb_remember(text, slot, about?, valid_from?)`
- `relatedb_recall(query, k?)`
- `relatedb_forget(slot? | fact_id?)`
- `relatedb_as_of(slot, on)`
- `relatedb_provenance(slot? | fact_id?)`
- `relatedb_cypher(query, params?)` (read-only)

### 3. Configuration

Settings resolve in the following order (highest precedence first):

1. Scoped environment variable
2. `memory.relatedb` mapping in `<hermes_home>/config.yaml`
3. Default value

| Key | Env var | Default | Description |
| --- | --- | --- | --- |
| `snapshot_format` | `RELATEDB_SNAPSHOT_FORMAT` | `parquet` | Store persistence format: `parquet` (directory), `json` (diffable directory), or `rl` (single file) |
| `db_path` | `RELATEDB_DB_PATH` | `<hermes_home>/memory/` (or `<hermes_home>/memory.rl` for `rl`) | Store path; relative paths resolve against `hermes_home` (must be a directory for `parquet`/`json`, or a `.rl` file for `rl`) |
| `embedding_model` | `RELATEDB_EMBEDDING_MODEL` | `minishlab/potion-science-8M` | `model2vec` model used for local vector recall (256-dim by default) |
| `prefetch_top_k` | `RELATEDB_PREFETCH_TOP_K` | `8` | Maximum facts injected on turn prefetch |
| `auto_extract` | `RELATEDB_AUTO_EXTRACT` | `true` | Extract facts from conversation turns in the background |

Configure these interactively via `hermes memory setup` or the Hermes Dashboard plugins panel (`config_schema.py`), or edit `<hermes_home>/config.yaml`:

```yaml
memory:
  relatedb:
    snapshot_format: parquet
    db_path: memory/
    prefetch_top_k: 8
    auto_extract: true
```

`is_available()` returns `false` (with an install hint from `unavailable_reason()`) when neither the `relate` Python module nor the `relate` CLI is present.

---

## CLI Reference

The `cli.py` entry point powers `hermes relatedb` (and can also be invoked directly with `uv run python cli.py <subcommand>`). All commands emit structured JSON to `stdout`.

When `--path` is omitted, commands resolve the active profile's store path from `HERMES_HOME` (defaulting to `~/.hermes`) and `relatedb_memory.config.resolve_config()`.

### `hermes relatedb init-diffable [path]`

Initialize a git-friendly JSON directory store (`graph.json`, `manifest.json`, `wal/`), append `graph.json diff=relate-json` and `*/graph.json diff=relate-json` to `.gitattributes`, and set `git config diff.relate-json.textconv "jq ."`.

- **Arguments**:
  - `path` (optional, default: `./memory`): Target store directory.
- **Example**:

```sh
hermes relatedb init-diffable ./memory
```

### `hermes relatedb status [--path PATH]`

Print the resolved store path, detected codec (`rl`, `parquet`, or `json`), total node and relationship counts, and active vs. closed `Fact` counts.

- **Options**:
  - `--path PATH`: Override the resolved store path.
- **Example**:

```sh
hermes relatedb status --path ./memory
```

### `hermes relatedb verify [--path PATH]`

Verify bi-temporal slot-uniqueness invariants (no `slot` may have more than one open `Fact` where `closedAt IS NULL`). Exits `0` with `{"ok": true, "violations": []}` when valid, or `1` with offending slots when violated.

- **Options**:
  - `--path PATH`: Override the resolved store path.
- **Example**:

```sh
hermes relatedb verify --path ./memory
```

### `hermes relatedb cypher "<QUERY>" [--path PATH]`

Execute a read-only Cypher query against the store. Mutating keywords (`CREATE`, `MERGE`, `SET`, `DELETE`, `DETACH`, `REMOVE`, `DROP`, `LOAD`) and multi-statement queries are rejected.

- **Arguments**:
  - `query`: Read-only Cypher query string.
- **Options**:
  - `--path PATH`: Override the resolved store path.
- **Example**:

```sh
hermes relatedb cypher "MATCH (f:Fact) WHERE f.closedAt IS NULL RETURN f.slot, f.text LIMIT 10"
```

### `hermes relatedb mcp [--path PATH] [--read-only] [--launch]`

Print the JSON configuration for a zero-code `relate serve --mcp stdio` sidecar, or launch it directly.

- **Options**:
  - `--path PATH`: Override the resolved store path.
  - `--read-only`: Pass `--read-only=live` to `relate serve` so the MCP server can safely read alongside an active writer.
  - `--launch`: Execute `relate serve --mcp stdio ...` directly instead of printing the client config JSON.
- **Examples**:

```sh
# Print MCP client config JSON
hermes relatedb mcp --path ./memory --read-only

# Or run the sidecar directly without Python provider code
relate serve --mcp stdio --database ./memory --read-only=live
```

---

## Contributing

Contributions are welcome. This repository tracks architectural decisions and specifications in a committed Relate context graph (`docs/context-graph/`) alongside the code.

### 1. Run Tests

```sh
make sync
make test
```

`make test` runs the full `pytest` and `pytest-bdd` suite under `tests/`.

### 2. Check Active ADRs and Specs

Before modifying architecture or storage behavior, query the decision context graph (always read-only so the working tree stays clean):

```sh
# Active decisions (Accepted and not fully superseded)
uv run python tools/index_specs.py --query active-adrs

# Supersession chain from an ADR
uv run python tools/index_specs.py --query chain --target ADR-0005

# Active ADRs governing a module
uv run python tools/index_specs.py --query blast --target relatedb_memory.store
```

See `AGENTS.md` for MCP query instructions and ADR formatting rules.

### 3. Refresh the Context Graph (When Changing ADRs, Specs, or Docstrings)

If your change adds or edits `docs/adr/*.md`, `specs/*.md`, or module docstrings, refresh the committed context graph and stage it:

```sh
make index-specs   # runs `make setup-git` and re-indexes idempotently
python tools/index_specs.py --check
git add docs/context-graph
```

### 4. Pull Request Checklist

- Keep commits atomic and the working tree clean.
- Ensure `make test` passes.
- Ensure `python tools/index_specs.py --check` passes if ADRs, specs, or module docstrings were touched.

---

## License

[MIT](LICENSE)
