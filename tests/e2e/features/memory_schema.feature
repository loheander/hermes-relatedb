Feature: Memory graph schema contract
  This feature is the single statement of the graph that relatedb_memory
  persists. It replaces the former memory schema spec: the scenarios drive
  the real write paths against an embedded store and compare the result with
  the schema below, exhaustively, so a label, property or relationship type
  cannot be added, renamed or removed without updating this file. Rationale
  lives in ADR-0001.

  Nodes
    Entity   {key}                          a thing facts and episodes talk about
    Episode  {id, session, kind, at, text}  one recorded event, the provenance
    Fact     {id, text, slot, origin, validFrom, validTo, recordedAt,
              closedAt, embedding}          one statement; validTo and closedAt
                                            are set only once the fact is closed

  Relationships
    (:Fact)-[:FROM]->(:Episode)             the episode a fact was recorded in
    (:Fact)-[:ABOUT]->(:Entity)             what a fact is about
    (:Episode)-[:MENTIONS]->(:Entity)       what an episode mentions
    (:Fact)-[:SUPERSEDES]->(:Fact)          a correction and the fact it closed
    (:Fact)-[:DUPLICATE_OF {score, detectedAt}]->(:Fact)
                                            flags a near-duplicate open fact and
                                            points at its canonical fact (ADR-0008)

  Fact.origin says how the fact was captured: turn, pre_compress, memory_write
  or remember. Recall ranks by it (ADR-0007). Episode.kind is one of message,
  tool_call, memory_write, delegation or pre_compress.

  Bi-temporal rules: a fact is never deleted or overwritten. A correction or a
  retraction closes the old fact by setting validTo (when it stopped being true)
  and closedAt (when the store learned that). A correction also adds a new fact
  that SUPERSEDES the old one. At most one open fact exists per slot.

  Access: all reads and writes go through relatedb_memory.store on its single
  worker thread (ADR-0002, amended by ADR-0005).

  Scenario: The graph has exactly the documented labels and properties
    Given a store written through every write path
    Then the node labels are exactly "Entity, Episode, Fact"
    And the "Entity" nodes have exactly the properties "key"
    And the "Episode" nodes have exactly the properties "at, id, kind, session, text"
    And the "Fact" nodes have exactly the properties "closedAt, embedding, id, origin, recordedAt, slot, text, validFrom, validTo"

  Scenario: The graph has exactly the documented relationship types and directions
    Given a store written through every write path
    Then the relationships are exactly "ABOUT:Fact>Entity, DUPLICATE_OF:Fact>Fact, FROM:Fact>Episode, MENTIONS:Episode>Entity, SUPERSEDES:Fact>Fact"
    And the "DUPLICATE_OF" relationships have exactly the properties "detectedAt, score"
    And the "SUPERSEDES" relationships have no properties

  Scenario: Episode kinds and fact origins are closed sets
    Given an open schema store
    Then the allowed episode kinds are exactly "delegation, memory_write, message, pre_compress, tool_call"
    And the allowed fact origins are exactly "memory_write, pre_compress, remember, turn"
    And recording an episode of kind "gossip" is rejected
    And recording a fact with origin "rumour" is rejected

  Scenario: A correction closes the old fact and never deletes it
    Given an open schema store
    And fact "f1" recorded on "2026-03-01T10:00:00Z" in slot "team/lead"
    When fact "f2" is recorded on "2026-03-20T09:00:00Z" in slot "team/lead" valid from "2026-03-10T00:00:00Z"
    Then fact "f1" is closed with validTo "2026-03-10T00:00:00Z" and closedAt "2026-03-20T09:00:00Z"
    And fact "f2" is open
    And fact "f2" supersedes fact "f1"
    And the graph holds 2 facts

  Scenario: A retraction closes the open fact and never deletes it
    Given an open schema store
    And fact "f1" recorded on "2026-03-01T10:00:00Z" in slot "team/lead"
    When the slot "team/lead" is retracted with validTo "2026-04-01T00:00:00Z" and closedAt "2026-04-02T00:00:00Z"
    Then fact "f1" is closed with validTo "2026-04-01T00:00:00Z" and closedAt "2026-04-02T00:00:00Z"
    And the graph holds 1 facts

  Scenario: Remembering through the agent tool records an episode and an open fact
    Given an open schema store
    When the agent remembers "Ada leads the team" in slot "team/lead" about "ada"
    Then the remembered fact is open with origin "remember"
    And the remembered fact comes from a "tool_call" episode
    And the remembered fact is about "ada"
