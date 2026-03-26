# KINFLOW Operator Runbook (Phase 4 Hardening)

status: canonical
last_updated_utc: 2026-03-26T11:37:00Z

## Purpose

Provide deterministic operator procedures for startup/shutdown/restart handling, degraded-mode triage, and incident response in Kinflow hardening phase.

## Preconditions

- Work from repository root: `/home/agent/projects/apps/kinflow`
- Use UTC timestamps for evidence
- Preserve immutable evidence artifacts under `/home/agent/projects/_backlog/output/**`

## Startup validation sequence

1. Verify baseline lineage pin before operations:
   - `git merge-base --is-ancestor d5abf38 HEAD`
2. Run lint preflight:
   - `python3 -m compileall -q src scripts tests`
   - `ruff check .`
3. Run deterministic verification harnesses as needed:
   - `PYTHONPATH=src python3 scripts/p2c_e2e_runtime_probe.py --output-dir <evidence-root>`
   - `PYTHONPATH=src python3 scripts/phase4_hardening_drills.py --output-dir <evidence-root>`

Expected startup verdict: lint pass + probe/drill pass + non-empty evidence bundle.

## Controlled restart procedure (simulated/safe)

Use the Phase 4 drill runner for deterministic continuity checks without mutating host runtime service:

- Command:
  - `PYTHONPATH=src python3 scripts/phase4_hardening_drills.py --output-dir <evidence-root>`
- Drill ID:
  - `D1_CONTROLLED_RESTART`
- Success criteria:
  - initial cycle processes due row
  - post-restart cycle processes zero rows
  - no duplicate visible send
  - persisted delivery_attempt count stable across restart

## Degraded-mode handling

When provider/adapter behavior degrades:

1. Execute failure-injection parity check:
   - drill ID `D2_FAILURE_INJECTION`
2. Validate deterministic transient classification:
   - first attempt reason `FAILED_PROVIDER_TRANSIENT`
3. Validate recovery path:
   - next due attempt converges to `DELIVERED_SUCCESS`
4. Validate invariant:
   - `delivery_confidence=provider_confirmed => provider_accept_only=false`

If any check fails: classify as hardening blocker (`PHASE4_HARDENING_INCOMPLETE`).

## Incident triage checklist

1. Capture failing command + UTC timestamp.
2. Capture baseline lineage status and lint status.
3. Capture scenario/drill receipt(s) that failed.
4. Determine class:
   - deterministic mismatch
   - persistence violation
   - replay/duplicate-send risk
5. Produce incident evidence bundle and halt phase progression until resolved.

## Artifacts to attach per operator run

- baseline check output
- lint preflight output
- drill matrix + per-drill receipts
- integrity checks
- final gate verdict lines
