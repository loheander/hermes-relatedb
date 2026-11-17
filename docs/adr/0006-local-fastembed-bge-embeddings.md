# ADR-0006: Local fastembed BGE-small-en-v1.5 embeddings

- Status: Accepted
- Date: 2026-11-17
- Supersedes: ADR-0003

## Context

`model2vec` static token embeddings average word vectors without contextual attention, missing word order, role bindings, and negation. Retrieval quality on paraphrased queries and 512-token `sync_turn()` transcripts suffered.

## Decision

`relatedb_memory.embedder` replaces `model2vec` with `fastembed` (`BAAI/bge-small-en-v1.5`, 384-dim, 512-token window, INT8 quantized ONNX via `onnxruntime`, no PyTorch dependency). `relatedb_memory.config` defaults `embedding_model` to `"BAAI/bge-small-en-v1.5"`. `relatedb_memory.provider` uses `embed_query()` for retrieval queries (`prefetch()`, `relatedb_recall`) and `embed_one()` for passage writes (`sync_turn()`, `relatedb_remember`). `relatedb_memory.embedder` remains the only module that imports `fastembed`, keeping it lazy-loaded on first encode.

## Consequences

- Memory never leaves the machine; CPU-only quantized ONNX keeps disk and RAM small (~34 MB) without `torch`.
- Query and passage embeddings use asymmetric BGE instruction prefixes via `TextEmbedding.query_embed` and `TextEmbedding.embed`.
- Existing 256-dim `model2vec` stores must be re-embedded to 384-dim `BAAI/bge-small-en-v1.5` before opening with the new default.
