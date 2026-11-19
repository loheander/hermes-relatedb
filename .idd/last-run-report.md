<!-- idd:run-report v1 {"generated_at": "2026-11-19T13:45:35Z", "run_id": "20261119T132540Z-895570"} -->

◆ Auto-Pilot Summary — 4/10 iterations
  Result:    COMPLETED — complete: 4 merged (#42 → PR #44, #39 → PR #45, #40 → PR #46, #41 → PR #47), #33 skipped (blocked label)
  merged: 4 · left_open: 0 · partial_followup: 0 · blocked_by_dependency: 0 · failed: 0 · skipped: 1
  Mode:      balanced
  Evidence:  each PR squash-merged with --match-head-commit bound to the reviewed head; CI passed on every PR; issues #42, #39, #40, #41 confirmed CLOSED; post-merge cleanup ok
  Uncertainty: triage cache reused although the triage commit itself postdated it (kept the manual order override); PR #45's first review returned merge_floor unmet and was re-run before merge; PR #47 needed one review fix; lock was released just before this report was persisted
  Decision:  No approval needed.
  Remaining: 1 open issue (#33, blocked)
  Next action: Unblock or clarify #33, then re-run /auto-pilot
