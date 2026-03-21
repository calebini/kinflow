# Kinflow P1-C Recovery / Capture-Only / Idempotency Notes

## Scope boundary

Implemented in this packet:
- Deterministic recovery/reconciliation primitive with ordered due-selection and bounded batching.
- Capture-only execution gating for delivery/recovery side-effect paths.
- Idempotency window enforcement (primary tuple replay + bounded secondary intent-hash replay).
- System policy reads from authoritative persisted state (`runtime_mode`, `idempotency_window_hours`, `max_retry_attempts`).

Not implemented in this packet:
- Comms adapter implementation.
- Daemon loop expansion / background worker framework.
- New product features.

## P1-C artifact manifest

- `src/ctx002_v0/engine.py`
  - Added primary replay identity and secondary idempotency-window replay path.
  - Added capture_only guards for delivery and recovery execution paths.
  - Added `run_reconciliation_batch(now_utc, batch_size=...)` deterministic recovery primitive.

- `src/ctx002_v0/persistence/store.py`
  - Added receipt tuple and intent-hash lookup APIs.
  - Added deterministic due-reminder selectors ordered by `(trigger_at_utc ASC, reminder_id ASC)`.
  - Added bounded due-count helper for continuation checks.
  - Added authoritative `system_state` reads/writes for runtime mode/window/retry policy.

- `src/ctx002_v0/reason_codes.py`
  - Added canonical reason codes used in P1-C paths:
    - `RECOVERY_RECONCILED`
    - `CAPTURE_ONLY_BLOCKED`

- `tests/test_p1c_recovery_capture_idempotency.py`
  - Added P1-C targeted tests for:
    - deterministic recovery ordering + bounded continuation
    - capture_only no-side-effect invariant
    - idempotency window replay hit/miss behavior

- `docs/KINFLOW_P1C_RECOVERY_CAPTURE_IDEMPOTENCY_NOTES.md`
  - This implementation note.

- `docs/KINFLOW_P1C_VERIFICATION_EVIDENCE.md`
  - Verification output + invariant proof map.
