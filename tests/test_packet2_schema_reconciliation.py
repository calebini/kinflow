from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ctx002_v0.persistence.db import apply_migrations, connect_sqlite, discover_migrations, enforce_foreign_keys


class Packet2SchemaReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "kinflow_packet2.sqlite")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _conn(self):
        conn = connect_sqlite(self.db_path)
        enforce_foreign_keys(conn)
        return conn

    def test_migration_apply_on_clean_db(self) -> None:
        conn = self._conn()
        apply_migrations(conn, discover_migrations())

        statuses = {r[0] for r in conn.execute("SELECT status FROM enum_attempt_status").fetchall()}
        self.assertIn("blocked", statuses)

        reason_codes = {r[0] for r in conn.execute("SELECT code FROM enum_reason_codes").fetchall()}
        self.assertIn("DELIVERED_SUCCESS", reason_codes)
        self.assertNotIn("DELIVERED", reason_codes)

        classes = {r[0] for r in conn.execute("SELECT DISTINCT class FROM enum_reason_codes").fetchall()}
        self.assertEqual(
            classes,
            {"success", "mutation", "blocked", "runtime", "transient", "permanent", "suppressed"},
        )

        cols = {r[1] for r in conn.execute("PRAGMA table_info(delivery_attempts)").fetchall()}
        self.assertTrue(
            {
                "provider_status_code",
                "provider_error_text",
                "provider_accept_only",
                "delivery_confidence",
                "result_at_utc",
                "trace_id",
                "causation_id",
                "source_adapter_attempt_id",
            }.issubset(cols)
        )

    def test_apply_on_preexisting_db_shape_then_reconcile(self) -> None:
        conn = self._conn()
        all_migrations = discover_migrations()
        apply_migrations(conn, [m for m in all_migrations if m.version == "0001_p1a_schema_foundation"])
        apply_migrations(conn, all_migrations)

        row = conn.execute("SELECT 1 FROM enum_attempt_status WHERE status='blocked'").fetchone()
        self.assertIsNotNone(row)

    def test_fk_enum_insert_checks_blocked_and_delivered_success(self) -> None:
        conn = self._conn()
        apply_migrations(conn, discover_migrations())

        conn.execute(
            "INSERT INTO events(event_id,current_version,status,created_at_utc,updated_at_utc) VALUES (?,?,?,?,?)",
            ("evt-1", 1, "active", "2026-03-24T00:00:00+00:00", "2026-03-24T00:00:00+00:00"),
        )
        conn.execute(
            """
            INSERT INTO event_versions(
                event_id,version,title,start_at_local_iso,end_at_local_iso,all_day,event_timezone,
                participants_json,audience_json,reminder_offset_minutes,source_message_ref,
                intent_hash,normalized_fields_hash,created_at_utc
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "evt-1",
                1,
                "t",
                "2026-03-24T10:00:00",
                None,
                0,
                "UTC",
                "[]",
                '["p1"]',
                15,
                "m1",
                "h1",
                "h2",
                "2026-03-24T00:00:00+00:00",
            ),
        )
        conn.execute(
            "INSERT INTO delivery_targets(target_id,person_id,channel,target_ref,timezone,updated_at_utc) "
            "VALUES (?,?,?,?,?,?)",
            ("p1", "p1", "discord", "user:p1", "UTC", "2026-03-24T00:00:00+00:00"),
        )
        conn.execute(
            """
            INSERT INTO reminders(
                reminder_id,dedupe_key,event_id,event_version,recipient_target_id,offset_minutes,
                trigger_at_utc,next_attempt_at_utc,attempts,status,recipient_timezone_snapshot,tz_source,
                last_error_code,created_at_utc,updated_at_utc
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "rem-1",
                "dedupe-1",
                "evt-1",
                1,
                "p1",
                15,
                "2026-03-24T09:45:00+00:00",
                None,
                0,
                "scheduled",
                "UTC",
                "EXPLICIT",
                None,
                "2026-03-24T00:00:00+00:00",
                "2026-03-24T00:00:00+00:00",
            ),
        )

        conn.execute(
            """
            INSERT INTO delivery_attempts(
                attempt_id, reminder_id, attempt_index, attempted_at_utc, status, reason_code,
                provider_ref, provider_status_code, provider_error_text, provider_accept_only,
                delivery_confidence, result_at_utc, trace_id, causation_id, source_adapter_attempt_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "att-1",
                "rem-1",
                1,
                "2026-03-24T09:45:00+00:00",
                "blocked",
                "DELIVERED_SUCCESS",
                "provider-ref",
                "ok",
                None,
                0,
                "provider_confirmed",
                "2026-03-24T09:45:00+00:00",
                "trace-1",
                "cause-1",
                None,
            ),
        )


if __name__ == "__main__":
    unittest.main()
