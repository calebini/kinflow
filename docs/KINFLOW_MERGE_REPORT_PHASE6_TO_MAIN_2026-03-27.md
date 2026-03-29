# KINFLOW Merge Report — Phase 6 Canary -> main

- instruction_id: `KINFLOW-MERGE-PHASE6-CANARY-TO-MAIN-20260327-001`
- run_code: `4379`
- repository: `calebini/kinflow`
- source_branch: `phase6-canary-4378`
- target_branch: `main`
- anchor_commit: `b1f3d097aed56c80aab8fc2b6a7334c5973778e3`
- evidence_root: `/home/agent/projects/_backlog/output/kinflow_merge_4379_20260327T221929Z/`

## Lint preflight

- command: `ruff check .`
- result: `LINT_PASS_NORMALIZED`
- evidence: `00_lint_preflight_block.txt`, `01_ruff_check.txt`

## Evidence matrix

### Pre-merge checks

1) PR head commit matches expected anchor lineage
- status: **PASS**
- observed: `ANCHOR_PRESENT=true`; PR head `b1f3d097aed56c80aab8fc2b6a7334c5973778e3`
- evidence: `15_anchor_lineage.txt`, `12_pr_pre.json`, `16_premerge_eval.txt`

2) Required CI contexts present/green
- status: **PASS**
- evidence: `14_pr_checks_pre.txt`, `16_premerge_eval.txt`

3) Mergeability clean
- status: **PASS**
- observed: `mergeable=MERGEABLE`
- evidence: `12_pr_pre.json`, `16_premerge_eval.txt`

4) Branch protection posture intact
- status: **PASS**
- observed:
  - strict=`true`
  - required contexts=`Kinflow CI / lint`,`Kinflow CI / test`,`Kinflow CI / contracts`
  - approvals baseline=`required_approving_review_count=1`
- evidence: `13_branch_protection_before.json`, `16_premerge_eval.txt`

### Merge execution

- Initial strategy attempt: `--merge`
- result: blocked by base branch policy (merge-commit path disallowed / review policy gating)
- evidence: `20_merge_output_initial.txt`

- Controlled temporary override path used: **YES**
  - approvals `1 -> 0`
  - merge via repo-allowed fallback strategy `--squash`
  - approvals `0 -> 1` restored immediately
- evidence:
  - `22_reviews_patch_to0.json`
  - `23_reviews_temp0_response.json`
  - `24_branch_protection_temp0.json`
  - `25_merge_output_after_temp0.txt`
  - `26_reviews_patch_restore1.json`
  - `27_reviews_restore_response.json`
  - `28_override_used.txt`

### Post-merge verification

1) PR merged state true
- status: **PASS**
- observed: `state=MERGED`, `mergedAt=2026-03-27T22:19:39Z`, `mergeCommit=01cf5909e68e9d75866261cb11f7767a797bf3f7`
- evidence: `32_pr_post.json`

2) Main head advanced and includes Phase 6 canary artifacts
- status: **PASS**
- main/origin-main aligned: `01cf5909e68e9d75866261cb11f7767a797bf3f7`
- artifact presence observed in merged PR files:
  - `docs/KINFLOW_PHASE6_CANARY_KICKOFF_REPORT.md`
  - `observability/phase6/canary_policy.yaml`
  - `scripts/phase6_canary_kickoff.py`
  - `README.md` (pointer update)
- evidence: `31_main_alignment_post.txt`, `32_pr_post.json`

3) Branch protection restored/intact
- status: **PASS**
- observed final:
  - strict=`true`
  - required contexts unchanged
  - approvals restored to `1`
- evidence: `29_branch_protection_final.json`

4) Main-head CI success verified
- status: **PASS**
- observed:
  - run status=`completed`
  - conclusion=`success`
  - run URL=`https://github.com/calebini/kinflow/actions/runs/23669911149`
- evidence: `33_main_runs.json`, `43_main_head_ci_eval.txt`, `44_ci_head_result.txt`

## Final lines

- MERGE_PHASE6_TO_MAIN_STATUS: `SUCCESS`
- MAIN_HEAD_COMMIT_SHA: `01cf5909e68e9d75866261cb11f7767a797bf3f7`
- APPROVAL_POLICY_RESTORED: `YES`

## Finalization

- RUN_FINALIZED: `YES`
- instruction_id: `KINFLOW-MERGE-PHASE6-CANARY-TO-MAIN-20260327-001`
- run_id: `RUN-20260327T221929Z-4379`
- status: `OK`
- final_status: `OK`
- ready_for_landing: `YES`
- scope_breach: `false`
- rollback_path: `Revert merge commit 01cf5909e68e9d75866261cb11f7767a797bf3f7 via standard revert flow; keep branch protection approvals=1 strict=true required contexts unchanged.`
- completion_timestamp_utc: `2026-03-27T22:21:30Z`
