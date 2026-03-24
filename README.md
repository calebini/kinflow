# Kinflow

## What It Is

Kinflow is a deterministic, chat-first family scheduling coordinator.

It captures event intent from chat, resolves create/update/cancel actions, enforces explicit confirmation before persistence, and drives reliable daily briefs and reminders with audit-first traceability.

Kinflow is designed for:
- predictable behavior under ambiguity
- policy-bounded delivery
- clear lifecycle evidence for every state transition
---

## Core Concepts

**Event**
A versioned scheduling record (title, time semantics, participants, audience, status) that acts as the source of truth.

**ReminderRule**
Policy for pre-event reminders (offset, recipient scope, enabled state).

**Trigger / Job**
A scheduled execution unit:
- `daily_overview`
- `event_reminder`
**DeliveryAttempt**
A concrete outbound attempt with status and failure/suppression reason.

**Resolver**
Deterministic create-vs-update decision path:
1. explicit event reference
2. deterministic similarity match
3. ambiguity block (requires user disambiguation)
4. no match → create

**Policy Reason Codes**
Canonical enum IDs (no free-text drift) used for resolver/time/lifecycle/delivery decisions.

---
## Architecture

Chat Ingress
│
Intake Orchestrator
├─ Intent Parser (fields + confidence)
├─ Resolver (create/update/cancel precedence)
├─ Confirmation Gate (hard yes/no before persist)
│
Event Store (versioned event state)
│
Scheduler / Trigger Engine
├─ Reminder generation/invalidation/regeneration
├─ Daily overview scheduling
│
Delivery Engine
├─ Group/individual routing
├─ Quiet-hours enforcement (recipient-local time)
├─ Bounded retries + dedupe gate
│
Audit Ledger (append-only lifecycle records)

Core references:
- Requirements baseline: `requirements/KINFLOW_MASTER_REQUIREMENTS_UNIFIED_V0.md`
- Architecture baseline: `architecture/KINFLOW_V0_ARCHITECTURE_BRIEF_MASTER.md`


## Canonical Persistence Spec

- `specs/KINFLOW_DURABLE_PERSISTENCE_SPEC_MASTER_v0.2.6.md`

---

## Canonical Comms Adapter Spec

- `specs/KINFLOW_COMMS_ADAPTER_CONTRACT_MASTER_v0.1.7.md`

## Canonical Production Plan Checklist

- `specs/KINFLOW_PRODUCTION_PLAN_CHECKLIST_MASTER.md`

## Canonical Daemon Runtime Contract

- `specs/KINFLOW_DAEMON_RUNTIME_CONTRACT_MASTER_v0.1.4.md`

## Canonical OpenClaw Adapter Implementation Spec

- `specs/KINFLOW_OC_ADAPTER_IMPLEMENTATION_SPEC_MASTER_v0.2.4.md`

## Canonical Reason Code Registry

- `specs/KINFLOW_REASON_CODES_CANONICAL.md`

## Key Behaviors
### Idempotency
Same intent fingerprint + same state resolves to same terminal mutation.

### Resolver correctness
Ambiguity never auto-resolves; explicit references always win.

### Reminder regeneration
Event update invalidates future old-version reminders and regenerates deterministic new set.

### Cancel propagation
Event cancel invalidates all future pending reminders.

### Timezone safety
- Event timezone = event semantics
- Recipient timezone = delivery timing + quiet-hours
- Missing recipient timezone blocks delivery scheduling (`TZ_MISSING`)

### Delivery reliability
- bounded retries
- dedupe before send
- no duplicate user-visible delivery for same dedupe key

### Auditability
Every lifecycle step emits append-only, correlated audit events with reason codes.

---

## Data Flow (Happy Path)

1. Intake user message
2. Parse/classify intent + required fields
3. Ask follow-up only for missing required fields
4. Resolve create/update/cancel target deterministically
5. Normalize event candidate
6. Confirmation gate (`Save this event? yes/no`)
7. Persist event mutation (versioned)
8. Generate/invalidate triggers
9. Execute due delivery attempts
10. Record delivery + audit outcomes

---

## Key Files

