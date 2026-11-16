# ADR-0002: In-process relate-db thread-worker instead of CLI or MCP access

- Status: Accepted
- Date: 2026-11-16

## Context

Hermes calls memory providers from several threads. The `relate-db` Python
package embeds the engine in-process, but connections are thread-affine. The
alternative is to shell out to the Relate CLI or talk to a Relate MCP server.

## Decision

`relatedb_memory.store` embeds `relate-db` in-process and owns the connection
on one dedicated worker thread. Provider calls submit work to that thread and
wait for the result. We do not spawn the CLI or an MCP server for memory
access, which keeps latency low and avoids a subprocess per profile.

## Consequences

- One writer per database, matching the engine rule.
- Calls cross a queue, so every operation needs a timeout.
- Tooling that wants a live read-only view of the store uses a separate
  read-only connection (see ADR-0004).
