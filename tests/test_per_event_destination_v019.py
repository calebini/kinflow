from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.daemon_run import DispatchCallbacks, RunnerConfig, build_oc_adapter_binding
from src.ctx002_v0.engine import FamilySchedulerV0
from src.ctx002_v0.models import Event, Reminder
from src.ctx002_v0.oc_adapter import OpenClawSendResponseNormalized
from src.ctx002_v0.persistence.store import SqliteStateStore
from src.ctx002_v0.reason_codes import ReasonCode


def _runner_cfg(root: Path) -> RunnerConfig:
    return RunnerConfig(
        tick_ms=1000,
        shutdown_grace_ms=1000,
        lock_timeout_ms=100,
        stale_threshold_ms=100,
        health_path=root / "health.json",
        state_stamp_path=root / "state.state",
        lock_path=root / "daemon.lock",
        owner_meta_path=root / "owner.json",
        db_path=str(root / "db.sqlite"),
        expected_runtime_contract_version="v0.1.4",
        expected_deployment_contract_version="v0.1.4",
        max_consecutive_fatal_cycles=2,
        evidence_root=root / "evidence",
        accept_mode_verification_window_sec=120,
        accept_mode_open_gauge_alert_threshold=25,
        accept_mode_open_gauge_alert_cycles=5,
    )


