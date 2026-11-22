Feature: Scoped decisions and fresh-session context (Dream Mode, Phase 2a)
  Dream Mode keeps project decisions in the project they belong to and proposes
  only durable personal preferences for USER.md. A fresh session picks up the
  latest confirmed decision for its scope, without repetition and without
  superseded versions. Part of #33.

  @pending_59
  Scenario: A project decision is recalled in its own project only
    Given a Dream Mode run that recorded the decision "Billing uses PostgreSQL 16" in project "project-a"
    When a fresh session in project "project-a" asks "Which database does billing use?"
    And a fresh session in project "project-b" asks "Which database does billing use?"
    Then the answer in project "project-a" contains "Billing uses PostgreSQL 16"
    And the answer in project "project-b" does not contain "Billing uses PostgreSQL 16"

  @pending_59
  Scenario: A session with no clear project gets no project decisions in automatic recall
    Given a USER.md containing "Name: Lo"
    And a Dream Mode run that recorded the decision "Billing uses PostgreSQL 16" in project "project-a"
    And a Dream Mode run that observed the durable preference "Prefers concise answers without preamble"
    And the user approves that proposal
    When a fresh session with no project asks "Which database does billing use?"
    Then the answer with no project does not contain "Billing uses PostgreSQL 16"
    And the answer with no project contains "Prefers concise answers without preamble"

  @pending_59
  Scenario: A project decision is never proposed for the user profile
    Given a Dream Mode run that recorded the decision "Billing uses PostgreSQL 16" in project "project-a"
    Then no USER.md proposal mentions "PostgreSQL"

  @pending_59
  Scenario: A durable preference is proposed and USER.md is untouched until approval
    Given a USER.md containing "Name: Lo"
    And a Dream Mode run that observed the durable preference "Prefers concise answers without preamble"
    Then one USER.md proposal contains "Prefers concise answers without preamble"
    And USER.md still contains only "Name: Lo"
    When the user approves that proposal
    Then USER.md contains "Name: Lo" and "Prefers concise answers without preamble"

  @pending_59
  Scenario: A fresh session starts with the latest decision and the durable preferences
    Given a USER.md containing "Name: Lo"
    And a Dream Mode run on 1 March that recorded the decision "Billing uses MySQL" in project "project-a"
    And a Dream Mode run on 8 March that recorded the decision "Billing uses PostgreSQL 16" in project "project-a"
    And a Dream Mode run that observed the durable preference "Prefers concise answers without preamble"
    And the user approves that proposal
    When a fresh session in project "project-a" asks "Which database does billing use?"
    Then the answer in project "project-a" contains "Billing uses PostgreSQL 16"
    And the answer in project "project-a" contains "Prefers concise answers without preamble"
    And the answer in project "project-a" does not contain "Billing uses MySQL"

  @pending_59
  Scenario: The later decision in a scope wins and the earlier one stays in history
    Given a Dream Mode run on 1 March that recorded the decision "Billing uses MySQL" in project "project-a"
    And a Dream Mode run on 8 March that recorded the decision "Billing uses PostgreSQL 16" in project "project-a"
    When a fresh session in project "project-a" asks "Which database does billing use?"
    Then the answer in project "project-a" contains "Billing uses PostgreSQL 16"
    And the answer in project "project-a" does not contain "Billing uses MySQL"
    And the history of the billing decision on 3 March shows "Billing uses MySQL"

  @pending_59
  Scenario: With Dream Mode off a fresh session recalls exactly what Phase 1 recalls
    Given Dream Mode is turned off
    And a stored fact "Billing uses PostgreSQL 16" recorded before Dream Mode existed
    When a Dream Mode run is attempted
    And a fresh session in project "project-a" asks "Which database does billing use?"
    Then the answer in project "project-a" is identical to the Phase 1 answer
    And the language model was never called

  @pending_59
  Scenario: The maintained context stays within the size budget
    Given a context size budget of 400 characters
    And a Dream Mode run that recorded 60 distinct decisions in project "project-a"
    Then the maintained context for project "project-a" is at most 400 characters
