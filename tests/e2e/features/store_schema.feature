Feature: Bi-temporal schema and thread-affine store
  The memory store is an embedded Relate database, one per Hermes profile.
  It bootstraps its own schema, survives re-opening, and can be used from
  agent and background threads without losing writes.

  # <hermes_home> is always the profile's own directory, the one Hermes passes
  # to the provider (e.g. ~/.hermes/profiles/paprika), never the shared root.

  Scenario: A fresh profile store bootstraps the bi-temporal schema
    Given a profile with no memory store
    When the profile's store is opened
    Then the store directory is "memory" inside that profile's own hermes home
    And the uniqueness constraints entity_key, episode_id and fact_id exist
    And facts are indexed by slot with a range index
    And facts are indexed by embedding with a vector index scoped by closedAt

  Scenario: Re-opening an existing store is idempotent
    Given a populated store that has been closed
    When the store is opened again
    Then opening did not fail on the existing constraints and indexes
    And the schema is unchanged
    And the entity "ada" and its episode "ep-1" are preserved

  Scenario: Agent and background threads share one store without losing writes
    Given an open store
    When 8 threads each write 10 facts and read at the same time
    Then no thread raised an error
    And all 80 facts are present

  Scenario: A store closes cleanly after threaded use and can be reopened
    Given an open store that 8 background threads have written to
    When the store is closed from a thread other than the one that opened it
    Then the close completes
    And the flushed writes survive a re-open

  Scenario: Two profiles operate concurrently without cross-talk
    Given two profiles "work" and "personal", each with its own open store
    When both stores are written to by 8 threads at the same time
    Then no thread raised an error
    And each store holds only its own profile's facts
    And the two stores live in different files

  Scenario: A new named profile gets its own store and leaves the main store untouched
    Given the main profile has a populated store that has been closed
    And a profile "paprika" with no memory store
    When the store of profile "paprika" is opened
    Then the store file is created inside the "paprika" profile's own hermes home
    And the "paprika" store is a different file from the main store
    And the main store still holds exactly its original data

  Scenario: Importing the store module creates no database
    Given a profile with no memory store
    When the store module is imported in a fresh interpreter
    Then the import succeeds
    And no database file or directory is left behind
