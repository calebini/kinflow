source_message_id: 1484963253934358558
installed_by_instruction_id: KINFLOW-SPEC-INSTALL-PROD-PLAN-CHECKLIST-20260321-001
run_code: 4322
installed_utc: 2026-03-21T17:17:50Z
status: canonical

Kinflow Production Plan Checklist (Master List)
Global Rule — Git Discipline (Phases 1–7)
No phase exits unless:
all in-scope changes committed
pushed to remote
PR/direct-land reference captured
evidence artifacts linked
rollback reference (commit/tag) recorded

---

Phase 0 — Baseline Lock
[x] Canonical specs installed + linked (requirements, architecture, persistence, comms adapter)
[x] Pointer integrity verified (README + backlog board)
[x] Open spec deltas resolved or explicitly deferred
Exit Gate: PASS — All canonical artifact hashes pinned; no unresolved blocking deltas.
Evidence:
- `/home/agent/projects/apps/kinflow/docs/KINFLOW_FREEZE_MANIFEST_INSTALL_4323_EVIDENCE.md`
- `/home/agent/projects/apps/kinflow/specs/KINFLOW_CONTRACT_FREEZE_MANIFEST_PHASE0_5.md`

Phase 0 completion annotations (concise):
- Baseline canonical pointers installed and verified in README + backlog board (run_code 4323 evidence).
- Pinned artifact hash table captured in freeze install evidence.

---

Phase 0.5 — Contract Freeze Gate
[x] Reason-code enum version/hash pinned
[x] Comms contract version pinned
[x] Persistence schema version pinned
[x] Change-control rule set documented (what may change, who approves, re-freeze trigger)

Exit Gate: PASS — Freeze manifest approved; implementation may proceed.
Evidence:
- `/home/agent/projects/apps/kinflow/specs/KINFLOW_CONTRACT_FREEZE_MANIFEST_PHASE0_5.md`
- freeze_authority_pointer: `artifact_path=/home/agent/projects/apps/kinflow/specs/KINFLOW_CONTRACT_FREEZE_MANIFEST_PHASE0_5.md`
- freeze_hash_display (informational, non-gating): `optional-display-only; authoritative hash is freeze §1`

Phase 0.5 completion annotations (concise):
- Freeze manifest installed via instruction `KINFLOW-FREEZE-MANIFEST-INSTALL-20260321-001` (run_code 4323).
- Change-control rules + deterministic block conditions documented in manifest.
- Authority model: checklist references freeze by stable artifact-path pointer; any displayed freeze hash in this checklist is informational only and cannot hard-fail gate checks.

---

Phase 1 — Persistence Core
[x] SQLite schema + migrations implemented
[x] FK/enum enforcement active
[x] Repository interfaces integrated into engine
[x] Idempotency receipts + window logic implemented
[x] Version guard + conflict handling (VERSION_CONFLICT_RETRY) implemented
[x] Recovery ordering + bounded batching implemented
[x] Capture-only persistence/runtime constraints implemented

Exit Gate: PASS — Durability/replay/version-conflict/recovery tests pass with zero invariant violations.
Evidence: `/home/agent/projects/apps/kinflow/docs/KINFLOW_PHASE1_EXIT_EVIDENCE_MASTER.md`
sha256: `e59ea46fc819976545f6ef73ccdc8d2f683bed784b8b96d0d546e566e6b1b3b8`
Git Gate: PASS.

Phase 1 completion annotations (concise):
- P1-A landed refs: impl `77a25e6`; landing `2e3f380`
- P1-B landed refs: impl `50e6767`; landing `e9ff393`
- P1-C + P1-E closure refs: impl `dba4853` + `4289f94`; landing `2d79983`

---

