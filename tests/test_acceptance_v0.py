from __future__ import annotations

import unittest
from datetime import UTC, datetime

from ctx002_v0 import DeliveryTarget, FamilySchedulerV0, ReasonCode


def _intent(
    message_id: str,
    *,
    action: str = "create",
    title: str = "School pickup",
    start_at_local: datetime | None = None,
    participants: tuple[str, ...] = ("caleb", "wife"),
    audience: tuple[str, ...] = ("caleb",),
    reminder_offset_minutes: int | None = 30,
    confirmed: bool = True,
    event_timezone: str | None = "Europe/Paris",
    event_id: str | None = None,
) -> dict:
    return {
        "message_id": message_id,
        "correlation_id": f"corr-{message_id}",
        "action": action,
        "title": title,
        "start_at_local": start_at_local or datetime(2026, 3, 28, 18, 0),
        "participants": participants,
        "audience": audience,
        "reminder_offset_minutes": reminder_offset_minutes,
        "confirmed": confirmed,
        "event_timezone": event_timezone,
        "event_id": event_id,
        "received_at_utc": datetime(2026, 3, 18, 17, 30, tzinfo=UTC),
    }


def _engine() -> FamilySchedulerV0:
    engine = FamilySchedulerV0(household_timezone="Europe/Paris")
    engine.register_delivery_target(
        DeliveryTarget(
            person_id="caleb",
            channel="discord",
            target_id="user:caleb",
            timezone="Europe/Paris",
            quiet_hours_start=23,
            quiet_hours_end=7,
        )
    )
    engine.register_delivery_target(
        DeliveryTarget(
            person_id="wife",
            channel="discord",
            target_id="user:wife",
            timezone="America/New_York",
            quiet_hours_start=22,
            quiet_hours_end=7,
        )
    )
    return engine


class AcceptanceHarnessTests(unittest.TestCase):
    def test_confirmation_gate_blocks_persist_without_yes(self) -> None:
        engine = _engine()
        result = engine.process_intent(_intent("m1", confirmed=False))
        self.assertFalse(result["persisted"])
        self.assertEqual(result["reason_code"], ReasonCode.BLOCKED_CONFIRMATION_REQUIRED.value)
        self.assertEqual(engine.active_events, ())

    def test_missing_required_field_follow_up_only(self) -> None:
        engine = _engine()
        result = engine.process_intent(_intent("m2", reminder_offset_minutes=None))
        self.assertEqual(result["status"], "needs_follow_up")
        self.assertIn("reminder_preference", result["missing_fields"])

    def test_resolver_precedence_explicit_beats_similarity(self) -> None:
        engine = _engine()
        created = engine.process_intent(_intent("m3"))
        update = engine.process_intent(
            _intent(
                "m4",
                action="update",
                event_id=created["event_id"],
                title="School pickup changed",
                start_at_local=datetime(2026, 3, 28, 19, 0),
            )
        )
        self.assertEqual(update["reason_code"], ReasonCode.RESOLVER_EXPLICIT.value)
        self.assertEqual(update["event_version"], 2)

    def test_resolver_ambiguity_blocks_auto_resolution(self) -> None:
        engine = _engine()
        created = engine.process_intent(_intent("m5", audience=("caleb", "wife")))
        original = engine._event_versions[created["event_id"]][-1]  # test-only ambiguity fixture setup
        clone = type(original)(**{**original.__dict__, "event_id": "evt-9999"})
        engine._event_versions["evt-9999"] = [clone]

        ambiguous = engine.process_intent(
            _intent(
                "m7",
                action="update",
                event_timezone=None,
                title="School pickup",
                start_at_local=datetime(2026, 3, 28, 18, 0),
                audience=("caleb", "wife"),
                participants=("caleb", "wife"),
            )
        )
        self.assertEqual(ambiguous["status"], "ambiguous")
        self.assertEqual(ambiguous["reason_code"], ReasonCode.RESOLVER_AMBIGUOUS.value)

    def test_update_regenerates_and_invalidates_prior_version_reminders_without_drift(self) -> None:
        engine = _engine()
        created = engine.process_intent(_intent("m8", audience=("caleb", "wife")))
        old = [r for r in engine.reminders if r.event_id == created["event_id"] and r.event_version == 1]

        engine.process_intent(
            _intent(
                "m9",
                action="update",
                event_id=created["event_id"],
                start_at_local=datetime(2026, 3, 28, 20, 0),
                audience=("caleb", "wife"),
            )
        )
        invalidated = [r for r in old if r.status == "invalidated"]
        regen = [r for r in engine.reminders if r.event_id == created["event_id"] and r.event_version == 2]

        self.assertEqual(len(invalidated), len(old))
        self.assertEqual(len(regen), len(old))
        self.assertTrue(all(r.trigger_at_utc.isoformat().endswith("+00:00") for r in regen))

    def test_cancel_invalidates_all_future_pending_reminders(self) -> None:
        engine = _engine()
        created = engine.process_intent(_intent("m10", audience=("caleb", "wife")))
        engine.process_intent(_intent("m11", action="cancel", event_id=created["event_id"], event_timezone=None))
        post = [r for r in engine.reminders if r.event_id == created["event_id"]]
        self.assertTrue(any(r.status == "invalidated" for r in post))

    def test_timezone_missing_blocks_delivery_scheduling(self) -> None:
        engine = FamilySchedulerV0(household_timezone="Europe/Paris")
        engine.register_delivery_target(
            DeliveryTarget(
                person_id="caleb",
                channel="discord",
                target_id="user:caleb",
                timezone=None,
            )
        )
        engine.process_intent(_intent("m12"))
        blocked = [r for r in engine.reminders if r.status == "blocked"]
        self.assertTrue(blocked)
        self.assertTrue(any(a.reason_code == ReasonCode.TZ_MISSING for a in engine.audit))

    def test_retry_and_replay_no_duplicate_user_visible_delivery(self) -> None:
        engine = _engine()
        engine.process_intent(_intent("m13", start_at_local=datetime(2026, 3, 18, 18, 0)))
        calls = {"n": 0}

        def flaky(_: object) -> bool:
            calls["n"] += 1
            return calls["n"] >= 2

        now = datetime(2026, 3, 18, 16, 30, tzinfo=UTC)
        first = engine.attempt_due_deliveries(now, flaky)
        second = engine.attempt_due_deliveries(now.replace(minute=35), flaky)
        replay = engine.process_intent(_intent("m13", start_at_local=datetime(2026, 3, 18, 18, 0)))

        delivered = [o for o in first + second if o[1] == ReasonCode.DELIVERED]
        self.assertEqual(len(delivered), 1)
        self.assertEqual(replay["status"], "ok")

    def test_replay_consistency_dst_and_cross_timezone_fixture(self) -> None:
        intent_a = _intent("m14", start_at_local=datetime(2026, 3, 29, 9, 0), audience=("caleb", "wife"))
        intent_b = _intent(
            "m15",
            action="update",
            event_id="evt-0001",
            start_at_local=datetime(2026, 3, 29, 10, 0),
            audience=("caleb", "wife"),
        )

        left = _engine()
        right = _engine()

        for engine in (left, right):
            engine.process_intent(intent_a)
            engine.process_intent(intent_b)

        self.assertEqual(left.deterministic_hash(), right.deterministic_hash())


if __name__ == "__main__":
    unittest.main()
