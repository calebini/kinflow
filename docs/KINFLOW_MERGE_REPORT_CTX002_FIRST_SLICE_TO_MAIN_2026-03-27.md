# KINFLOW Merge Report — ctx002-first-slice -> main

- instruction_id: `KINFLOW-MERGE-CTX002-FIRST-SLICE-TO-MAIN-20260327-001`
- run_code: `4370`
- execution_timestamp_utc: `2026-03-27T17:53:12Z`
- repository: `calebini/kinflow`
- source_branch: `ctx002-first-slice`
- target_branch: `main`
- evidence_root: `/home/agent/projects/_backlog/output/kinflow_merge_4370_20260327T175312Z/`

## Lint preflight

- command: `ruff check .`
- result: `LINT_PASS_NORMALIZED`
- evidence: `00_lint_preflight_block.txt`, `01_ruff_check.txt`

## Pre-merge gate matrix

1. Branch protection on `main` required checks + strict mode
   - status: **PASS**
   - evidence: `20_branch_protection.json`
   - observed:
     - strict: `true`
     - required checks: `Kinflow CI / lint`, `Kinflow CI / test`, `Kinflow CI / contracts`

2. Latest PR head commit required contexts present and green
   - status: **PASS**
   - evidence: `12_pr_view.json`, `21_pr_checks.txt`
   - observed PR head SHA: `3de6b8b244799a4a0034d03fd8aeae62310ff595`

3. Required review conditions unresolved
   - status: **FAIL**
   - evidence: `12_pr_view.json`, `22_mergeability_eval.txt`
   - observed: `reviewDecision=REVIEW_REQUIRED`, `mergeStateStatus=BLOCKED`

4. Behind/diverged condition invalidating mergeability
   - status: **PASS**
   - evidence: `22_mergeability_eval.txt`
   - observed: `mergeable=MERGEABLE` (no behind/diverged block reported)

## Merge execution

- command: `gh pr merge 1 --repo calebini/kinflow --merge --delete-branch=false`
- result: **blocked by base branch policy**
- evidence: `30_merge_command.txt`, `31_merge_status.txt`, `42_pr_post.json`
- observed message:
  - `Pull request calebini/kinflow#1 is not mergeable: the base branch policy prohibits the merge.`
  - `To have the pull request merged after all the requirements have been met, add the --auto flag.`

## Post-merge verification matrix

1. main contains expected rollout artifacts
   - status: **NOT EXECUTED (merge blocked)**

2. merged commit lineage includes latest validated gates
   - status: **NOT EXECUTED (merge blocked)**

3. CI checks on resulting main head are green
   - status: **PASS (current main head)**
   - evidence: `41_origin_main_head.txt`, `43_main_runs.json`
   - main head: `4c8095d073f39715b047ed5fba8874f743ca2561`
   - run conclusion: `success`

4. default-branch browser-visible surfaces reflect expected state
   - status: **NOT EXECUTED (merge blocked)**

## Verdict

- MERGE_TO_MAIN_STATUS: `BLOCKED`
- MAIN_HEAD_COMMIT_SHA: `4c8095d073f39715b047ed5fba8874f743ca2561`
- blocker_code: `MERGE_PRECONDITION_FAILED`
- blocker_detail: `Required review condition unresolved (reviewDecision=REVIEW_REQUIRED).`

## Finalization

- RUN_FINALIZED: `YES`
- instruction_id: `KINFLOW-MERGE-CTX002-FIRST-SLICE-TO-MAIN-20260327-001`
- run_id: `RUN-20260327T175312Z-4370`
- status: `BLOCKED`
- final_status: `BLOCKED`
- ready_for_landing: `NO`
- scope_breach: `false`
- rollback_path: `No merge commit created. Optional cleanup: remove evidence root and this report file if desired.`
- completion_timestamp_utc: `2026-03-27T17:56:30Z`
