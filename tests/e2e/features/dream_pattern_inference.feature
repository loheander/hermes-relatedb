Feature: Pattern inference across conversations (Dream Mode, Phase 2b)
  Dream Mode can surface a recurring pattern across several conversations as a
  labelled inference with its evidence. A pattern helps recall; it is never a
  fact, never an instruction, and never becomes one by repetition. Pattern
  inference has its own switch. Part of #33.

  Background:
    Given Dream Mode is on
    And a pattern needs at least 3 distinct episodes

  @pending_60
  Scenario: Three distinct episodes are enough to propose a pattern
    Given the observation "Asks for the migration plan before any code" in episode "ep-1"
    And the observation "Wants the migration plan before the code" in episode "ep-2"
    And the observation "Reads the migration plan first, code second" in episode "ep-3"
    When Dream Mode infers the pattern "Tends to want the migration plan before code" from all observations
    Then one pattern is proposed with 3 supporting episodes

  @pending_60
  Scenario: Repeating a statement within one episode adds no support
    Given the observation "Asks for the migration plan before any code" in episode "ep-1"
    And the observation "Asks for the migration plan before any code" in episode "ep-1"
    And the observation "Asks for the migration plan before any code" in episode "ep-1"
    And the observation "Wants the migration plan before the code" in episode "ep-2"
    When Dream Mode infers the pattern "Tends to want the migration plan before code" from all observations
    Then no pattern is proposed

  @pending_60
  Scenario: A summary of the same evidence adds no support
    Given the observation "Asks for the migration plan before any code" in episode "ep-1"
    And the observation "Wants the migration plan before the code" in episode "ep-2"
    And a summary observation "Two sessions asked for the plan first" of episode "ep-2"
    When Dream Mode infers the pattern "Tends to want the migration plan before code" from all observations
    Then no pattern is proposed

  @pending_60
  Scenario: Recall shows a pattern as an inference with its source count
    Given a pattern "Tends to want the migration plan before code" supported by 3 episodes
    When a session asks "Tends to want the migration plan before code"
    Then the recalled line for "Tends to want the migration plan before code" is labelled as an inference
    And that line states 3 sources
    And that line does not read as an instruction

  @pending_60
  Scenario: A pattern keeps links to its supporting observations and episodes
    Given a pattern "Tends to want the migration plan before code" supported by 3 episodes
    Then the pattern is derived from its 3 observations and their 3 episodes

  @pending_60
  Scenario: A pattern is never written into USER.md or the system prompt
    Given a USER.md containing "Name: Lo"
    And a pattern "Tends to want the migration plan before code" supported by 3 episodes
    Then USER.md still contains only "Name: Lo"
    And the system prompt block does not mention "migration plan"
    And no USER.md proposal mentions "migration plan"

  @pending_60
  Scenario: More supporting episodes raise the count but do not promote the pattern
    Given a pattern "Tends to want the migration plan before code" supported by 3 episodes
    When 4 more episodes support the pattern
    Then the pattern has 7 supporting episodes
    And the pattern is still an inference
    And no decision or statement mentions "migration plan"

  @pending_60
  Scenario: An explicit statement that contradicts a pattern retires it
    Given a pattern "Tends to want the migration plan before code" supported by 3 episodes
    When the user states "Show me the code first, the plan afterwards" and Dream Mode retires the pattern because of it
    Then recall no longer shows the pattern
    And the pattern is closed, not deleted, with its supporting links kept

  @pending_60
  Scenario: Losing supporting evidence closes the pattern
    Given a pattern "Tends to want the migration plan before code" supported by 3 episodes
    When 2 of its supporting observations are superseded
    And Dream Mode runs again
    Then the pattern is closed, not deleted, with its supporting links kept

  @pending_60
  Scenario: Pattern inference off leaves typed observations on and makes no pattern call
    Given pattern inference is turned off
    And the observation "Asks for the migration plan before any code" in episode "ep-1"
    When a Dream Mode run is attempted
    Then no pattern task is registered
    And the language model made no pattern call
    And the observation "Asks for the migration plan before any code" is still recorded
