source_message_id: 1484963253934358558
installed_by_instruction_id: KINFLOW-SPEC-INSTALL-PROD-PLAN-CHECKLIST-20260321-001
run_code: 4322
installed_utc: 2026-03-21T17:17:50Z
status: canonical

# Kinflow Production Plan Checklist

This checklist tracks production readiness at the level of required capability and gate status. Historical evidence packets are not active source material; executable tests and the freeze manifest are the current verification surface.

## Global Rules

- In-scope changes must be committed before phase exit.
- Public behavior changes must update the relevant spec or contract version.
- Runtime implemented-version declarations must match the freeze manifest.
- Pinned artifact changes require a freeze-manifest rebind.
- Phase exits require pin verification and the unittest suite to pass.

Required local gates:

```bash
python3 scripts/verify_contract_pins.py
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v
```

## Phase 0 - Baseline Lock

Status: PASS

- Requirements baseline installed.
- Architecture baseline installed.
- Persistence, comms, daemon, OC adapter, reason-code, and checklist artifacts pinned.
- Freeze manifest is the authoritative hash source.

## Phase 0.5 - Contract Freeze Gate

Status: PASS

- Reason-code registry pinned.
- Comms contract pinned.
- Persistence spec pinned.
- Runtime declarations and pin verifier installed.
- One-way freeze authority documented.

## Phase 1 - Persistence Core

Status: PASS

- SQLite schema and migrations implemented.
- FK and enum enforcement active.
- Repository interfaces integrated into the engine.
- Idempotency receipts and replay windows implemented.
- Version-conflict handling implemented.
- Recovery ordering and bounded batching implemented.
- Capture-only runtime constraints implemented.

## Phase 2 - Daemonization

Status: PASS for implemented baseline and adapter-facing runtime paths.

- Daemon runtime primitives implemented.
- Reconciliation loop behavior covered by tests and probes.
- Graceful shutdown and transactional safety covered by runner tests.
- Runtime config validation implemented.
- Health/state reporting wired.
- `tickerd` adapter path is the preferred foreground daemon integration.

## Phase 3 - Comms Adapter Integration

Status: PASS for current OpenClaw integration baseline.

- OpenClaw adapter integration implemented.
- Mapping precedence enforced.
- Replay and dedupe behavior covered by contract tests.
- Status/confidence coupling enforced.
- Capability and routing failures fail closed.
- Correlation propagation covered.

## Phase 4 - Operational Readiness

Status: IN PROGRESS

- Operator scripts exist for create, update, cancel, and smoke flows.
- Operations and rollback docs are current.
- Hardening drill runner exists.
- Incident playbook exists under `ops/playbooks/`.

Remaining exit work:

- Validate representative create, update, cancel, retry, and recovery flows against intended deployment environment.
- Confirm operator docs match the actual runtime invocation path.
- Capture current rollback receipt for production-bound deployment.

## Phase 5 - CI/CD And Migration Hardening

Status: IN PROGRESS

- CI workflow exists.
- Migration rehearsal script exists.

Remaining exit work:

- Confirm branch protection and required checks.
- Confirm backup, forward migration, and rollback rehearsal against production-like state.
- Publish current changelog or release notes when a release is cut.

## Phase 5.5 - Observability Minimum Bar

Status: IN PROGRESS

- Alert policy exists.
- SQLite signal query pack exists.
- Observability probe exists.

Remaining exit work:

- Validate thresholds against realistic traffic.
- Wire live dashboards or equivalent operator-facing readbacks.

## Phase 6 - Canary Rollout

Status: PLANNED

- Canary policy exists.
- Canary kickoff runner exists.

Remaining exit work:

- Enable limited cohort traffic.
- Monitor real-path telemetry.
- Execute incident response dry run during canary.

## Phase 7 - Full Production

Status: PLANNED

- Full rollout enabled.
- Post-launch coupling audit complete.
- Deferred evolution items triaged.
