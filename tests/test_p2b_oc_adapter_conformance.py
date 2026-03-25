from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta

from ctx002_v0.models import DeliveryTarget, Event, Reminder
from ctx002_v0.oc_adapter import (
    AdapterCapabilities,
    MappingRule,
    OpenClawGatewayAdapter,
    OpenClawSendResponseNormalized,
    OutboundMessage,
    delivery_result_to_attempt_kwargs,
)
from ctx002_v0.persistence.store import SqliteStateStore
from ctx002_v0.reason_codes import ReasonCode


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def advance(self, delta: timedelta) -> None:
        self.now += delta

    def __call__(self) -> datetime:
        return self.now


class P2BOCAdapterConformanceTests(unittest.TestCase):
    def _outbound(self, **overrides) -> OutboundMessage:
        base = {
            "delivery_id": "del-1",
            "attempt_id": "att-1",
            "attempt_index": 1,
            "trace_id": "trace-1",
            "causation_id": "ROOT:trace-1:1",
            "channel_hint": "whatsapp",
            "target_ref": "whatsapp:120363425701060269@g.us",
            "subject_type": "event_reminder",
            "priority": "normal",
            "body_text": "Dinner at 18:00",
            "dedupe_key": "evt-1:v1:caleb:30",
            "created_at_utc": datetime(2026, 3, 25, 19, 30, tzinfo=UTC),
            "payload_json": {"kind": "reminder"},
            "payload_schema_version": 1,
            "metadata_json": {"daemon_cycle_id": "cycle-1"},
            "metadata_schema_version": 1,
        }
        base.update(overrides)
        return OutboundMessage(**base)

    def test_mapping_precedence_policy_override_wins_provider_map(self) -> None:
        clock = _Clock(datetime(2026, 3, 25, 19, 30, tzinfo=UTC))

        def send_fn(_: OutboundMessage) -> OpenClawSendResponseNormalized:
            return OpenClawSendResponseNormalized(
                normalized_outcome_class="success",
                provider_status_code="OVERRIDE_PERM",
                provider_receipt_ref=None,
                provider_error_class_hint="permanent",
                provider_error_message_sanitized="rejected",
                provider_confirmation_strength="none",
                raw_observed_at_utc=clock(),
            )

        adapter = OpenClawGatewayAdapter(
            send_fn=send_fn,
            now_fn=clock,
            policy_override_map={
                "OVERRIDE_PERM": MappingRule(
                    status="FAILED_PERMANENT",
                    reason_code=ReasonCode.FAILED_PROVIDER_PERMANENT.value,
                    retry_eligible=False,
                    error_class="permanent",
                )
            },
        )

        out = adapter.send(self._outbound())
        self.assertEqual(out.status, "FAILED_PERMANENT")
        self.assertEqual(out.reason_code, ReasonCode.FAILED_PROVIDER_PERMANENT.value)

    def test_status_confidence_invariants_for_delivered(self) -> None:
        clock = _Clock(datetime(2026, 3, 25, 19, 31, tzinfo=UTC))
        calls: list[OutboundMessage] = []

        def send_fn(outbound: OutboundMessage) -> OpenClawSendResponseNormalized:
            calls.append(outbound)
            return OpenClawSendResponseNormalized(
                normalized_outcome_class="success",
                provider_status_code="ok",
                provider_receipt_ref="msg-123",
                provider_error_class_hint=None,
                provider_error_message_sanitized=None,
                provider_confirmation_strength="confirmed",
                raw_observed_at_utc=clock(),
            )

        adapter = OpenClawGatewayAdapter(send_fn=send_fn, now_fn=clock)
        out = adapter.send(self._outbound())
        self.assertEqual(out.status, "DELIVERED")
        self.assertEqual(out.reason_code, ReasonCode.DELIVERED_SUCCESS.value)
        self.assertEqual(out.delivery_confidence, "provider_confirmed")
        self.assertFalse(out.provider_accept_only)
        self.assertIsNone(out.error_object)
        self.assertEqual(calls[0].target_ref, "120363425701060269@g.us")

    def test_replay_attempt_id_and_dedupe_window(self) -> None:
        clock = _Clock(datetime(2026, 3, 25, 19, 32, tzinfo=UTC))
        send_calls = 0

        def send_fn(_: OutboundMessage) -> OpenClawSendResponseNormalized:
            nonlocal send_calls
            send_calls += 1
            return OpenClawSendResponseNormalized(
                normalized_outcome_class="success",
                provider_status_code="ok",
                provider_receipt_ref=f"msg-{send_calls}",
                provider_error_class_hint=None,
                provider_error_message_sanitized=None,
                provider_confirmation_strength="accepted",
                raw_observed_at_utc=clock(),
            )

        adapter = OpenClawGatewayAdapter(send_fn=send_fn, now_fn=clock, adapter_dedupe_window_ms=10_000)

        first = adapter.send(self._outbound(attempt_id="att-1", dedupe_key="d1"))
        replay_attempt = adapter.send(self._outbound(attempt_id="att-1", dedupe_key="d1"))
        replay_dedupe = adapter.send(self._outbound(attempt_id="att-2", dedupe_key="d1"))

        self.assertEqual(send_calls, 1)
        self.assertTrue(replay_attempt.replay_indicator)
        self.assertEqual(replay_attempt.replay_source, "attempt_id_hit")
        self.assertEqual(replay_attempt.result_at_utc, first.result_at_utc)
        self.assertTrue(replay_dedupe.replay_indicator)
        self.assertEqual(replay_dedupe.replay_source, "dedupe_key_window_hit")
        self.assertEqual(replay_dedupe.result_at_utc, first.result_at_utc)

        clock.advance(timedelta(seconds=11))
        fresh = adapter.send(self._outbound(attempt_id="att-3", dedupe_key="d1"))
        self.assertFalse(fresh.replay_indicator)
        self.assertEqual(send_calls, 2)

    def test_capture_only_and_capability_block_are_no_side_effect(self) -> None:
        clock = _Clock(datetime(2026, 3, 25, 19, 33, tzinfo=UTC))
        send_calls = 0

        def send_fn(_: OutboundMessage) -> OpenClawSendResponseNormalized:
            nonlocal send_calls
            send_calls += 1
            raise AssertionError("send_fn must not be called")

        adapter_capture = OpenClawGatewayAdapter(
            send_fn=send_fn,
            now_fn=clock,
            read_runtime_mode=lambda: "capture_only",
        )
        blocked_capture = adapter_capture.send(self._outbound())
        self.assertEqual(blocked_capture.status, "BLOCKED")
        self.assertEqual(blocked_capture.reason_code, ReasonCode.CAPTURE_ONLY_BLOCKED.value)

        adapter_cap = OpenClawGatewayAdapter(
            send_fn=send_fn,
            now_fn=clock,
            capabilities=AdapterCapabilities(
                supports_channel_hints=("discord",),
                supports_media=False,
                supports_priority=True,
                supports_delivery_receipts=True,
                supports_target_resolution=False,
            ),
        )
        blocked_cap = adapter_cap.send(self._outbound(channel_hint="whatsapp"))
        self.assertEqual(blocked_cap.status, "BLOCKED")
        self.assertEqual(blocked_cap.reason_code, ReasonCode.FAILED_CAPABILITY_UNSUPPORTED.value)
        self.assertEqual(send_calls, 0)

    def test_whatsapp_target_shape_alias_resolution_and_correlation_audit(self) -> None:
        clock = _Clock(datetime(2026, 3, 25, 19, 34, tzinfo=UTC))
        seen_targets: list[str] = []

        def send_fn(outbound: OutboundMessage) -> OpenClawSendResponseNormalized:
            seen_targets.append(outbound.target_ref)
            return OpenClawSendResponseNormalized(
                normalized_outcome_class="success",
                provider_status_code="ok",
                provider_receipt_ref="msg-ok",
                provider_error_class_hint=None,
                provider_error_message_sanitized=None,
                provider_confirmation_strength="accepted",
                raw_observed_at_utc=clock(),
            )

        adapter = OpenClawGatewayAdapter(
            send_fn=send_fn,
            now_fn=clock,
            capabilities=AdapterCapabilities(
                supports_channel_hints=("whatsapp",),
                supports_media=False,
                supports_priority=True,
                supports_delivery_receipts=True,
                supports_target_resolution=True,
            ),
            resolve_target_fn=lambda _: "120363425701060269@g.us",
        )
        out = adapter.send(self._outbound(target_ref="whatsapp:g-caleb-loop", attempt_id="att-alias"))
        self.assertEqual(out.status, "DELIVERED")
        self.assertEqual(seen_targets[-1], "120363425701060269@g.us")

        audit = adapter.audit_events[-1]
        self.assertEqual(audit["trace_id"], "trace-1")
        self.assertEqual(audit["causation_id"], "ROOT:trace-1:1")
        self.assertEqual(audit["daemon_cycle_id"], "cycle-1")

    def test_delivery_attempts_persistence_compatibility(self) -> None:
        clock = _Clock(datetime(2026, 3, 25, 19, 35, tzinfo=UTC))

        def send_fn(_: OutboundMessage) -> OpenClawSendResponseNormalized:
            return OpenClawSendResponseNormalized(
                normalized_outcome_class="success",
                provider_status_code="ok",
                provider_receipt_ref="msg-1",
                provider_error_class_hint=None,
                provider_error_message_sanitized=None,
                provider_confirmation_strength="accepted",
                raw_observed_at_utc=clock(),
            )

        with tempfile.TemporaryDirectory() as td:
            db_path = f"{td}/kinflow.sqlite"
            store = SqliteStateStore.from_path(db_path)
            event = Event(
                event_id="evt-0001",
                version=1,
                title="Family dinner",
                start_at_local=datetime(2026, 3, 26, 18, 0),
                timezone="UTC",
                participants=("caleb",),
                audience=("caleb",),
                reminder_offset_minutes=30,
                source_message_ref="msg-0",
            )
            store.save_new_event(event)
            store.save_delivery_target(
                DeliveryTarget(
                    person_id="caleb",
                    channel="whatsapp",
                    target_id="120363425701060269@g.us",
                    timezone="UTC",
                )
            )
            reminder = Reminder(
                reminder_id="rem-evt-0001-v1-caleb-30",
                dedupe_key="evt-0001:v1:caleb:30",
                event_id="evt-0001",
                event_version=1,
                recipient_id="caleb",
                trigger_at_utc=datetime(2026, 3, 26, 17, 30, tzinfo=UTC),
                offset_minutes=30,
                status="scheduled",
            )
            store.save_reminder(reminder)

            adapter = OpenClawGatewayAdapter(send_fn=send_fn, now_fn=clock)
            blocked = OpenClawGatewayAdapter(
                send_fn=send_fn,
                now_fn=clock,
                read_runtime_mode=lambda: "capture_only",
            ).send(self._outbound(attempt_id="att-block", dedupe_key="d-block"))
            delivered = adapter.send(self._outbound(attempt_id="att-deliver", dedupe_key="d-deliver"))

            store.append_delivery_attempt(
                **delivery_result_to_attempt_kwargs(
                    result=blocked,
                    reminder_id=reminder.reminder_id,
                    attempt_index=1,
                    attempted_at_utc=clock(),
                )
            )
            store.append_delivery_attempt(
                **delivery_result_to_attempt_kwargs(
                    result=delivered,
                    reminder_id=reminder.reminder_id,
                    attempt_index=2,
                    attempted_at_utc=clock(),
                )
            )

            rows = store.conn.execute(
                "SELECT status, reason_code, trace_id, causation_id FROM delivery_attempts ORDER BY attempt_index"
            ).fetchall()
            self.assertEqual([r["status"] for r in rows], ["blocked", "delivered"])
            self.assertEqual(rows[0]["reason_code"], ReasonCode.CAPTURE_ONLY_BLOCKED.value)
            self.assertEqual(rows[1]["reason_code"], ReasonCode.DELIVERED_SUCCESS.value)
            self.assertEqual(rows[1]["trace_id"], "trace-1")
            self.assertEqual(rows[1]["causation_id"], "ROOT:trace-1:1")


if __name__ == "__main__":
    unittest.main()
