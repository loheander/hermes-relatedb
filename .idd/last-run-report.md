<!-- idd:run-report v1 {"generated_at": "2026-11-16T10:14:29Z", "run_id": "20261116T094619Z-3673532"} -->

◆ Auto-Pilot Summary — 3/10 iterations
┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄
  Result:                  COMPLETED — partial: 2 merged, 1 left open (human review required: E2E test issue)

  Iteration 1:       ✓ merged    — #2 context-graph Relate store → PR #18
  Iteration 2:       ✓ merged    — #3 profile-scoped config → PR #19
  Iteration 3:       ⚠ left_open — #11 E2E acceptance tests for schema and store → PR #20 · AC 3/0/0 pass/fail/unverified
  ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄
  merged:                  2
  left_open:               1
  partial_followup:        0
  blocked_by_dependency:   0
  failed:                  0
  skipped:                 0
  ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄
  Mode:                    balanced
  Evidence:                PRs #18, #19 merged; PR #20 review APPROVE, MERGEABLE, head fea1572, no CI; run-log lines appended
  Uncertainty:             #11 merge deliberately held per user instruction; no CI configured; #4-#10, #12-#16 blocked by #11 chain (inference from dependency edges)
  Decision:                No approval needed.

  Remaining:               12 open issues
  Next action:             user reviews and merges PR #20, then re-run /auto-pilot to continue with #4
  Report:                  .idd/last-run-report.md
