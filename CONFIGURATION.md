# Configuration

Every setting of the `relatedb-memory` provider, with its default, accepted values and effect. The defaults suit most people.

## Where settings come from

Highest precedence first:

1. **Environment variable** (`RELATEDB_*`, listed per setting below). A blank value counts as unset.
2. **`config.yaml`**: the `memory.relatedb-memory` mapping in `<hermes_home>/config.yaml`.
3. **Built-in default.**

Each Hermes profile has its own `hermes_home`, so each profile has its own settings and its own store.

Edit the file by hand or run `hermes memory setup relatedb-memory`:

```yaml
memory:
  provider: relatedb-memory
  relatedb-memory:
    snapshot_format: parquet
    db_path: memory/
    embedding_model: BAAI/bge-small-en-v1.5
    prefetch_top_k: 8
    auto_extract: true
    captured_share: 0.5
    dedupe: true
    dedupe_threshold: 0.92
    mirror_builtin_memory: true
```

An invalid value raises an error that names the setting, instead of silently falling back to a different store. Unknown keys in `config.yaml` are ignored.

**Booleans** accept `true`, `false`, `yes`, `no`, `on`, `off`, `1` and `0` (case-insensitive).

## Summary

| Setting | Default | Env variable | Group |
| --- | --- | --- | --- |
| [`snapshot_format`](#snapshot_format) | `parquet` | `RELATEDB_SNAPSHOT_FORMAT` | Storage |
| [`db_path`](#db_path) | `memory/` (`memory.rl` for `rl`) | `RELATEDB_DB_PATH` | Storage |
| [`embedding_model`](#embedding_model) | `BAAI/bge-small-en-v1.5` | `RELATEDB_EMBEDDING_MODEL` | Recall |
| [`prefetch_top_k`](#prefetch_top_k) | `8` | `RELATEDB_PREFETCH_TOP_K` | Recall |
| [`auto_extract`](#auto_extract) | `true` | `RELATEDB_AUTO_EXTRACT` | Recall |
| [`captured_share`](#captured_share) | `0.5` | `RELATEDB_CAPTURED_SHARE` | Recall |
| [`dedupe`](#dedupe) | `true` | `RELATEDB_DEDUPE` | Recall |
| [`dedupe_threshold`](#dedupe_threshold) | `0.92` | `RELATEDB_DEDUPE_THRESHOLD` | Recall |
| [`mirror_builtin_memory`](#mirror_builtin_memory) | `true` | `RELATEDB_MIRROR_BUILTIN_MEMORY` | Memory writes |

## Storage

### `snapshot_format`

How the store is persisted. One of:

- `parquet`: a directory of Parquet files. Compact.
- `json`: a directory of JSON files. Diffable in git (see [Keeping memory in git](README.md#keeping-memory-in-git)).
- `rl`: a single `memory.rl` file.

### `db_path`

Where the store lives. Relative paths resolve against the profile's `hermes_home`; `~` is expanded. The path must match the format:

- `parquet` and `json`: a directory. A path ending in `.rl`, or an existing file, is rejected.
- `rl`: a file ending in `.rl`. A path ending in a slash, or an existing directory, is rejected.

When unset, the store is `<hermes_home>/memory/` for `parquet` and `json`, and `<hermes_home>/memory.rl` for `rl`. Changing the format or path points the provider at a different store; it does not convert the old one.

## Recall

### `embedding_model`

The [`fastembed`](https://github.com/qdrant/fastembed) model used for local vector recall, computed on your CPU. Must not be empty. A store is bound to one vector dimension (384 for the default), so keep the same dimension for an existing store, or re-embed it with `tools/migrate_embeddings.py` (see [Upgrading and re-embedding existing stores](README.md#upgrading-and-re-embedding-existing-stores)).

### `prefetch_top_k`

How many facts are added to context before each turn. A positive integer.

### `auto_extract`

Extract facts from conversation turns in the background. Set to `false` to record only what is written deliberately (`relatedb_remember`, built-in memory writes).

### `captured_share`

The largest share of the recalled facts that *captured* facts may fill. A number from 0 to 1.

Each fact has an `origin`. Captured facts come from `turn` and `pre_compress`; deliberate facts come from `remember` and `memory_write`. Deliberate facts are always eligible; captured facts fill at most `captured_share` of `prefetch_top_k`. `0` excludes captured facts from recall, `1` removes the cap.

### `dedupe`

Flag near-duplicate facts on write, linking them with `DUPLICATE_OF` edges, and return one hit per duplicate cluster in recall, annotated `seen=N` (the number of distinct supporting episodes). `false` restores plain recall.

To link duplicates in a store that predates this setting, run `hermes relatedb-memory dedupe`. Add `--dry-run` to list the proposed links without writing. The pass is idempotent.

### `dedupe_threshold`

The cosine similarity at or above which two facts count as duplicates. A number from 0 to 1. Lower values merge more. Facts in different explicit slots are never merged.

## Memory writes

### `mirror_builtin_memory`

Whether Hermes built-in memory writes (`USER.md`, `MEMORY.md`) are mirrored into the graph, one fact per entry.

**Why you might turn it off.** Hermes already injects both files into every session, so a mirrored entry mostly duplicates what the agent already sees, and the mirror is a second copy that can drift. Turn the setting off to avoid that.

**What you give up.** History and `relatedb_as_of` queries over built-in entries: with the mirror off, the graph does not record when an entry was added, changed or removed.

**Behaviour when `false`:**

- `add`, `replace`, `patch` and `remove` on the built-in targets (`user`, `memory`) write no fact, close no fact and do not call the embedder.
- Writes to explicit slots, such as `prefs/editor`, still record facts as before.
- Facts that were already mirrored stay in the store and in recall until forgotten. Switching the setting off does not delete them.
- Switching it back on mirrors only new writes. Entries written while it was off are not backfilled, so re-add any you want in the graph (for example with `relatedb_remember`).

With the default `true`, behaviour is unchanged.

## Examples

Disable the mirror for one run without editing `config.yaml`:

```sh
RELATEDB_MIRROR_BUILTIN_MEMORY=false hermes
```

A diffable store with a smaller recall budget:

```yaml
memory:
  relatedb-memory:
    snapshot_format: json
    db_path: ~/notes/agent-memory
    prefetch_top_k: 5
```

## Dashboard

The Hermes dashboard shows the same settings, defined in `config_schema.py`. A test keeps its defaults in sync with `relatedb_memory/config.py`.
