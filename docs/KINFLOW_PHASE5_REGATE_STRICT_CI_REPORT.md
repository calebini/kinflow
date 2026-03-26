# KINFLOW Phase 5 Re-Gate (Strict CI Evidence)

instruction_id: KINFLOW-PHASE5-REGATE-STRICT-CI-EVIDENCE-20260326-001  
run_code: 4368  
status: canonical  
report_timestamp_utc: 2026-03-26T20:31:00Z  
evidence_root: `/home/agent/projects/_backlog/output/kinflow_phase5_regate_4368_20260326T202732Z/`

## 1) Baseline lineage lock

Required remediation lineage anchors:
- `6c30126`
- `eff3fa0`
- `1dcc0dd`

Verification:
- `git merge-base --is-ancestor <commit> HEAD` for each anchor

Result: **PASS**  
Evidence: `00_baseline_lineage_check.txt`

## 2) Lint preflight

Allowed continuation states: `LINT_PASS` or `LINT_PASS_NORMALIZED`.

Result: **LINT_PASS**  
Evidence: `01_lint_preflight.txt`

## 3) Strict CI evidence (GitHub authoritative)

Latest 5 `Kinflow CI` runs collected with run_id/branch/commit and job statuses:
- Raw list: `02_ci_runs_latest5.json`
- Enriched per-run details: `03_ci_runs_latest5_enriched.json`
- Ledger CSV: `04_ci_run_ledger_latest5.csv`
- Ledger table (markdown): `04b_ci_run_ledger_latest5.md`
- Per-run detail snapshots:
  - `run_23611842410_detail.json`
  - `run_23611840726_detail.json`
  - `run_23611753562_detail.json`
  - `run_23611751510_detail.json`
  - `run_23611678681_detail.json`

### CI run ledger (latest 5)

| run_id | branch | commit_sha | lint | test | contracts | verdict |
|---:|---|---|---|---|---|---|
| 23611842410 | ctx002-first-slice | 1dcc0dd777b1 | success | success | success | GREEN |
| 23611840726 | ctx002-first-slice | 1dcc0dd777b1 | success | success | success | GREEN |
| 23611753562 | ctx002-first-slice | eff3fa0ae328 | success | success | success | GREEN |
| 23611751510 | ctx002-first-slice | eff3fa0ae328 | success | success | success | GREEN |
| 23611678681 | ctx002-first-slice | 6c301262e9ef | success | failure | failure | NOT_GREEN |

## 4) Protected-branch (main) required-check binding verdict

Protected branch discovery:
- branch: `main`
- HEAD commit: `2e8afffcb1c6e050b9663eaa38098334447398c7`

Evidence:
- branch info: `05_main_branch.json`
- branch protection readback: `06_main_branch_protection.json`
- check-runs on HEAD: `07_main_head_check_runs.json`
- status contexts on HEAD: `08_main_head_status_contexts.json`
- strict verdict synthesis: `09_main_head_required_checks_verdict.json`

Required-check enforcement verification:
- Configured contexts exactly match required list: **YES**
  - `Kinflow CI / lint`
  - `Kinflow CI / test`
  - `Kinflow CI / contracts`
- strict mode enabled: **YES**

HEAD_COMMIT_SHA: `2e8afffcb1c6e050b9663eaa38098334447398c7`  
REQUIRED_CHECKS_ALL_GREEN: **NO**

Reason:
- For protected-branch HEAD commit, required contexts are currently missing in authoritative check/status APIs (`missing`, not green).

## 5) Migration evidence linkage (from 4366)

No migration re-run was required for this packet.

Linked prior evidence:
- 4366 evidence root: `/home/agent/projects/_backlog/output/kinflow_phase5_hardening_4366_20260326T173849Z/`
- prior migration rehearsal matrix: `09_migration_rehearsal_matrix.md`
- prior aggregate migration verdict: `migration_matrix.json` (`all_pass=true`)

## 6) Re-gate decision

Gate rule: `PHASE5_HARDENING_GATE = GO` only if required checks are green for protected-branch HEAD commit.

Observed protected-branch HEAD required checks: **NOT ALL GREEN** (missing).

Per packet contract, fail-stop code applies: `PHASE5_REGATE_CI_RED_REQUIRED_CHECKS`.

PHASE5_HARDENING_GATE: NO_GO  
BLOCKERS: 1  
RESIDUAL_RISKS: 1  
READY_FOR_PHASE5_5_OR_6: NO

## 7) Rollback path

- `git -C /home/agent/projects/apps/kinflow checkout -- docs/KINFLOW_PHASE5_REGATE_STRICT_CI_REPORT.md`
