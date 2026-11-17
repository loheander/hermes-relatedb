# ADR-0003: Local model2vec embeddings

- Status: Superseded
- Date: 2026-11-16

## Context

Semantic recall needs embeddings. Hosted embedding APIs add network
latency, cost and a privacy risk for personal memory.

## Decision

Embeddings are computed locally with `model2vec`, a static embedding model
that runs on CPU without a GPU or network after the first model download.
`relatedb_memory.embedder` wraps the model and is the only module that
imports it. Vectors are stored as properties next to the text they embed.

## Consequences

- Memory never leaves the machine.
- Embedding quality is lower than large hosted models, accepted for speed.
- Changing the model requires re-embedding stored text.