Phase 2 consolidated exit status (P2-A/P2-B/P2-C)
Result: PASS
Evidence:
- `/home/agent/projects/apps/kinflow/docs/KINFLOW_PHASE2_EXIT_EVIDENCE_MASTER.md`
- `/home/agent/projects/apps/kinflow/docs/KINFLOW_P2B_OC_ADAPTER_CONFORMANCE_EVIDENCE.md` (commit `90474f6`)
- `/home/agent/projects/apps/kinflow/docs/KINFLOW_P2C_E2E_RUNTIME_VERIFICATION_REPORT.md` (commit `d4c079c`)
Gate lineage:
- `P2B_IMPLEMENTATION_READY_FOR_LANDING: YES`
- `P2C_VERIFICATION_GATE: GO`
- `PHASE2_EXIT_READY: YES`

---

Phase 2 — Daemonization
[ ] Scheduler heartbeat loop implemented
[ ] Reconciliation loop implemented
[ ] Graceful shutdown + transactional safety implemented
[ ] Runtime config validation implemented
[ ] Health/state reporting wired
[ ] Structured logs with trace/causation IDs emitted

Exit Gate: Restart/failure drills pass; deterministic progression; no duplicate visible sends.
Git Gate: Required.

---

Phase 3 — Comms Adapter Integration (OpenClaw first)
[ ] CommsAdapter interface implemented in runtime path
[ ] OpenClawGatewayAdapter implemented
[ ] Mapping precedence contract enforced
[ ] Replay/dedupe contract enforced
[ ] Status/confidence coupling enforced
[ ] Capability allowlist + block behavior enforced
[ ] Correlation propagation enforced

Exit Gate: 0 adapter contract violations across evidence suite; no mapping drift.
Git Gate: Required.

---

Phase 4 hardening kickoff status
Result: GO
Evidence:
- `/home/agent/projects/apps/kinflow/docs/KINFLOW_PHASE4_HARDENING_KICKOFF_REPORT.md`
- `/home/agent/projects/apps/kinflow/docs/KINFLOW_OPERATOR_RUNBOOK_PHASE4.md`
- `/home/agent/projects/apps/kinflow/docs/KINFLOW_ROLLBACK_RUNBOOK_PHASE4.md`
Gate lineage:
- `PHASE4_HARDENING_GATE: GO`
- `READY_FOR_PHASE5: YES`

---

Phase 4 — End-to-End Operational Readiness
[ ] Create flow end-to-end verified
[ ] Update invalidation/regeneration verified
[ ] Cancel suppression verified
[ ] Retry/recovery/write-amplification invariants validated
[ ] Operator runbook complete
[ ] Incident playbook complete

Exit Gate: All E2E flows pass with deterministic receipts and full audit reconstruction.
Git Gate: Required.

---
Phase 5 — CI/CD + Migration Hardening
[ ] CI required checks enforced
[ ] Branch protections enabled
[ ] Conformance artifacts published per build
[ ] Version/changelog policy enforced
[ ] Data migration rehearsal completed:
[ ] backup/restore
[ ] forward migration
[ ] rollback with audit integrity preserved

Exit Gate: CI policy active + migration rehearsal clean.
Git Gate: Required.

---

Phase 5.5 — Observability Minimum Bar
[ ] Dashboard live with:
[ ] duplicate-send rate
[ ] retry-exhaustion rate
[ ] blocked/TZ_MISSING rate
[ ] Alert thresholds configured
[ ] Thresholds validated against realistic traffic shape

Exit Gate: Metrics and alerts are operational with acceptable noise characteristics.
Git Gate: Required (for config/runbook changes).

---

Phase 6 — Canary Rollout
[ ] Limited traffic canary enabled
[ ] Real-path telemetry monitored
[ ] Incident response dry-run executed during canary

Exit Gate: Canary reliability thresholds met; no Sev-1/2 contract violations.
Git Gate: Required.

---

Phase 7 — Full Production
[ ] Full rollout enabled
[ ] Post-launch coupling audit complete
[ ] Deferred T5 evolution items triaged/planned
[ ] SLO tracking active for soak window

Exit Gate: SLO stability confirmed over soak period; rollback path still validated.
Git Gate: Required.

---

Production Readiness Definition
Kinflow is production-ready when:
deterministic + durable behavior proven under replay/recovery,
transport contract conformance holds,
observability and incident controls are active,
and every phase is landed/traceable in git.