class PerEventDestinationV019Tests(unittest.TestCase):
    def _seed_event_and_reminder(
        self,
        store: SqliteStateStore,
        *,
        event_override_channel: str | None,
        event_override_target_ref: str | None,
        request_context_default_channel: str | None,
        request_context_default_target_ref: str | None,
    ) -> None:
        now = datetime.now(UTC)
        store.save_new_event(
            Event(
                event_id="evt-dst-1",
                version=1,
                title="dest-check",
                start_at_local=now + timedelta(hours=1),
                timezone="UTC",
                participants=("p1",),
                audience=("p1",),
                reminder_offset_minutes=5,
                source_message_ref="msg-dst-1",
                event_override_channel=event_override_channel,
                event_override_target_ref=event_override_target_ref,
                request_context_default_channel=request_context_default_channel,
                request_context_default_target_ref=request_context_default_target_ref,
            )
        )
        store.save_reminder(
            Reminder(
                reminder_id="rem-dst-1",
                dedupe_key="k-dst-1",
                event_id="evt-dst-1",
                event_version=1,
                recipient_id="p1",
                trigger_at_utc=now - timedelta(minutes=1),
                offset_minutes=5,
                status="scheduled",
                event_override_channel=event_override_channel,
                event_override_target_ref=event_override_target_ref,
                request_context_default_channel=request_context_default_channel,
                request_context_default_target_ref=request_context_default_target_ref,
            )
        )

    def test_precedence_event_override_wins(self) -> None:
        from src.ctx002_v0.models import DeliveryTarget

        captured: dict[str, str] = {}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = SqliteStateStore.from_path(str(root / "runtime.sqlite"))
            store.save_delivery_target(
                DeliveryTarget(person_id="p1", channel="discord", target_id="user:p1", timezone="UTC")
            )
            self._seed_event_and_reminder(
                store,
                event_override_channel="whatsapp",
                event_override_target_ref="15551234567",
                request_context_default_channel="telegram",
                request_context_default_target_ref="tg-user",
            )

            def send_capture(msg):
                captured["channel_hint"] = msg.channel_hint
                captured["target_ref"] = msg.target_ref
                return OpenClawSendResponseNormalized(
                    normalized_outcome_class="success",
                    provider_status_code="ok",
                    provider_receipt_ref="wamid.dst.1",
                    provider_error_class_hint=None,
                    provider_error_message_sanitized=None,
                    provider_confirmation_strength="confirmed",
                    raw_observed_at_utc=datetime.now(UTC),
                )

            cb = DispatchCallbacks(
                store,
                lambda _e: None,
                oc_adapter=build_oc_adapter_binding(send_capture),
                cfg=_runner_cfg(root),
            )
            ok = cb.process_candidate(cb.list_candidates()[0])
            self.assertTrue(ok)
            self.assertEqual(captured["channel_hint"], "whatsapp")
            self.assertEqual(captured["target_ref"], "15551234567")

            row = store.conn.execute(
                "SELECT destination_source, destination_resolution_status, resolved_channel, resolved_target_ref "
                "FROM delivery_attempts ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            self.assertEqual(row["destination_source"], "event_override")
            self.assertEqual(row["destination_resolution_status"], "ok")
            self.assertEqual(row["resolved_channel"], "whatsapp")
            self.assertEqual(row["resolved_target_ref"], "15551234567")

    def test_precedence_request_context_default_used_when_override_absent(self) -> None:
        from src.ctx002_v0.models import DeliveryTarget

        captured: dict[str, str] = {}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = SqliteStateStore.from_path(str(root / "runtime.sqlite"))
            store.save_delivery_target(
                DeliveryTarget(person_id="p1", channel="discord", target_id="user:p1", timezone="UTC")
            )
            self._seed_event_and_reminder(
                store,
                event_override_channel=None,
                event_override_target_ref=None,
                request_context_default_channel="whatsapp",
                request_context_default_target_ref="15550001111",
            )

            def send_capture(msg):
                captured["channel_hint"] = msg.channel_hint
                captured["target_ref"] = msg.target_ref
                return OpenClawSendResponseNormalized(
                    normalized_outcome_class="success",
                    provider_status_code="ok",
                    provider_receipt_ref="wamid.dst.2",
                    provider_error_class_hint=None,
                    provider_error_message_sanitized=None,
                    provider_confirmation_strength="confirmed",
                    raw_observed_at_utc=datetime.now(UTC),
                )

            cb = DispatchCallbacks(
                store,
                lambda _e: None,
                oc_adapter=build_oc_adapter_binding(send_capture),
                cfg=_runner_cfg(root),
            )
            ok = cb.process_candidate(cb.list_candidates()[0])
            self.assertTrue(ok)
            self.assertEqual(captured["channel_hint"], "whatsapp")
            self.assertEqual(captured["target_ref"], "15550001111")

            row = store.conn.execute(
                "SELECT destination_source, destination_resolution_status, resolved_channel, resolved_target_ref "
                "FROM delivery_attempts ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            self.assertEqual(row["destination_source"], "request_context_default")
            self.assertEqual(row["destination_resolution_status"], "ok")
            self.assertEqual(row["resolved_channel"], "whatsapp")
            self.assertEqual(row["resolved_target_ref"], "15550001111")

    def test_missing_destination_fails_closed_with_none_missing(self) -> None:
        from src.ctx002_v0.models import DeliveryTarget

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = SqliteStateStore.from_path(str(root / "runtime.sqlite"))
            store.save_delivery_target(DeliveryTarget(person_id="p1", channel="", target_id="", timezone="UTC"))
            self._seed_event_and_reminder(
                store,
                event_override_channel=None,
                event_override_target_ref=None,
                request_context_default_channel=None,
                request_context_default_target_ref=None,
            )

            cb = DispatchCallbacks(
                store,
                lambda _e: None,
                oc_adapter=build_oc_adapter_binding(),
                cfg=_runner_cfg(root),
            )
            ok = cb.process_candidate(cb.list_candidates()[0])
            self.assertFalse(ok)

            row = store.conn.execute(
                "SELECT status, reason_code, destination_source, destination_resolution_status, "
                "resolved_channel, resolved_target_ref FROM delivery_attempts ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            self.assertEqual(row["status"], "failed")
            self.assertEqual(row["reason_code"], ReasonCode.FAILED_CONFIG_INVALID_TARGET.value)
            self.assertEqual(row["destination_source"], "none")
            self.assertEqual(row["destination_resolution_status"], "missing")
            self.assertIsNone(row["resolved_channel"])
            self.assertIsNone(row["resolved_target_ref"])

            delivered = store.conn.execute(
                "SELECT COUNT(*) AS n FROM delivery_attempts WHERE status='delivered'"
            ).fetchone()["n"]
            self.assertEqual(delivered, 0)

    def test_invalid_override_blocks_without_fallback(self) -> None:
        from src.ctx002_v0.models import DeliveryTarget

        calls = {"n": 0}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = SqliteStateStore.from_path(str(root / "runtime.sqlite"))
            store.save_delivery_target(
                DeliveryTarget(person_id="p1", channel="whatsapp", target_id="15550002222", timezone="UTC")
            )
            self._seed_event_and_reminder(
                store,
                event_override_channel="whatsapp",
                event_override_target_ref=None,
                request_context_default_channel=None,
                request_context_default_target_ref=None,
            )

            def send_capture(_msg):
                calls["n"] += 1
                return OpenClawSendResponseNormalized(
                    normalized_outcome_class="success",
                    provider_status_code="ok",
                    provider_receipt_ref="should-not-send",
                    provider_error_class_hint=None,
                    provider_error_message_sanitized=None,
                    provider_confirmation_strength="confirmed",
                    raw_observed_at_utc=datetime.now(UTC),
                )

            cb = DispatchCallbacks(
                store,
                lambda _e: None,
                oc_adapter=build_oc_adapter_binding(send_capture),
                cfg=_runner_cfg(root),
            )
            ok = cb.process_candidate(cb.list_candidates()[0])
            self.assertFalse(ok)
            self.assertEqual(calls["n"], 0)

            row = store.conn.execute(
                "SELECT reason_code, destination_source, destination_resolution_status "
                "FROM delivery_attempts ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            self.assertEqual(row["reason_code"], ReasonCode.FAILED_CONFIG_INVALID_TARGET.value)
            self.assertEqual(row["destination_source"], "event_override")
            self.assertEqual(row["destination_resolution_status"], "invalid")

    def test_unknown_failure_exhaustion_maps_to_failed_retry_exhausted(self) -> None:
        from src.ctx002_v0.models import DeliveryTarget

        engine = FamilySchedulerV0(
            household_timezone="UTC",
            retry_delay_minutes=0,
            max_retries=1,
        )
        engine.register_delivery_target(
            DeliveryTarget(
                person_id="p1",
                channel="discord",
                target_id="user:p1",
                timezone="UTC",
            )
        )

        created = engine.process_intent(
            {
                "message_id": "m-dst-exhaust",
                "correlation_id": "corr-m-dst-exhaust",
                "action": "create",
                "title": "retry exhaust",
                "start_at_local": datetime(2026, 4, 24, 7, 0),
                "participants": ("p1",),
                "audience": ("p1",),
                "reminder_offset_minutes": 0,
                "confirmed": True,
                "event_timezone": "UTC",
                "received_at_utc": datetime(2026, 4, 24, 6, 59, tzinfo=UTC),
            }
        )
        self.assertEqual(created["status"], "ok")

        def unknown_provider(_reminder):
            return {
                "ok": False,
                "provider_status_code": "provider.unknown",
                "provider_error_text": "unknown class",
                "provider_accept_only": False,
                "delivery_confidence": "none",
            }

        now = datetime(2026, 4, 24, 7, 0, tzinfo=UTC)
        outcomes = []
        for _ in range(4):
            outcomes.extend(engine.attempt_due_deliveries(now, unknown_provider))

        reason_codes = [reason for _, reason in outcomes]
        self.assertIn(ReasonCode.FAILED_RETRY_EXHAUSTED, reason_codes)


if __name__ == "__main__":
    unittest.main()
