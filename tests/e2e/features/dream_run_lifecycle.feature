@pending_55
Feature: Dream Mode run lifecycle, opt-in and inspectability
  Dream Mode is off unless the user turns it on. When on, it runs only when
  Hermes has been idle, only when there are episodes it has not processed, and
  it records every run so the user can see what it did or why it did not run.
  A dry run changes nothing that recall or the apply checkpoint depend on.

  Scenario: Off means off
    Given a profile with Dream Mode disabled and 3 captured episodes
    When the Dream Mode plugin entry point registers
    Then no idle task is registered
    And no LLM call is made
    When a turn is captured and then recalled through the provider
    Then recall returns the captured turn
    And no LLM call is made

  Scenario: Opt-in registers the idle task
    Given a profile with Dream Mode enabled, an interval of 24 hours and a minimum idle time of 3 hours
    When the Dream Mode plugin entry point registers
    Then exactly one idle task is registered
    And the idle task runs every 24 hours after 3 hours of idleness

  Scenario: No new material, no run
    Given a profile with Dream Mode enabled and no captured episodes
    And the Dream Mode plugin entry point has registered
    When the idle task fires
    Then no LLM call is made
    And the latest Dream run is recorded as skipped

  Scenario: Bounded batch
    Given a profile with Dream Mode enabled, a batch size of 2 and 5 captured episodes
    And the Dream Mode plugin entry point has registered
    And the LLM will propose one fact
    When the idle task fires
    Then exactly one LLM call is made
    And 3 episodes are still pending
    And the latest Dream run is recorded as completed

  Scenario: Manual run
    Given a profile with Dream Mode enabled and 3 captured episodes
    And the LLM will propose one fact
    When "hermes relatedb dream" is run with Hermes idle for only a few seconds
    Then the command exits 0
    And 0 episodes are still pending
    And the proposed fact is stored

  Scenario: Dry run is inert
    Given a profile with Dream Mode enabled and 3 captured episodes
    And the LLM will propose one fact and one profile change
    When "hermes relatedb dream --dry-run" is run
    Then the command exits 0
    And the latest Dream run is recorded as a dry run with 2 proposals
    And no fact is stored
    And no profile proposal is stored
    And the apply checkpoint is unchanged
    And 3 episodes are still pending
    When the LLM will propose one fact and one profile change
    And "hermes relatedb dream" is run
    Then the latest Dream run covers the same 3 episodes
    And the proposed fact is stored

  Scenario: Run history is inspectable
    Given a profile with Dream Mode enabled and 3 captured episodes
    And the LLM will propose one fact, one profile change and one proposal outside the schema
    When "hermes relatedb dream" is run
    Then the latest Dream run records its checkpoint, 2 proposals, 1 applied, 1 rejected and no failures
    When "hermes relatedb dream --status" is run
    Then the status reports the last run, its outcome, 0 pending episodes and the time since the last activity

  Scenario: A busy instance that never got to run is visible
    Given a profile with Dream Mode enabled and 3 captured episodes
    And the last captured episode is 10 minutes old
    When "hermes relatedb dream --status" is run
    Then the status reports no last run, 3 pending episodes and a time since the last activity of about 10 minutes

  Scenario: Interrupted run resumes
    Given a profile with Dream Mode enabled and 3 captured episodes
    And the LLM fails with a provider error
    When "hermes relatedb dream" is run
    Then the command exits non-zero
    And the latest Dream run is recorded as failed with a failure message
    And no fact is stored
    And the apply checkpoint is unchanged
    And 3 episodes are still pending
    When the LLM will propose one fact
    And "hermes relatedb dream" is run
    Then the command exits 0
    And the latest Dream run covers the same 3 episodes
    And 0 episodes are still pending
    And the proposed fact is stored

  Scenario: Re-run over unchanged input
    Given a profile with Dream Mode enabled and 3 captured episodes
    And the LLM will propose one fact
    When "hermes relatedb dream" is run
    And a new episode repeats the same statement
    And the LLM will propose the same fact again
    And "hermes relatedb dream" is run
    Then exactly one open fact exists for the proposed slot
    And no duplicate link is created for it
