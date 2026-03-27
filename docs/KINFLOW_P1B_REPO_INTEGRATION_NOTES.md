# Kinflow P1-B Repository Integration Notes

## Objective
Integrate persistence repositories into the deterministic engine state path (events/event_versions, reminders, receipts, audit, delivery targets) while preserving v0 behavior semantics.

## Scope boundary (P1-B only)
Implemented:
- Repository abstraction seam for core state operations.
- In-memory repository (parity baseline) and SQLite repository (persistence-backed path).
- Engine refactor to route state reads/writes through repository abstraction.
- Transaction-bound persistence behavior for create/update/cancel via repository methods.
- Persisted receipt replay behavior across engine restarts.

Not implemented in this packet:
- Comms adapter implementation.
- Daemon/recovery loop features.
- New product behaviors.

## File manifest

- `src/ctx002_v0/persistence/store.py`
  - `StateStore` protocol and concrete `InMemoryStateStore` + `SqliteStateStore`.
  - Repository-backed operations for events, versions, reminders, receipts, audit, and delivery targets.

- `src/ctx002_v0/engine.py`
  - Engine state plumbing refactor to repository-backed state access.
  - Preserves deterministic resolver/confirmation/lifecycle/timezone/dedupe semantics.

- `src/ctx002_v0/persistence/__init__.py`
  - Export repository interfaces and implementations.

- `tests/test_p1b_repo_integration.py`
  - P1-B targeted tests:
    - parity checks for create/update/cancel
    - transaction boundary sanity for event versions/current_version
    - persisted receipt replay behavior across engine restart

- `docs/KINFLOW_P1B_REPO_INTEGRATION_NOTES.md`
  - This implementation summary.

- `docs/KINFLOW_P1B_VERIFICATION_EVIDENCE.md`
  - Verification outputs and parity proof mapping.
