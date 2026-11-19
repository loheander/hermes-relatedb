# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- New setting `mirror_builtin_memory` (default `true`, env `RELATEDB_MIRROR_BUILTIN_MEMORY`). When `false`, `on_memory_write` skips the built-in `user` and `memory` targets and writes, closes and embeds nothing; explicit slots still record. Trade-off: history and `relatedb_as_of` for built-in entries versus a duplicate copy of what Hermes already injects. Facts already mirrored stay until forgotten, and re-enabling mirrors only new writes (#48).

## [1.1.0] - 2026-11-19

### Added

- Each fact now has an `origin` (`turn`, `pre_compress`, `memory_write`, `remember`). Recall always admits deliberate facts, caps captured facts at `captured_share` of `k` (default `0.5`) and labels hits with their origin (#39, ADR-0007).
- `tools/backfill_origins.py` sets `origin` on existing stores from the episode kind. It is idempotent. Run it once per store: `uv run python tools/backfill_origins.py --db-path ~/.hermes/memory`. Facts without an origin are still ranked correctly, derived from their episode kind at recall time.
- Near-duplicate open facts are linked with `DUPLICATE_OF` edges on write and by `hermes relatedb-memory dedupe [--dry-run]`. Recall returns one hit per cluster with `seen=N` distinct supporting episodes. New settings `dedupe` (default `true`) and `dedupe_threshold` (default `0.92`) (#40, ADR-0008).

### Changed

- The memory graph schema is now an executable e2e contract, `tests/e2e/features/memory_schema.feature`, replacing the former, drifted memory schema spec (#41).

### Fixed

- `on_memory_write` now keeps one slot per `USER.md`/`MEMORY.md` entry instead of one per file, so `add`, `replace` and `remove` affect only the entry they name (#42). Stores written by earlier versions need a one-off resync: re-add the entries that exist now and leave the history as it is.

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