- `src/ctx002_v0/engine.py` — deterministic lifecycle engine
- `src/ctx002_v0/daemon.py` — P2-A daemon baseline primitives (contract v0.1.4 aligned)
- `src/ctx002_v0/models.py` — Event/Reminder/Delivery contracts
- `src/ctx002_v0/reason_codes.py` — canonical reason-code enums
- `src/ctx002_v0/persistence/db.py` — P1-A migration/bootstrap/FK/checksum/dirty enforcement primitives
- `src/ctx002_v0/persistence/reason_binding.py` — canonical reason-code source binding validation scaffold
- `src/ctx002_v0/persistence/store.py` — repository abstraction + in-memory/sqlite state stores
- `migrations/0001_p1a_schema_foundation.sql` — canonical SQLite schema + enum seeds (v0.2.6-aligned)
- `tests/test_acceptance_v0.py` — deterministic acceptance harness
- `tests/test_p1a_schema_migrations.py` — P1-A schema/migration guard test suite
- `tests/test_p1b_repo_integration.py` — P1-B repository integration suite
- `tests/test_p1c_recovery_capture_idempotency.py` — P1-C recovery/capture/idempotency invariant suite
- `tests/test_p2a_daemon_baseline.py` — P2-A daemon baseline contract conformance suite
- `docs/KINFLOW_V0_IMPLEMENTATION_NOTES.md` — implementation mapping
- `docs/KINFLOW_V0_VERIFICATION_EVIDENCE.md` — lint/test evidence
- `docs/KINFLOW_V0_KNUTH_LANDING_HANDOFF.md` — landing handoff
- `docs/PROJECT_RENAME_CTX002_TO_KINFLOW.md` — rename/migration note
- `docs/KINFLOW_P1A_SCHEMA_MIGRATIONS_NOTES.md` — P1-A scope and artifact notes
- `docs/KINFLOW_P1A_VERIFICATION_EVIDENCE.md` — P1-A verification evidence
- `docs/KINFLOW_P1B_REPO_INTEGRATION_NOTES.md` — P1-B repository integration notes
- `docs/KINFLOW_P1B_VERIFICATION_EVIDENCE.md` — P1-B verification evidence
- `docs/KINFLOW_P1C_RECOVERY_CAPTURE_IDEMPOTENCY_NOTES.md` — P1-C recovery/capture/idempotency notes
- `docs/KINFLOW_P1C_VERIFICATION_EVIDENCE.md` — P1-C verification evidence
- `docs/KINFLOW_P2A_DAEMON_BASELINE_NOTES.md` — P2-A daemon baseline implementation notes
- `docs/KINFLOW_P2A_VERIFICATION_EVIDENCE.md` — P2-A contract verification evidence and matrix
- `docs/KINFLOW_PHASE1_EXIT_EVIDENCE_MASTER.md` — Phase 1 exit criteria assessment and evidence matrix
- `docs/KINFLOW_OC_GATEWAY_ASSUMPTION_PROBE.md` — deterministic gateway assumption probe evidence (Discord/WhatsApp/error-shape)
- `docs/KINFLOW_SPEC_FAMILY_ALIGNMENT_REPORT_2026-03-24.md` — cross-spec alignment packet report for issues #1–#16
- `specs/KINFLOW_CONTRACT_FREEZE_MANIFEST_PHASE0_5.md` — Phase 0.5 canonical freeze manifest (pinned versions + hashes + change-control)

---

## Verification

Run from project root:
```bash
python3 -m compileall -q src scripts tests && echo LINT_PASS_NORMALIZED
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v
PYTHONPATH=src python3 -m unittest -v tests.test_p1a_schema_migrations
```
Expected:
- `LINT_PASS_NORMALIZED`
- `Ran 9 tests ...`
- `OK`

## Operator Scripts (copy/paste)

Run from project root:
```bash
PYTHONPATH=src python3 scripts/operator_smoke.py
PYTHONPATH=src python3 scripts/operator_create.py
PYTHONPATH=src python3 scripts/operator_update.py
PYTHONPATH=src python3 scripts/operator_cancel.py
```

Script purposes:
- `scripts/operator_smoke.py` — one-pass create + delivery + brief/hash sanity check.
- `scripts/operator_create.py` — deterministic create flow and due reminder delivery output.
- `scripts/operator_update.py` — create then explicit update flow with regeneration-aware delivery output.
- `scripts/operator_cancel.py` — create then cancel flow showing cancellation state and post-cancel delivery output.

---

## Current Status / Known Gaps

- v0 deterministic core implemented and verified.
- Calendar integrations are intentionally out-of-scope for v0.
- Persistence/deployment hardening may still require follow-on phases.
- GitHub square-one hygiene/CI standardization should be completed and enforced as policy gates.
