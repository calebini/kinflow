# CTX-002 Golden Verification Script

## Files

- Script: `/home/agent/projects/apps/kinflow/ops/verify_ctx002_golden.sh`
- Env template: `/home/agent/projects/apps/kinflow/ops/verify_ctx002_golden.env.example`

## Purpose

Runs one canonical CTX-002 verification flow with deterministic stage ordering and PASS/FAIL verdict emission.

Ordered stages:
1. Compile check (`daemon_run.py`)
2. Targeted daemon-runner CTX-002 tests
3. Daemon restart (`sudo systemctl restart kinflow-daemon.service`)
4. Journal health evaluation (must include `cycle_summary` + `cycle_success=true`; fails on traceback/uncaught/fatal boundary failure signals)
5. Optional canary hook (`CANARY_COMMAND`) or SKIPPED when unset
6. DB delivery assertion on latest `delivery_attempts` row
7. Final verdict emission (`PASS` only when mandatory stages pass)

## Artifacts

Each run writes a timestamped directory:

`/home/agent/projects/_backlog/output/kinflow_verify_ctx002golden<UTCSTAMP>/`

Minimum artifacts generated per run:
- `compile_check.log`
- `targeted_tests.log`
- `daemon_restart.log`
- `journal_health.log`
- `canary_stage.log`
- `db_assertion.json`
- `summary.json`
- `final_verdict.txt`

## Prerequisites

- Python 3 available as `python3`
- `sudo` and `systemctl` available for non-dry-run
- Non-interactive sudo rights for restart/log inspection (`sudo -n`)
- Kinflow DB present at configured path

If sudo is unavailable in full mode, stage `daemon_restart` fails with explicit reason.

## Invocation Examples

### Minimal run

```bash
/home/agent/projects/apps/kinflow/ops/verify_ctx002_golden.sh
```

### Run with env template

```bash
set -a
source /home/agent/projects/apps/kinflow/ops/verify_ctx002_golden.env.example
set +a
/home/agent/projects/apps/kinflow/ops/verify_ctx002_golden.sh
```

### Run with canary command

```bash
CANARY_COMMAND='python3 /home/agent/projects/apps/kinflow/scripts/canary_fire.py --label ctx002-golden' \
/home/agent/projects/apps/kinflow/ops/verify_ctx002_golden.sh
```

### Non-mutating tooling dry-run (for script validation)

```bash
VERIFY_CTX002_GOLDEN_DRY_RUN=1 /home/agent/projects/apps/kinflow/ops/verify_ctx002_golden.sh
```

Dry-run mode skips destructive restart execution and is intended for script validation evidence. Because mandatory runtime stages are gated by restart/health, dry-run is expected to produce final verdict `FAIL`.

## PASS/FAIL Interpretation

- `PASS` => all mandatory stages succeeded:
  - compile_check
  - targeted_tests
  - daemon_restart
  - journal_health
  - db_assertion
- `FAIL` => one or more mandatory stages failed or were skipped by precondition.

Script exit code:
- `0` on PASS
- non-zero on FAIL
