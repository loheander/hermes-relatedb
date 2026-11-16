@pending_7
Feature: Pre-filtered vector recall, prefetch lifecycle, and RecallStatus
  Vector recall filters out closed/superseded facts inside the index scan
  before LIMIT k, background prefetch warms the next turn without blocking,
  and the static system prompt block never changes after writes or recalls.

  Scenario: Pre-filtered vector search skips superseded facts before LIMIT k
    Given an open store with a superseded fact closer to the query than the current fact
    When vector recall runs with k=1
    Then only the current fact is returned with its entities, episode evidence, and replaced text

  Scenario: Background queue_prefetch populates next-turn prefetch and RecallStatus
    Given an initialized RelateDBMemoryProvider with a stored fact about release reviews
    When queue_prefetch runs for "Who reviews relate releases?" and completes
    Then prefetch returns the formatted "[RelateDB Memory]" block
    And recall_status reports provider_label "relatedb" with count 1

  Scenario: Trivial prompts bypass recall
    Given an initialized RelateDBMemoryProvider with a stored fact about release reviews
    When prefetch runs for trivial prompts "ok", "thanks!", and "/help"
    Then prefetch returns an empty string and recall_status is None

  Scenario: Static system prompt invariant holds across writes and prefetches
    Given an initialized RelateDBMemoryProvider
    When facts are written and prefetches run
    Then system_prompt_block is byte-for-byte identical before and after
