# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-11-17

### Breaking Changes

- Switched the local embedding backend from `model2vec` (256 dimensions) to `fastembed` with `BAAI/bge-small-en-v1.5` (384 dimensions) (#36).
- Because each RelateDB store is bound to a single vector index dimension, existing 256-dim stores created with `0.1.0` are incompatible with `1.0.0` until re-embedded.

### Added

- Standalone migration script `tools/migrate_embeddings.py` to re-embed existing `.rl`, `parquet`, or `json` stores from 256-dim `model2vec` to 384-dim `BAAI/bge-small-en-v1.5` without requiring `model2vec` (#37).

### Migration from 0.1.0

Before opening an existing `0.1.0` store with `1.0.0`:

1. **Stop any running Hermes process** (CLI sessions or gateway) that may hold a writer lock on the store.
2. **Preview the store** (read-only, optional):
   ```sh
   uv run python tools/migrate_embeddings.py --db-path ~/.hermes/memory --dry-run
   ```
   For a named profile, pass that profile's store path (for example `~/.hermes/profiles/<profile>/memory`).
3. **Re-embed the store in place**:
   ```sh
   uv run python tools/migrate_embeddings.py --db-path ~/.hermes/memory
   ```
   By default, the script creates a timestamped backup (`<db_path>.bak-YYYYMMDDTHHMMSSZ`), drops `fact_embedding`, re-embeds all `Fact` nodes in batches using `BAAI/bge-small-en-v1.5`, rebuilds the 384-dim `fact_embedding` index, and runs a smoke `SEARCH` query.
   - Pass `--no-backup` to skip creating a backup.
   - Pass `--batch-size <n>` to adjust the embedding batch size (default: `64`).
   - Pass `--model <name>` to migrate to a different `fastembed` model.
4. **Verify the migrated store**:
   ```sh
   hermes relatedb-memory status
   hermes relatedb-memory verify
   ```

## [0.1.0] - 2026-11-16

### Added

- Initial release of `relatedb-memory`, a bi-temporal long-term memory provider for Hermes Agent backed by RelateDB.
- Thread-affine bi-temporal graph schema with slot supersession, entity links, and episode provenance supporting `parquet`, `json` (git-diffable), and single-file `.rl` stores.
- Local CPU vector recall (`model2vec`, 256-dim) with pre-turn prefetch, post-turn extraction, `MEMORY.md`/`USER.md` write mirroring, and pre-compression episode capture.
- Agent tools (`relatedb_remember`, `relatedb_recall`, `relatedb_forget`, `relatedb_as_of`, `relatedb_provenance`, `relatedb_cypher`) and bundled `relatedb-memory` skill.
- Hermes CLI subcommands (`status`, `verify`, `cypher`, `mcp`, `init-diffable`) for store inspection, integrity checks, and MCP server configuration.
