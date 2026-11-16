@pending_10
Feature: Diffable JSON store git workflow, MCP sidecar, and hermes relatedb CLI
  The diffable JSON directory store produces clean git diffs, replays
  idempotently with zero diff, exposes status/verify/mcp CLI subcommands,
  and registers CLI parsers without importing heavy provider dependencies.

  Scenario: Diffable JSON store initialization and readable git diff
    Given an initialized temporary git repository
    When hermes relatedb init-diffable is run on "./memory"
    Then the JSON-codec store, .gitattributes, and git textconv config are created
    When the initial store is committed and a new fact is written
    Then git status and git diff show the added node and relationship

  Scenario: Silent replay on idempotent MERGE produces zero diff
    Given an initialized diffable store committed in git
    When the exact same fact write is replayed
    Then graph.json has zero git diff

  Scenario: CLI status and verify commands
    Given an initialized diffable store with valid facts
    When hermes relatedb status is run
    Then status reports store path, codec, and node/relationship counts
    When hermes relatedb verify is run
    Then verify exits 0
    When a duplicate open fact is injected into the same slot
    Then verify exits non-zero

  Scenario: MCP sidecar configuration and lightweight parser registration
    Given an initialized diffable store
    When hermes relatedb mcp --read-only is run
    Then it outputs a valid relate serve --mcp stdio --read-only=live configuration
    And importing cli and building the parser does not load model2vec or numpy
