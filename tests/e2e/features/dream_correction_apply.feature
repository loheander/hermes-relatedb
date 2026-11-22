@pending_58
Feature: Corrections win, conflicts stay visible, and Dream Mode applies changes safely
  A later correction replaces the statement it corrects and the old version is
  kept. Whether a statement corrects an earlier one or merely describes another
  context is never guessed: unclear cases stay open and visible. Dream Mode can
  never overwrite a newer correction, writes only through the store's single
  writer, and can be rolled back without losing history.

  Scenario: Explicit correction wins immediately
    Given an open fact "f-db-old" in slot "project/alpha/database" saying "Alpha uses MySQL."
    When the user explicitly corrects slot "project/alpha/database" to "Alpha uses PostgreSQL." without any Dream run
    Then recall for "which database does Alpha use" shows "Alpha uses PostgreSQL."
    And recall for "which database does Alpha use" does not show "Alpha uses MySQL."
    And fact "f-db-old" is kept, closed, and still traces back to its original episode
    And the new fact supersedes fact "f-db-old"
    And the new fact is recorded as an explicit correction

  Scenario: Inferred never beats explicit
    Given an open fact "f-db-old" in slot "project/alpha/database" saying "Alpha uses MySQL."
    And the user explicitly corrected slot "project/alpha/database" to "Alpha uses PostgreSQL."
    And Dream Mode is enabled with 1 unprocessed episode in which the user mentions "mysql" again in passing
    When Dream Mode runs and the model proposes the inferred fact "Alpha uses MySQL." in slot "project/alpha/database"
    Then the proposal is recorded as rejected in the run history because it contradicts an explicit correction
    And recall for "which database does Alpha use" shows "Alpha uses PostgreSQL."
    And recall for "which database does Alpha use" does not show "Alpha uses MySQL."

  Scenario: Ambiguous contradictions stay visible
    Given an open fact "f-editor-a" in slot "project/alpha/editor" saying "Alpha code is edited in vim."
    And Dream Mode is enabled with 1 unprocessed episode in which the user mentions VS Code for Alpha
    When Dream Mode runs and the model proposes an ambiguous correction of "f-editor-a" to "Alpha code is edited in VS Code." in slot "project/alpha/editor-notes"
    Then both statements are still open
    And the two statements are linked as a possible conflict
    And recall for "what editor is used for Alpha" shows both statements and marks them as a conflict

  Scenario: Different context is not a correction
    Given an open fact "f-db-alpha" in slot "project/alpha/database" saying "Alpha uses MySQL."
    When the user explicitly states in slot "project/beta/database" that "Beta uses PostgreSQL."
    Then fact "f-db-alpha" is still open
    And recall for "which database does Alpha use" shows "Alpha uses MySQL."
    And the two facts are not linked as a conflict

  Scenario: Stale proposals are rejected against the changed store revision
    Given an open fact "f-db-old" in slot "project/alpha/database" saying "Alpha uses MySQL."
    And an open fact "f-lang-old" in slot "project/alpha/language" saying "Alpha is written in Ruby."
    And Dream Mode is enabled with 2 unprocessed episodes
    When Dream Mode runs, the model proposes a database fact and a language fact, and the user corrects slot "project/alpha/database" to "Alpha uses PostgreSQL." while the run is in flight
    Then the database proposal is rejected as stale in the run history
    And the user's correction is preserved and still open
    And the language proposal is applied
    When Dream Mode runs again with the model re-proposing the database fact
    Then the database proposal is not applied over the correction

  Scenario: Single writer
    Given Dream Mode is enabled with 2 unprocessed episodes
    When Dream Mode runs and the model proposes one fact
    Then the run applied its proposal
    And no store handle other than the provider's writer was opened during the run
    And the applied fact is in the provider's store

  Scenario: Rollback closes derived facts and keeps history
    Given an open fact "f-db-old" in slot "project/alpha/database" saying "Alpha uses MySQL."
    And Dream Mode is enabled with 1 unprocessed episode
    And a completed Dream run derived the fact "Alpha prefers short migrations." in slot "project/alpha/style"
    When the user rolls back that run
    Then the derived fact is closed and no longer recalled
    And fact "f-db-old" is still open and unchanged
    And the rolled-back run is still visible in the run history as rolled back

  Scenario: Correction detection from the model is applied
    Given an open fact "f-db-old" in slot "project/alpha/database" saying "Alpha uses MySQL."
    And Dream Mode is enabled with 1 unprocessed episode in which the user says Alpha moved to PostgreSQL
    When Dream Mode runs and the model proposes a correction of "f-db-old" to "Alpha uses PostgreSQL."
    Then the correction is applied
    And fact "f-db-old" is kept and closed
    And recall for "which database does Alpha use" shows "Alpha uses PostgreSQL."

  Scenario Outline: Correction detection from the model is refused when its sources do not qualify
    Given an open fact "f-db-old" in slot "project/alpha/database" saying "Alpha uses MySQL."
    And <setup>
    And Dream Mode is enabled with 1 unprocessed episode in which the user says Alpha moved to PostgreSQL
    When Dream Mode runs and the model proposes a correction of "<target>" to "Alpha uses PostgreSQL."
    Then the correction is rejected in the run history with reason "<reason>"
    And no new fact is written by that run

    Examples:
      | setup                                                                       | target      | reason          |
      | no fact named "f-missing" exists                                            | f-missing   | source_missing  |
      | fact "f-db-closed" was retracted earlier                                    | f-db-closed | source_closed   |
      | an open fact "f-db-new" in slot "project/alpha/db-engine" saying "Alpha uses PostgreSQL."  | f-db-old    | already_covered |
