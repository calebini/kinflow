from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta

from ctx002_v0 import DeliveryTarget, FamilySchedulerV0, ReasonCode


def _intent(
    message_id: str,
    *,
    start_at_local: datetime,
    intent_hash: str,
    received_at_utc: datetime,
) -> dict:
    return {
        "message_id": message_id,
        "correlation_id": f"corr-{message_id}",
        "channel": "discord",
        "conversation_id": "family",
        "intent_hash": intent_hash,
        "action": "create",
        "title": "Recurring school run",
        "start_at_local": start_at_local,
        "participants": ("caleb", "wife"),
        "audience": ("caleb",),
        "reminder_offset_minutes": 30,
        "confirmed": True,
        "event_timezone": "Europe/Paris",
        "received_at_utc": received_at_utc,
    }


class P1CRecoveryCaptureIdempotencyTests(unittest.TestCase):
    def test_recovery_ordering_and_bounded_continuation(self) -> None:
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

            engine.process_intent(
                _intent(
                    "r1",
                    start_at_local=datetime(2026, 3, 22, 10, 0),
                    intent_hash="ih-r1",
                    received_at_utc=datetime(2026, 3, 21, 22, 0, tzinfo=UTC),
                )
            )
            engine.process_intent(
                _intent(
                    "r2",
                    start_at_local=datetime(2026, 3, 22, 10, 5),
                    intent_hash="ih-r2",
                    received_at_utc=datetime(2026, 3, 21, 22, 1, tzinfo=UTC),
                )
            )

            now = datetime(2026, 3, 22, 8, 40, tzinfo=UTC)
            due = list(engine._store.list_due_reminders(now, limit=2))  # type: ignore[attr-defined]
            for reminder in due:
                reminder.status = "attempted"
                reminder.next_attempt_at_utc = now - timedelta(minutes=1)
                engine._store.update_reminder(reminder)  # type: ignore[attr-defined]

            ordered_before = list(engine._store.list_due_reminders(now, limit=2))  # type: ignore[attr-defined]
            out = engine.run_reconciliation_batch(now, batch_size=1)
            ordered_after = list(engine._store.list_due_reminders(now, limit=2))  # type: ignore[attr-defined]

            self.assertEqual(out["processed"], 1)
            self.assertTrue(out["has_more"])
            self.assertEqual(out["reason_code"], ReasonCode.RECOVERY_RECONCILED.value)
            self.assertEqual(ordered_before[0].reminder_id, ordered_after[0].reminder_id)
            self.assertEqual(ordered_after[0].status, "scheduled")
            self.assertTrue(any(a.reason_code == ReasonCode.RECOVERY_RECONCILED for a in engine.audit))

    def test_capture_only_blocks_side_effect_paths(self) -> None:
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
            engine.process_intent(
                _intent(
                    "c1",
                    start_at_local=datetime(2026, 3, 22, 10, 0),
                    intent_hash="ih-c1",
                    received_at_utc=datetime(2026, 3, 21, 22, 0, tzinfo=UTC),
                )
            )
            engine.set_runtime_mode("capture_only")

            calls = {"n": 0}

            def provider(_):
                calls["n"] += 1
                return True

            before = [(r.dedupe_key, r.status, r.attempts) for r in engine.reminders]
            delivery = engine.attempt_due_deliveries(datetime(2026, 3, 22, 8, 0, tzinfo=UTC), provider)
            recon = engine.run_reconciliation_batch(datetime(2026, 3, 22, 8, 0, tzinfo=UTC), batch_size=10)
            after = [(r.dedupe_key, r.status, r.attempts) for r in engine.reminders]

            self.assertEqual(calls["n"], 0)
            self.assertEqual(delivery, [("capture_only", ReasonCode.CAPTURE_ONLY_BLOCKED)])
            self.assertEqual(recon["reason_code"], ReasonCode.CAPTURE_ONLY_BLOCKED.value)
            self.assertEqual(before, after)

    def test_idempotency_window_replay_hit_and_miss(self) -> None:
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

            t0 = datetime(2026, 3, 21, 20, 0, tzinfo=UTC)
            a = engine.process_intent(
                _intent(
                    "id-1",
                    start_at_local=datetime(2026, 3, 22, 11, 0),
                    intent_hash="ih-same",
                    received_at_utc=t0,
                )
            )
            b = engine.process_intent(
                _intent(
                    "id-2",
                    start_at_local=datetime(2026, 3, 22, 11, 0),
                    intent_hash="ih-same",
                    received_at_utc=t0 + timedelta(hours=1),
                )
            )

            conn = engine._store.conn  # type: ignore[attr-defined]
            count_after_hit = conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
            self.assertEqual(a, b)
            self.assertEqual(count_after_hit, 1)

            conn.execute(
                "UPDATE system_state SET value = '0', updated_at_utc = ? WHERE key = 'idempotency_window_hours'",
                (datetime.now(UTC).isoformat(),),
            )
            conn.commit()

            c = engine.process_intent(
                _intent(
                    "id-3",
                    start_at_local=datetime(2026, 3, 22, 11, 0),
                    intent_hash="ih-same",
                    received_at_utc=t0 + timedelta(hours=2),
                )
            )
            count_after_miss = conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]

            self.assertEqual(c["event_id"], a["event_id"])
            self.assertGreater(c["event_version"], a["event_version"])
            self.assertEqual(count_after_miss, 1)


if __name__ == "__main__":
    unittest.main()
