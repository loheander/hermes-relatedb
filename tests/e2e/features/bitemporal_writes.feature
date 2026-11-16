@pending_6
Feature: Bi-temporal write path, slot supersession, and provenance
  Facts are never overwritten or deleted when knowledge changes.
  Episodes record provenance, slot corrections supersede prior open facts
  non-destructively, and shared entity keys converge across sessions.

  Scenario: Recording an episode and initial facts with provenance
    Given an open bi-temporal store
    When session "s1" records a "message" episode "ep-1" mentioning "grace" and "relate"
    And fact "f1" is recorded in slot "relate/release-reviewer" from "ep-1" about "grace" and "relate"
    Then the graph holds the provenance chain from "f1" to "ep-1" and its entities
    And "relate/release-reviewer" is in active slots

  Scenario: Non-destructive correction supersedes prior fact in the same slot
    Given an open bi-temporal store
    And session "s1" recorded fact "f1" in slot "relate/release-reviewer" on "2026-03-01T10:00:00Z"
    When session "s2" on "2026-03-20T09:00:00Z" records a "tool_call" episode "ep-2" with fact "f3" in slot "relate/release-reviewer" valid from "2026-03-10T00:00:00Z"
    Then fact "f1" is still present with validTo "2026-03-10T00:00:00Z" and closedAt "2026-03-20T09:00:00Z"
    And fact "f3" supersedes fact "f1"
    And the slot-uniqueness invariant holds

  Scenario: Idempotent session replay
    Given an open bi-temporal store
    And session "s1" recorded fact "f1" in slot "relate/release-reviewer" on "2026-03-01T10:00:00Z"
    When the exact same episode and fact payload for "s1" is replayed
    Then the node and relationship counts are unchanged
    And the slot-uniqueness invariant holds

  Scenario: Explicit retraction closes a slot without replacement
    Given an open bi-temporal store
    And session "s1" recorded fact "f1" in slot "relate/release-reviewer" on "2026-03-01T10:00:00Z"
    When slot "relate/release-reviewer" is retracted at "2026-03-25T12:00:00Z"
    Then fact "f1" is closed with validTo "2026-03-25T12:00:00Z" and closedAt "2026-03-25T12:00:00Z"
    And "relate/release-reviewer" is not in active slots
    And the slot-uniqueness invariant holds

  Scenario: Shared Zettelkasten entity keys converge across episodes
    Given an open bi-temporal store
    When episode "ep-z1" records fact "fz1" about "note_id:202611142237", "citation_key:ada2026", and "project_slug:hermes-relatedb"
    And episode "ep-z2" records fact "fz2" about "note_id:202611142237", "citation_key:ada2026", and "project_slug:hermes-relatedb"
    Then each shared entity key has exactly one Entity node with both facts attached
    And the slot-uniqueness invariant holds
