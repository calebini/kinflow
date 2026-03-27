from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from ctx002_v0.persistence import (
    DEFAULT_MIGRATIONS_DIR,
    DirtyMigrationError,
    MigrationChecksumMismatchError,
    bootstrap_database,
    connect_sqlite,
    discover_migrations,
    enforce_foreign_keys,
    verify_migration_checksums,
)


class P1ASchemaMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "kinflow_p1a.sqlite")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_schema_create_and_forward_apply(self) -> None:
        conn = bootstrap_database(self.db_path)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        required = {
            "events",
            "event_versions",
            "delivery_targets",
            "reminders",
            "delivery_attempts",
            "message_receipts",
            "audit_log",
            "system_state",
            "schema_migrations",
            "enum_reason_codes",
            "enum_audit_stages",
            "enum_reminder_status",
            "enum_attempt_status",
        }
        self.assertTrue(required.issubset(tables))

        idx = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_reminders_trigger_at_utc_reminder_id'"
        ).fetchone()
        self.assertIsNotNone(idx)

    def test_checksum_mismatch_fail_stop(self) -> None:
        conn = bootstrap_database(self.db_path)
        row = conn.execute("SELECT version, checksum FROM schema_migrations LIMIT 1").fetchone()
        conn.execute(
            "UPDATE schema_migrations SET checksum = ? WHERE version = ?",
            ("bad-checksum", row["version"]),
        )
        conn.commit()

        with self.assertRaises(MigrationChecksumMismatchError):
            verify_migration_checksums(conn, discover_migrations(DEFAULT_MIGRATIONS_DIR))

    def test_dirty_sentinel_fail_stop(self) -> None:
        conn = bootstrap_database(self.db_path)
        row = conn.execute("SELECT version FROM schema_migrations LIMIT 1").fetchone()
        conn.execute("UPDATE schema_migrations SET dirty = 1 WHERE version = ?", (row["version"],))
        conn.commit()

        with self.assertRaises(DirtyMigrationError):
            verify_migration_checksums(conn, discover_migrations(DEFAULT_MIGRATIONS_DIR))

    def test_fk_pragma_enforcement(self) -> None:
        conn = connect_sqlite(self.db_path)
        enforce_foreign_keys(conn)
        fk_enabled = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        self.assertEqual(fk_enabled, 1)

    def test_enum_fk_rejection_for_invalid_values(self) -> None:
        conn = bootstrap_database(self.db_path)
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO audit_log(
                    ts_utc, trace_id, causation_id, correlation_id, message_id,
                    entity_type, entity_id, stage, reason_code, payload_schema_version, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "2026-03-21T00:00:00Z",
                    "trace-1",
                    "cause-1",
                    "corr-1",
                    "msg-1",
                    "event",
                    "evt-1",
                    "invalid_stage",
                    "invalid_reason",
                    1,
                    "{}",
                ),
            )


if __name__ == "__main__":
    unittest.main()
