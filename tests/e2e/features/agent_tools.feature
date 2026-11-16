Feature: Agent memory tools (remember, recall, as-of, provenance, cypher)
  The provider exposes tool schemas and handles tool calls for remembering,
  recalling, forgetting, auditing bi-temporal state (trueOn vs believedOn),
  inspecting provenance, and running read-only Cypher queries.

  Scenario: Explicit remember, recall, update, and forget tool workflow
    Given an initialized RelateDBMemoryProvider with agent tools enabled
    When the agent calls relatedb_remember for slot "project/owner" with "Grace owns relatedb"
    And the agent calls relatedb_recall for "Who owns relatedb?"
    Then the recalled tool result contains "Grace owns relatedb"
    When the agent calls relatedb_remember for slot "project/owner" with "Ada owns relatedb"
    And the agent calls relatedb_recall for "Who owns relatedb?"
    Then the recalled tool result contains "Ada owns relatedb" and replaced "Grace owns relatedb"
    When the agent calls relatedb_forget for slot "project/owner"
    And the agent calls relatedb_recall for "Who owns relatedb?"
    Then the recalled tool result has zero active facts

  Scenario: Bi-temporal relatedb_as_of audit (trueOn vs believedOn)
    Given an initialized RelateDBMemoryProvider with agent tools enabled
    And Grace was recorded on "2026-03-02T00:00:00Z" as reviewer since "2026-01-05T00:00:00Z"
    And Ada was recorded on "2026-03-20T00:00:00Z" as taking over on "2026-03-10T00:00:00Z"
    When the agent calls relatedb_as_of for slot "relate/release-reviewer" on "2026-03-15T00:00:00Z"
    Then trueOn is ["Ada reviews each relate release."] and believedOn is ["Grace reviews each relate release."]

  Scenario: Evidence provenance chain via relatedb_provenance
    Given an initialized RelateDBMemoryProvider with agent tools enabled
    And Grace was recorded on "2026-03-02T00:00:00Z" as reviewer since "2026-01-05T00:00:00Z"
    And Ada was recorded on "2026-03-20T00:00:00Z" as taking over on "2026-03-10T00:00:00Z"
    When the agent calls relatedb_provenance for slot "relate/release-reviewer"
    Then provenance includes both facts in lineage with their Episode kind, session, at, and text

  Scenario: Read-only relatedb_cypher guardrails
    Given an initialized RelateDBMemoryProvider with agent tools enabled
    When the agent calls relatedb_cypher with a read query "MATCH (n) RETURN count(n) AS c"
    Then the Cypher tool returns JSON rows
    When the agent calls relatedb_cypher with mutating queries CREATE, MERGE, SET, DELETE, REMOVE, and DROP
    Then every mutating Cypher query is rejected without modifying the store
