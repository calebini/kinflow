# Kinflow P1-A Schema & Migrations Notes

## Scope boundary

This change set implements **Phase 1-A persistence foundation only**:
- SQLite schema materialization
- Enum table materialization + seeds
- Migration framework and registry with checksum/dirty semantics
- Startup DB enforcement hooks (FK pragma + checksum/dirty guards)
- Reason-code source binding validation scaffold

Out of scope for this packet:
- Comms adapter implementation
- Scheduler/recovery semantic rewiring
- Engine lifecycle behavior rewiring

## New artifact manifest (P1-A)

- `migrations/0001_p1a_schema_foundation.sql`
  - Canonical v0.2.6 schema foundation for events/event_versions/delivery_targets/reminders/delivery_attempts/message_receipts/audit_log/daily_overview_policy/system_state/system_state_policy plus enum tables and seeds.
  - Includes required index: `(trigger_at_utc, reminder_id)` for reminders.
  - Includes required FK and CHECK constraints (including composite FK reminders -> event_versions).

- `src/ctx002_v0/persistence/db.py`
  - Migration discovery/application primitives.
  - `schema_migrations` bootstrap + dirty sentinel guard.
  - Migration checksum verification fail-stop.
  - Startup FK enforcement primitive (`PRAGMA foreign_keys=ON` + fail-fast check).
  - `bootstrap_database(...)` entry point for P1-A DB bootstrap path.

- `src/ctx002_v0/persistence/reason_binding.py`
  - Canonical reason-code source binding validation scaffold (`version/hash/path` contract hook).

- `src/ctx002_v0/persistence/__init__.py`
  - Public exports for P1-A persistence primitives.

- `tests/test_p1a_schema_migrations.py`
  - P1-A verification tests:
    - forward migration/schema create
    - checksum mismatch fail-stop
    - dirty migration sentinel fail-stop
    - FK pragma enforcement
    - enum FK rejection for invalid values

- `docs/KINFLOW_P1A_SCHEMA_MIGRATIONS_NOTES.md`
  - This implementation summary.

- `docs/KINFLOW_P1A_VERIFICATION_EVIDENCE.md`
  - Command/evidence outputs for P1-A gates.
