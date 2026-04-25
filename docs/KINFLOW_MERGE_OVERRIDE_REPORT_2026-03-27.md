# KINFLOW Merge Override Report (Run 4374)

- instruction_id: `KINFLOW-MERGE-APPROVAL-GATE-TEMP-OVERRIDE-20260327-001`
- run_code: `4374`
- repository: `calebini/kinflow`
- PR: `#1` (`ctx002-first-slice` -> `main`)
- evidence_root: `/home/agent/projects/_backlog/output/kinflow_merge_override_4374_20260327T175758Z/`

## Lint preflight

- command: `ruff check .`
- result: `LINT_PASS_NORMALIZED`
- evidence: `00_lint_preflight_block.txt`, `01_ruff_check.txt`

## Preconditions

- Required CI contexts present and green: **PASS**
- Mergeability true (not conflicted): **PASS** (`mergeable=MERGEABLE`)
- Branch protection currently requires 1 approval: **PASS**
- evidence: `10_pr_pre.json`, `11_protection_before.json`, `12_pr_checks_pre.txt`, `13_precondition_eval.txt`

## Temporary policy adjustment attempt (1 -> 0)

- operation attempted:
  - `PUT repos/calebini/kinflow/branches/main/protection/required_pull_request_reviews`
- result: **FAILED** (`HTTP 404 Not Found`)
- evidence:
  - intended payload: `14_protection_patch_to0.json`
  - failure stderr captured in run output
  - post-failure protection check: `17_protection_after_failure_check.json` shows `required_approving_review_count=1`

## Merge execution

- status: **NOT EXECUTED** (blocked by inability to apply authorized temporary approval-policy adjustment)

## Restoration

- approval policy remained unchanged at `1`
- APPROVAL_POLICY_RESTORED: `YES` (no drift from baseline)

## Final verdict

- MERGE_TO_MAIN_STATUS: `FAILED`
- APPROVAL_POLICY_RESTORED: `YES`
- MAIN_HEAD_COMMIT_SHA: `UNMODIFIED_BY_RUN`
- failure_code: `RUNTIME_CAPABILITY_MISSING`
- failure_detail: `GitHub API permission/capability boundary prevented required_pull_request_reviews policy write (HTTP 404).`

## Finalization block

- RUN_FINALIZED: `YES`
- instruction_id: `KINFLOW-MERGE-APPROVAL-GATE-TEMP-OVERRIDE-20260327-001`
- run_id: `RUN-20260327T175758Z-4374`
- status: `FAILED`
- final_status: `FAILED`
- ready_for_landing: `NO`
- scope_breach: `false`
- rollback_path: `No merge commit and no policy mutation applied. Optional cleanup: remove evidence_root and report file.`
- evidence_root: `/home/agent/projects/_backlog/output/kinflow_merge_override_4374_20260327T175758Z/`
- completion_timestamp_utc: `2026-03-27T18:00:30Z`
