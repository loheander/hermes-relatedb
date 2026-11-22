Feature: Dream Mode model routing and transparency
  Dream Mode reads conversation excerpts and proposes consolidations through
  Hermes, on a dedicated auxiliary model slot. The user chooses that model
  explicitly and can always see which provider and model would receive the
  excerpts. Dream Mode never inherits the chat model and never falls back to
  another model, paid or not.

  Background:
    Given a Dream Mode plugin context with the relatedb-memory plugin registered
    And a memory store with these episodes, oldest first:
      | id   | text                                    |
      | ep-1 | I moved the Lund office to Malmo.       |
      | ep-2 | Please call me Ada from now on.         |
      | ep-3 | The staging database is called orchid.  |
    And the Hermes chat model is "chat-premium" from provider "chat-cloud"

  @pending_56
  Scenario: Dream calls use the consolidation slot, never the chat model
    Given the consolidation slot resolves to model "dream-small" from provider "dream-cloud"
    And the model returns one valid proposal
    When Dream Mode runs
    Then the run succeeds
    And exactly 1 model call was made
    And every model call went through the consolidation slot
    And no model call used the chat model

  @pending_56
  Scenario: A run refuses when the consolidation slot is unset, even with a chat model configured
    Given the consolidation slot has no provider or model chosen
    When Dream Mode runs
    Then the run is refused with a message naming the consolidation slot and how to set it
    And exactly 0 model calls were made
    And the store has no consolidation proposals

  @pending_56
  Scenario: A failing model fails the run and is never replaced by another model
    Given the consolidation slot resolves to model "dream-small" from provider "dream-cloud"
    And the model always fails with "provider unavailable"
    When Dream Mode runs with 0 retries
    Then the run fails
    And exactly 1 model call was made
    And every model call went through the consolidation slot
    And no model call used the chat model
    And Dream Mode status records the failure "provider unavailable" for model "dream-small"
    And the store has no consolidation proposals

  @pending_56
  Scenario Outline: A local model runs the same scenario as a cloud model
    Given the consolidation slot resolves to model "<model>" from provider "<provider>"
    And the model returns one valid proposal
    When Dream Mode runs
    Then the run succeeds
    And every model call went through the consolidation slot
    And the run report names provider "<provider>" and model "<model>"

    Examples:
      | provider     | model       |
      | dream-cloud  | dream-small |
      | local-ollama | qwen3-8b |

  @pending_56
  Scenario: A dry run shows the resolved provider and model and sends nothing
    Given the consolidation slot resolves to model "dream-small" from provider "dream-cloud"
    When Dream Mode runs with --dry-run
    Then the run succeeds
    And the output names the consolidation slot, provider "dream-cloud" and model "dream-small"
    And exactly 0 model calls were made

  @pending_56
  Scenario: Status shows the resolved provider and model and sends nothing
    Given the consolidation slot resolves to model "dream-small" from provider "dream-cloud"
    When Dream Mode status is requested
    Then the output names the consolidation slot, provider "dream-cloud" and model "dream-small"
    And exactly 0 model calls were made

  @pending_56
  Scenario: Status says so when no model has been chosen
    Given the consolidation slot has no provider or model chosen
    When Dream Mode status is requested
    Then the output says no Dream Mode model is chosen
    And exactly 0 model calls were made

  @pending_56
  Scenario: A transient failure is retried on the same model, within a bound
    Given the consolidation slot resolves to model "dream-small" from provider "dream-cloud"
    And the model times out once and then returns one valid proposal
    When Dream Mode runs with a 30 second timeout and 2 retries
    Then the run succeeds
    And exactly 2 model calls were made
    And every model call went through the consolidation slot
    And every model call carried a 30 second timeout

  @pending_56
  Scenario: Retries stop at the bound and the failure is recorded
    Given the consolidation slot resolves to model "dream-small" from provider "dream-cloud"
    And the model always times out
    When Dream Mode runs with a 30 second timeout and 2 retries
    Then the run fails
    And exactly 3 model calls were made
    And every model call went through the consolidation slot
    And no model call used the chat model
    And Dream Mode status records the failure "timed out" for model "dream-small"

  @pending_56
  Scenario: Only the episodes in the batch are sent, as quoted data
    Given the consolidation slot resolves to model "dream-small" from provider "dream-cloud"
    And the model returns one valid proposal
    When Dream Mode runs with a batch of 2 episodes
    Then the run succeeds
    And the model received the text of "ep-1" and "ep-2" as quoted data
    And the model did not receive the text of "ep-3"
    And the instructions to the model contain no episode text
    And the model received no stored facts or entities beyond the proposal schema
