# hermes-relatedb

A long-term memory provider for [Hermes Agent](https://github.com/NousResearch/hermes-agent) that remembers how facts change over time. Memory is stored as a local graph in [RelateDB](https://pypi.org/project/relate-db/) and searched with embeddings computed on your own CPU.

```sh
hermes plugins install loheander/hermes-relatedb
```

---

## Why use it

### Agent memory goes stale, and most backends forget that it did

An assistant that works with you for months keeps learning things that later stop being true. A project changes owner, you switch editors, a deadline moves, or the agent's first guess turns out to be wrong. Most memory backends store notes or key-value pairs and overwrite them in place. After the update the agent knows the new value but has lost the old one, when it changed, and where either came from.

That loss matters in practice:

- **"What did we decide last month?"** cannot be answered once the decision has been overwritten.
- **Contradictions pile up.** Without a notion of "this replaces that", stale notes and new notes are both recalled and the agent has to guess which one wins.
- **You cannot audit the agent.** When it states something wrong, you want to know which conversation it learned it from.

### What this plugin does differently

Every memory is a **fact** with a named **slot** (for example `project/owner` or `prefs/editor`), the **entities** it is about, and the **episode** (conversation turn or memory write) it came from. A new fact for a slot does not overwrite the old one. The old fact is closed and linked to its replacement. Each fact carries two timelines: when it was true in the world, and when the agent believed it.

This gives the agent, and you, four things that flat memory cannot provide:

| Question | Tool |
| --- | --- |
| What is true now? | `relatedb_recall` (semantic search over current facts only) |
| What did we believe on 1 March? | `relatedb_as_of` |
| Where did this come from, and what did it replace? | `relatedb_provenance` |
| Anything else about the memory graph | `relatedb_cypher` (read-only Cypher) |

Corrections become cheap and safe. The agent can update its beliefs freely because nothing is destroyed. Slot names stop contradictions from piling up because only one fact per slot is open at a time.

### Why RelateDB

A graph is the natural shape for memory: people, projects, notes and decisions connected by facts. RelateDB fits agent memory well because:

- **It is embedded.** There is no database server to run, secure or keep alive. The store is a directory (or a single file) under your Hermes profile, and the plugin loads it in-process.
- **Graph and vector search share one engine.** Semantic recall (`SEARCH` over embeddings) and structural queries (`MATCH` over entities and history) run against the same store. There is no second vector database to keep in sync.
- **You can query it with standard openCypher.** The memory is not a black box. You, the agent and other tools can read it with a well-known query language.
- **It speaks MCP.** `relate serve --mcp stdio --read-only=live` exposes the live memory to any MCP client (Claude Code, an IDE, another agent) without writing any code.
- **It can be version-controlled.** The optional JSON store format produces readable `git diff`s, so you can review what the agent learned the same way you review code.

### Private by default

Embeddings come from a small [`fastembed`](https://github.com/qdrant/fastembed) (`BAAI/bge-small-en-v1.5`, INT8 ONNX, 384 dimensions) model running on CPU without PyTorch. Apart from a one-time model download from Hugging Face, nothing leaves your machine. There is no hosted service, no API key and no GPU requirement.

### What it does on your machine

- **Network:** downloads the embedding model from Hugging Face the first time it runs. It makes no other network calls and sends no telemetry.
- **Files:** reads and writes only its store (`memory/` under your Hermes profile, or your `db_path`) and its `memory.relatedb-memory` section of `config.yaml`.
- **Background work:** one writer thread and short-lived recall and extraction threads inside the Hermes process. It starts no long-running processes.
- **Shell commands:** only when you run them yourself. `init-diffable` runs `git config` and edits `.gitattributes` in the target repository, and `mcp --launch` starts the `relate` binary.
- **Credentials:** none.

### Trade-offs

- `fastembed` (`BAAI/bge-small-en-v1.5`) runs locally on CPU; for even higher recall or different languages, you can configure another supported `fastembed` model.
- Only one Hermes process can write to a store at a time. Other processes can read it (`--read-only=live`).
- Each store is tied to one embedding dimension. Switching from an existing 256-dim `model2vec` store to the 384-dim `BAAI/bge-small-en-v1.5` default requires re-embedding the store with `tools/migrate_embeddings.py`.

---

## Install

### Requirements

- Hermes Agent 0.23.1 or newer, running on Python 3.12 or newer
- `jq` (optional, for readable diffs of JSON stores)

### 1. Install from GitHub

You do not need to clone anything. Hermes fetches the plugin straight from GitHub:

```sh
hermes plugins install loheander/hermes-relatedb
```

Hermes asks before it installs the Python dependencies (`relate-db`, `fastembed`, `pyyaml`). It then asks whether to use `relatedb-memory` as your memory provider. Answer **y**.

For an unattended install, or to install into a named profile:

```sh
hermes plugins install loheander/hermes-relatedb --yes-deps --enable
hermes -p <profile> plugins install loheander/hermes-relatedb
```

### 2. Activate and check

If you skipped the prompt, select the provider and configure it:

```sh
hermes memory setup relatedb-memory
```

Then confirm that it is active:

```sh
hermes memory status            # Provider: relatedb-memory, Status: available
hermes relatedb-memory status   # store path and fact counts
```

New sessions use the new memory. The first session downloads the embedding model.

### Update or remove

```sh
hermes plugins update relatedb-memory
hermes plugins remove relatedb-memory   # the memory store under your profile is kept
```

---

## Usage

You normally do nothing. Once active, the plugin works in the background:

- **Before each turn** it recalls the most relevant current facts and adds them to the agent's context.
- **After each turn** it extracts new facts from the conversation (turn off with `auto_extract: false`).
- **When Hermes writes built-in memory** (`MEMORY.md`/`USER.md`), the write is mirrored into the graph, one fact per entry. If you installed an earlier version, its mirrored `USER.md`/`MEMORY.md` facts were closed wrongly: re-add the entries that exist now (for example with `relatedb_remember`) and leave the history as it is.
- **Before Hermes compresses context**, the messages about to be summarised are saved as an episode, so nothing is lost.

The agent also gets these tools, and the bundled `relatedb-memory` skill teaches it how to use them:

| Tool | Purpose |
| --- | --- |
| `relatedb_remember(text, slot, about?, valid_from?)` | Store a fact. Supersedes the open fact in the same slot. |
| `relatedb_recall(query, k?)` | Semantic search over current facts. |
| `relatedb_forget(slot? \| fact_id?)` | Close a fact. Its history is kept. |
| `relatedb_as_of(slot, on)` | What was true, and what was believed, on a given date. |
| `relatedb_provenance(slot? \| fact_id?)` | Source episodes and supersession chain for a fact. |
| `relatedb_cypher(query, params?)` | Read-only Cypher over the whole graph. |

### Inspecting memory yourself

```sh
hermes relatedb-memory status            # path, format, node and fact counts
hermes relatedb-memory verify            # check that each slot has at most one open fact
hermes relatedb-memory cypher "MATCH (f:Fact) WHERE f.closedAt IS NULL RETURN f.slot, f.text LIMIT 10"
hermes relatedb-memory mcp --read-only   # print an MCP client config for the live store
```

Every command prints JSON and accepts `--path` to target a store other than the active profile's.

---

## Configuration

The defaults suit most people. To change them, run `hermes memory setup relatedb-memory` or edit `memory.relatedb-memory` in `<hermes_home>/config.yaml`:

```yaml
memory:
  provider: relatedb-memory
  relatedb-memory:
    snapshot_format: parquet   # parquet | json | rl
    db_path: memory/           # relative to the Hermes profile directory
    embedding_model: BAAI/bge-small-en-v1.5
    prefetch_top_k: 8
    auto_extract: true
```

| Key | Default | Meaning |
| --- | --- | --- |
| `snapshot_format` | `parquet` | `parquet`: compact directory. `json`: git-diffable directory. `rl`: single file. |
| `db_path` | `memory/` (`memory.rl` for `rl`) | Where the store lives. A directory for `parquet`/`json`, a `.rl` file for `rl`. |
| `embedding_model` | `BAAI/bge-small-en-v1.5` | Any `fastembed` model. Keep the same dimension for an existing store. |
| `prefetch_top_k` | `8` | How many facts are added to context before each turn. |
| `auto_extract` | `true` | Extract facts from conversation turns automatically. |

Each key can be overridden with an environment variable: `RELATEDB_SNAPSHOT_FORMAT`, `RELATEDB_DB_PATH`, `RELATEDB_EMBEDDING_MODEL`, `RELATEDB_PREFETCH_TOP_K`, `RELATEDB_AUTO_EXTRACT`. Environment variables take precedence over `config.yaml`. Each Hermes profile has its own store and settings.

### Keeping memory in git

To track the agent's memory in a git repository with readable diffs:

```sh
hermes relatedb-memory init-diffable ./memory
```

This creates a JSON store and configures `git diff` to pretty-print it with `jq`. Point `db_path` at that directory and set `snapshot_format: json`.

### Upgrading and re-embedding existing stores

If you have an existing 256-dim `model2vec` store (`.rl` file, `parquet` directory, or `json` directory), re-embed it to 384-dim `BAAI/bge-small-en-v1.5` before opening it with the updated plugin:

```sh
# Preview fact count and dimensions without modifying the store
uv run python tools/migrate_embeddings.py --db-path ~/.hermes/memory --dry-run

# Re-embed in place (creates a timestamped backup by default)
uv run python tools/migrate_embeddings.py --db-path ~/.hermes/memory
```

---

## Development

```sh
git clone https://github.com/loheander/hermes-relatedb.git
cd hermes-relatedb
make sync      # install dependencies with uv
make test      # run the test suite
make install   # copy this checkout into every local Hermes profile
hermes plugins doctor .   # check the plugin against the Hermes runtime
```

Design decisions are recorded as ADRs in `docs/adr/` and indexed into a Relate graph in `docs/context-graph/`. Read `AGENTS.md` before you change storage or architecture. If you edit ADRs, specs or module docstrings, run `make index-specs` and commit the updated `docs/context-graph/`.

## License

[MIT](LICENSE)
