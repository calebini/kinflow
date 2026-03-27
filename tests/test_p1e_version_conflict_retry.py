from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime

from ctx002_v0 import DeliveryTarget, FamilySchedulerV0, ReasonCode
from ctx002_v0.persistence.store import SqliteStateStore


def _create_intent(message_id: str) -> dict:
    return {
        "message_id": message_id,
        "correlation_id": f"corr-{message_id}",
        "channel": "discord",
        "conversation_id": "family",
        "action": "create",
        "title": "Conflict fixture",
        "start_at_local": datetime(2026, 3, 22, 12, 0),
        "participants": ("caleb",),
        "audience": ("caleb",),
        "reminder_offset_minutes": 30,
        "confirmed": True,
        "event_timezone": "Europe/Paris",
        "received_at_utc": datetime(2026, 3, 21, 22, 45, tzinfo=UTC),
    }


def _update_intent(message_id: str, event_id: str) -> dict:
    return {
        "message_id": message_id,
        "correlation_id": f"corr-{message_id}",
        "channel": "discord",
        "conversation_id": "family",
        "action": "update",
        "event_id": event_id,
        "title": "Conflict fixture updated",
        "start_at_local": datetime(2026, 3, 22, 12, 30),
        "participants": ("caleb",),
        "audience": ("caleb",),
        "reminder_offset_minutes": 30,
        "confirmed": True,
        "event_timezone": "Europe/Paris",
        "received_at_utc": datetime(2026, 3, 21, 22, 46, tzinfo=UTC),
    }


class P1EVersionConflictTests(unittest.TestCase):
    def test_version_conflict_retry_emission_and_no_partial_writes(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".sqlite") as tf:
            engine = FamilySchedulerV0(db_path=tf.name, household_timezone="Europe/Paris")
            engine.register_delivery_target(
                DeliveryTarget(
                    person_id="caleb",
                    channel="discord",
                    target_id="user:caleb",
                    timezone="Europe/Paris",
                )
            )

            created = engine.process_intent(_create_intent("seed"))
            self.assertEqual(created["status"], "ok")
            event_id = created["event_id"]

            store = engine._store  # type: ignore[attr-defined]
            self.assertIsInstance(store, SqliteStateStore)

            def conflict_injector(conn, event, expected_previous_version):
                src = conn.execute(
                    "SELECT * FROM event_versions WHERE event_id = ? AND version = ?",
                    (event.event_id, expected_previous_version),
                ).fetchone()
                next_version = expected_previous_version + 1
                exists = conn.execute(
                    "SELECT 1 FROM event_versions WHERE event_id = ? AND version = ?",
                    (event.event_id, next_version),
                ).fetchone()
                if src and not exists:
                    conn.execute(
                        """
                        INSERT INTO event_versions(
                            event_id,version,title,start_at_local_iso,end_at_local_iso,all_day,event_timezone,
                            participants_json,audience_json,reminder_offset_minutes,source_message_ref,
                            intent_hash,normalized_fields_hash,created_at_utc
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            src["event_id"],
                            next_version,
                            src["title"],
                            src["start_at_local_iso"],
                            src["end_at_local_iso"],
                            src["all_day"],
                            src["event_timezone"],
                            src["participants_json"],
                            src["audience_json"],
                            src["reminder_offset_minutes"],
                            src["source_message_ref"],
                            src["intent_hash"],
                            src["normalized_fields_hash"],
                            datetime.now(UTC).isoformat(),
                        ),
                    )
                conn.execute(
                    "UPDATE events SET current_version = ?, updated_at_utc = ? WHERE event_id = ?",
                    (next_version, datetime.now(UTC).isoformat(), event.event_id),
                )

            store.on_before_version_guard = conflict_injector

            result = engine.process_intent(_update_intent("conflict-1", event_id))
            self.assertEqual(result["status"], "conflict")
            self.assertEqual(result["persisted"], False)
            self.assertEqual(result["reason_code"], ReasonCode.VERSION_CONFLICT_RETRY.value)

            conn = store.conn
            partial_rows = conn.execute(
                "SELECT COUNT(*) AS n FROM event_versions WHERE event_id = ? AND source_message_ref = ?",
                (event_id, "conflict-1"),
            ).fetchone()["n"]
            self.assertEqual(partial_rows, 0)

            before_replay_versions = conn.execute(
                "SELECT COUNT(*) AS n FROM event_versions WHERE event_id = ?",
                (event_id,),
            ).fetchone()["n"]

            replay = engine.process_intent(_update_intent("conflict-1", event_id))
            after_replay_versions = conn.execute(
                "SELECT COUNT(*) AS n FROM event_versions WHERE event_id = ?",
                (event_id,),
            ).fetchone()["n"]

            self.assertEqual(replay, result)
            self.assertEqual(before_replay_versions, after_replay_versions)


if __name__ == "__main__":
    unittest.main()
