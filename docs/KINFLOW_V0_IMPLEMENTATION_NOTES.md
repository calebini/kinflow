# Kinflow v0 deterministic core — implementation notes

## Implemented artifact set

- `src/ctx002_v0/reason_codes.py`
  - Canonical reason-code enum IDs (no free-text drift).
- `src/ctx002_v0/models.py`
  - Deterministic data contracts for `Event`, `Reminder`, `DeliveryTarget`, and append-only `AuditRecord`.
- `src/ctx002_v0/engine.py`
  - v0 deterministic intake pipeline, follow-up loop, confirmation gate, create-vs-update resolver precedence, lifecycle mutation behavior, timezone contract, reminder scheduler/delivery, bounded retry + dedupe, and immutable audit append.
- `tests/test_acceptance_v0.py`
  - Acceptance harness for deterministic behavior requirements (resolver ambiguity block, replay/idempotency, regeneration drift, timezone constraints including cross-timezone/DST fixture, retry/recovery no-duplicate delivery).
- `pyproject.toml`
  - Local project tooling config.
- `docs/KINFLOW_V0_VERIFICATION_EVIDENCE.md`
  - Lint preflight and verification output evidence.
- `docs/KINFLOW_V0_KNUTH_LANDING_HANDOFF.md`
  - Landing package for execution handoff.

## Deterministic flow implemented

1. Intake
2. Parse/classify + required field check
3. Missing-field follow-up (required fields only)
4. Create-vs-update resolver (explicit > deterministic match > ambiguity block > create)
5. Explicit confirmation gate (no persistence without yes)
6. Persistence (create/update/cancel)
7. Trigger generation / invalidation / regeneration
8. Delivery attempt lifecycle + retries + dedupe
9. Append-only audit log with correlation references
