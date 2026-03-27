from __future__ import annotations

import json
from datetime import UTC, datetime

from ctx002_v0 import DeliveryTarget, FamilySchedulerV0


def _serialize(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, default=str)


def _bootstrap() -> FamilySchedulerV0:
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
    return engine


def main() -> None:
    engine = _bootstrap()

    create_result = engine.process_intent(
        {
            "message_id": "operator-cancel-create",
            "correlation_id": "corr-operator-cancel-create",
            "action": "create",
            "title": "Piano lesson",
            "start_at_local": datetime(2026, 3, 23, 19, 0),
            "participants": ("caleb", "child"),
            "audience": ("caleb",),
            "reminder_offset_minutes": 30,
            "confirmed": True,
            "event_timezone": "Europe/Paris",
            "received_at_utc": datetime(2026, 3, 19, 18, 30, tzinfo=UTC),
        }
    )

    cancel_result = engine.process_intent(
        {
            "message_id": "operator-cancel",
            "correlation_id": "corr-operator-cancel",
            "action": "cancel",
            "event_id": create_result["event_id"],
            "confirmed": True,
            "received_at_utc": datetime(2026, 3, 19, 18, 40, tzinfo=UTC),
        }
    )

    delivery_outcomes = [
        (dedupe_key, reason.value)
        for dedupe_key, reason in engine.attempt_due_deliveries(
            datetime(2026, 3, 23, 17, 31, tzinfo=UTC),
            provider=lambda _: True,
        )
    ]

    print("PROCESS")
    print(
        _serialize(
            {
                "create": create_result,
                "cancel": cancel_result,
            }
        )
    )
    print()

    print("DELIVERY_OUTCOMES")
    print(_serialize(delivery_outcomes))
    print()

    print("HASH")
    print(engine.deterministic_hash())


if __name__ == "__main__":
    main()
