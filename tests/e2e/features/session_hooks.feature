@pending_8
Feature: Turn sync, memory-write mirroring, and pre-compression hooks
  Primary agent turns, built-in memory writes, pre-compression flushes,
  session switches, and delegations update the bi-temporal memory graph
  while non-primary agent contexts are ignored.

  Scenario: Primary turn sync persists episode and extracted facts
    Given an initialized RelateDBMemoryProvider for session "s-primary"
    When a primary turn completes with user "Grace prefers dark mode" and assistant "Noted."
    Then an Episode and active Fact are persisted for session "s-primary"

  Scenario: Non-primary agent contexts are ignored
    Given an initialized RelateDBMemoryProvider for session "s-primary"
    When sync_turn runs with agent_context "subagent", "cron", and "flush"
    Then zero Episode or Fact nodes are written

  Scenario: Built-in memory tool mirroring add, replace, and remove
    Given an initialized RelateDBMemoryProvider for session "s-mirror"
    When on_memory_write "add" records "User prefers vim" in target "prefs/editor"
    And on_memory_write "replace" updates "prefs/editor" to "User prefers neovim"
    Then the active fact for "prefs/editor" is "User prefers neovim" and the old fact is closed
    When on_memory_write "remove" closes "prefs/editor"
    Then "prefs/editor" has zero active facts

  Scenario: Pre-compression flush and session switching
    Given an initialized RelateDBMemoryProvider for session "s-old"
    When on_pre_compress runs on messages about to be truncated
    Then a "pre_compress" episode is recorded for "s-old"
    When on_session_switch switches to "s-new" with reset=True
    And a primary turn completes with user "Working on RelateDB" and assistant "Got it."
    Then the new episode is linked to session "s-new"

  Scenario: Delegation observation records parent-side delegation episode
    Given an initialized RelateDBMemoryProvider for session "s-parent"
    When on_delegation runs for task "Audit schema" with result "All constraints valid" and child_session_id "s-child"
    Then a "delegation" episode is recorded for session "s-parent"
