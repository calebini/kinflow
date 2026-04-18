# KINFLOW Daemon Runner Landing Validation Report (run 4402)

- instruction_id: `KINFLOW-DAEMON-RUNNER-LANDING-V013-20260330-001`
- run_code: `4402`
- timestamp_utc: `2026-03-30T21:11:38Z`
- source_evidence_root: `/home/agent/projects/_backlog/output/kinflow_daemon_runner_implement_v013_4401_20260330T200520Z`
- landing_evidence_root: `/home/agent/projects/_backlog/output/kinflow_daemon_runner_landing_v013_4402_20260330T211138Z`

## Gate Results
- receipt_cross_check: PASS
- scope_path_exact_match(commit 6da47fd): PASS
- py_compile: PASS
- unittest_runner: PASS
- unittest_regression_subset: FAIL
- terminal_jsonline_behavior: PASS (artifact check)
- fail_token_surface: PASS (artifact check)
- canonical_branch_landing: PASS

## Final
- LANDING_STATUS: NO_GO
- RUNTIME_SAFE: YES
- BLOCKERS: 1
