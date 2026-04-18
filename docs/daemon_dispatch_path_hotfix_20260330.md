# Daemon Dispatch Path Hotfix (2026-03-30)

## RCA

The runner was wiring daemon callbacks as stubs:
- `list_candidates=lambda: []`
- `process_candidate=lambda _row: True`
- `run_reconcile=lambda: True`

That allowed healthy loop ticks but prevented store-backed overdue reminder scanning, delivery attempt persistence, and delivery-stage audit records.

## Fix Summary

Updated `scripts/daemon_run.py` to wire store-backed dispatch callbacks:
- `DispatchCallbacks.list_candidates()` queries due reminders from sqlite store.
- `DispatchCallbacks.process_candidate()` executes reminder processing path and persists:
  - reminder status transitions
  - `delivery_attempts` rows
  - delivery-stage `audit_log` rows
- `DispatchCallbacks.run_reconcile()` is store-backed and reconciles due attempted reminders.
- Added startup guard for incomplete wiring:
  - `DISPATCH_PATH_WIRING_INCOMPLETE`
- Added no-op wiring fail token support:
  - `DISPATCH_PATH_NOOP_WIRING_DETECTED`

## Verification

- unit test for no-op/incomplete wiring guard
- unit test seeding overdue reminder and asserting:
  - non-zero rows scanned
  - reminder processed
  - `delivery_attempts` persistence
  - delivery-stage audit persistence
