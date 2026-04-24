from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime

from ctx002_v0 import DeliveryTarget, FamilySchedulerV0
from ctx002_v0.persistence.store import TargetRefValidationError


def _intent(
    message_id: str,
    *,
    action: str = "create",
    event_id: str | None = None,
    title: str = "School pickup",
    start_at_local: datetime | None = None,
    reminder_offset_minutes: int | None = 30,
    confirmed: bool = True,
) -> dict:
    return {
        "message_id": message_id,
        "correlation_id": f"corr-{message_id}",
        "action": action,
        "event_id": event_id,
        "title": title,
        "start_at_local": start_at_local or datetime(2026, 3, 28, 18, 0),
        "participants": ("caleb", "wife"),
        "audience": ("caleb",),
        "reminder_offset_minutes": reminder_offset_minutes,
        "confirmed": confirmed,
        "event_timezone": "Europe/Paris",
        "received_at_utc": datetime(2026, 3, 21, 21, 0, tzinfo=UTC),
    }


class P1BRepoIntegrationTests(unittest.TestCase):
    def test_sqlite_parity_create_update_cancel(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".sqlite") as tf:
            mem = FamilySchedulerV0(household_timezone="Europe/Paris")
            db = FamilySchedulerV0(household_timezone="Europe/Paris", db_path=tf.name)

            for engine in (mem, db):
                engine.register_delivery_target(
                    DeliveryTarget(
                        person_id="caleb",
                        channel="discord",
                        target_id="user:caleb",
                        timezone="Europe/Paris",
                    )
                )

            c_mem = mem.process_intent(_intent("m1"))
            c_db = db.process_intent(_intent("m1"))
            self.assertEqual(c_mem["reason_code"], c_db["reason_code"])
            self.assertEqual(c_mem["status"], c_db["status"])

            u_mem = mem.process_intent(_intent("m2", action="update", event_id=c_mem["event_id"], title="Updated"))
            u_db = db.process_intent(_intent("m2", action="update", event_id=c_db["event_id"], title="Updated"))
            self.assertEqual(u_mem["reason_code"], u_db["reason_code"])
            self.assertEqual(u_mem["event_version"], u_db["event_version"])

            x_mem = mem.process_intent(_intent("m3", action="cancel", event_id=c_mem["event_id"]))
            x_db = db.process_intent(_intent("m3", action="cancel", event_id=c_db["event_id"]))
            self.assertEqual(x_mem["reason_code"], x_db["reason_code"])
            self.assertEqual(x_mem["event_version"], x_db["event_version"])

    def test_transaction_boundary_sanity_for_create_update_cancel(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".sqlite") as tf:
            db = FamilySchedulerV0(household_timezone="Europe/Paris", db_path=tf.name)
            db.register_delivery_target(
                DeliveryTarget(
                    person_id="caleb",
                    channel="discord",
                    target_id="user:caleb",
                    timezone="Europe/Paris",
                )
            )
            create = db.process_intent(_intent("tx1"))
            update = db.process_intent(_intent("tx2", action="update", event_id=create["event_id"], title="Tx updated"))
            cancel = db.process_intent(_intent("tx3", action="cancel", event_id=create["event_id"]))

            conn = db._store.conn  # type: ignore[attr-defined]
            event_row = conn.execute(
                "SELECT current_version, status FROM events WHERE event_id = ?", (create["event_id"],)
            ).fetchone()
            version_rows = conn.execute(
                "SELECT COUNT(*) AS n FROM event_versions WHERE event_id = ?",
                (create["event_id"],),
            ).fetchone()

            self.assertEqual(update["event_version"], 2)
            self.assertEqual(cancel["event_version"], 3)
            self.assertEqual(event_row["current_version"], 3)
            self.assertEqual(event_row["status"], "cancelled")
            self.assertEqual(version_rows["n"], 3)

    def test_receipt_replay_persists_across_engine_restart(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".sqlite") as tf:
            first = FamilySchedulerV0(household_timezone="Europe/Paris", db_path=tf.name)
            first.register_delivery_target(
                DeliveryTarget(
                    person_id="caleb",
                    channel="discord",
                    target_id="user:caleb",
                    timezone="Europe/Paris",
                )
            )
            initial = first.process_intent(_intent("receipt-1"))

            second = FamilySchedulerV0(household_timezone="Europe/Paris", db_path=tf.name)
            second.register_delivery_target(
                DeliveryTarget(
                    person_id="caleb",
                    channel="discord",
                    target_id="user:caleb",
                    timezone="Europe/Paris",
                )
            )
            replay = second.process_intent(_intent("receipt-1"))

            self.assertEqual(initial, replay)
            conn = second._store.conn  # type: ignore[attr-defined]
            events = conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
            self.assertEqual(events, 1)

    def test_target_ref_width_guard_enforced_for_memory_and_sqlite_store(self) -> None:
        within_limit = "x" * 256
        overflow = "x" * 257

        mem = FamilySchedulerV0(household_timezone="Europe/Paris")
        mem.register_delivery_target(
            DeliveryTarget(
                person_id="mem-ok",
                channel="discord",
                target_id=within_limit,
                timezone="Europe/Paris",
            )
        )
        with self.assertRaises(TargetRefValidationError):
            mem.register_delivery_target(
                DeliveryTarget(
                    person_id="mem-bad",
                    channel="discord",
                    target_id=overflow,
                    timezone="Europe/Paris",
                )
            )

        with tempfile.NamedTemporaryFile(suffix=".sqlite") as tf:
            db = FamilySchedulerV0(household_timezone="Europe/Paris", db_path=tf.name)
            db.register_delivery_target(
                DeliveryTarget(
                    person_id="db-ok",
                    channel="discord",
                    target_id=within_limit,
                    timezone="Europe/Paris",
                )
            )
            with self.assertRaises(TargetRefValidationError):
                db.register_delivery_target(
                    DeliveryTarget(
                        person_id="db-bad",
                        channel="discord",
                        target_id=overflow,
                        timezone="Europe/Paris",
                    )
                )


if __name__ == "__main__":
    unittest.main()
