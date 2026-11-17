<!-- idd:run-report v1 {"generated_at": "2026-11-17T09:36:20Z", "run_id": "20261117T091514Z-4149913"} -->

◆ Auto-Pilot Summary — 2/10 iterations
┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄
  Result:                  COMPLETED — complete: 2 merged (#35 → PR #36, #34 → PR #37), #33 skipped (needs_clarification)

  Iteration 1:       ✓ merged                — #35 Switch local embedding backend to INT8-quantized BAAI/bge-small-en-v1.5 via fastembed → PR #36 · AC 5/0/0 pass/fail/unverified
  Iteration 2:       ✓ merged                — #34 Add standalone migration script to re-embed existing stores to 384-dim BAAI/bge-small-en-v1.5 → PR #37 · AC 4/0/0 pass/fail/unverified
  ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄
  merged:                  2
  left_open:               0
  partial_followup:        0
  blocked_by_dependency:   0
  failed:                  0
  skipped:                 1
  ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄
  Mode:                    balanced
  Evidence:                PR #36 merged (squash, match-head-commit bde12a0e, no CI configured, 100 tests passed, issue #35 closed); PR #37 merged (squash, match-head-commit 1fc1cf9a, no CI configured, 105 tests passed, issue #34 closed); run-log entries appended; report persisted to .idd/last-run-report.md
  Uncertainty:             none observed
  Decision:                No approval needed.

  Remaining:               1 open issue (#33 — needs clarification / acceptance criteria)
  Next action:             Clarify acceptance criteria on #33, then re-run /auto-pilot
  Report:                  .idd/last-run-report.md
