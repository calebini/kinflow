from __future__ import annotations

import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from kinflow.tickerd_runtime import (
    KinflowModeReader,
    KinflowReconciler,
    KinflowWorkItemProcessor,
    KinflowWorkItemSource,
    ensure_tickerd_importable,
)

ensure_tickerd_importable()

from tickerd.conformance import AdapterComponents, assert_basic_adapter_conformance  # noqa: E402
from tickerd.config import TickerdConfig  # noqa: E402
from tickerd.events import ListEventSink  # noqa: E402
from tickerd.kernel import RuntimeKernel  # noqa: E402
from tickerd.types import RuntimeMode  # noqa: E402

from scripts.daemon_run import DispatchCallbacks, build_oc_adapter_binding  # noqa: E402
from kinflow.models import DeliveryTarget, Event, Reminder  # noqa: E402
from kinflow.oc_adapter import OpenClawSendResponseNormalized  # noqa: E402
from kinflow.persistence.store import SqliteStateStore  # noqa: E402
from tests.test_daemon_runner_v013 import _test_runner_cfg  # noqa: E402

TICK_TS = datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC)


def _seed_due_reminder(store: SqliteStateStore, *, channel: str = "discord", target_ref: str = "u1") -> None:
    store.save_delivery_target(DeliveryTarget(person_id="p1", channel=channel, target_id=target_ref, timezone="UTC"))
    store.save_new_event(
        Event(
            event_id="evt-tickerd-1",
            version=1,
            title="tickerd",
            start_at_local=datetime.now(UTC) + timedelta(hours=1),
            timezone="UTC",
            participants=("p1",),
            audience=("p1",),
            reminder_offset_minutes=5,
            source_message_ref="msg-tickerd-1",
        )
    )
    store.save_reminder(
        Reminder(
            reminder_id="rem-tickerd-1",
            dedupe_key="k-tickerd-1",
            event_id="evt-tickerd-1",
            event_version=1,
            recipient_id="p1",
            trigger_at_utc=datetime.now(UTC) - timedelta(minutes=1),
            offset_minutes=5,
            status="scheduled",
        )
    )


def _callbacks(store: SqliteStateStore, root: Path, send_fn=None, events=None) -> DispatchCallbacks:
    return DispatchCallbacks(
        store,
        (events or []).append,
        oc_adapter=build_oc_adapter_binding(send_fn),
        cfg=_test_runner_cfg(root),
    )


def _kernel(store: SqliteStateStore, callbacks: DispatchCallbacks, events: ListEventSink) -> RuntimeKernel:
    cfg = TickerdConfig(tick_interval_ms=1000, reconcile_interval_ms=2000, max_work_items_per_tick=10)
    processor = KinflowWorkItemProcessor(callbacks.process_candidate, emit_event=events.emit)
    kernel = RuntimeKernel(
        cfg,
        mode_reader=KinflowModeReader(store.get_runtime_mode),
        work_source=KinflowWorkItemSource(callbacks.list_candidates),
        processor=processor,
        reconciler=KinflowReconciler(callbacks.run_reconcile),
        event_sink=events,
        trace_id="kinflow-test-trace",
    )
    kernel._test_processor = processor  # type: ignore[attr-defined]
    return kernel


class TickerdAdapterTests(unittest.TestCase):
    def test_basic_adapter_conformance_passes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = SqliteStateStore.from_path(str(Path(td) / "runtime.sqlite"))
            _seed_due_reminder(store)
            cb = _callbacks(store, Path(td))
            assert_basic_adapter_conformance(
                AdapterComponents(
                    mode_reader=KinflowModeReader(store.get_runtime_mode),
                    work_source=KinflowWorkItemSource(cb.list_candidates),
                    processor=KinflowWorkItemProcessor(cb.process_candidate),
                    reconciler=KinflowReconciler(cb.run_reconcile),
                ),
                TickerdConfig(tick_interval_ms=1000, reconcile_interval_ms=2000),
            )

    def test_mode_mapping_uses_tickerd_runtime_modes(self) -> None:
        self.assertEqual(KinflowModeReader(lambda: "normal").read_mode(), RuntimeMode.ACTIVE)
        self.assertEqual(KinflowModeReader(lambda: "capture_only").read_mode(), RuntimeMode.OBSERVE_ONLY)
        self.assertEqual(KinflowModeReader(lambda: "suspended").read_mode(), RuntimeMode.SUSPENDED)
        self.assertEqual(KinflowModeReader(lambda: "unknown").read_mode(), RuntimeMode.SUSPENDED)

    def test_active_mode_preserves_dispatch_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = SqliteStateStore.from_path(str(Path(td) / "runtime.sqlite"))
            _seed_due_reminder(store)
            cb = _callbacks(store, Path(td))
            events = ListEventSink()
            kernel = _kernel(store, cb, events)

            summary = kernel.run_cycle(TICK_TS, TICK_TS)

            self.assertEqual(summary["runtime_mode"], "active")
            self.assertEqual(summary["items_processed"], 1)
            self.assertEqual(store.list_reminders()[0].status, "delivered")
            attempts = store.conn.execute("SELECT COUNT(*) AS n FROM delivery_attempts").fetchone()["n"]
            self.assertEqual(attempts, 1)

    def test_observe_only_surfaces_work_without_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = SqliteStateStore.from_path(str(Path(td) / "runtime.sqlite"))
            store.set_runtime_mode("capture_only")
            _seed_due_reminder(store)
            cb = _callbacks(store, Path(td))
            events = ListEventSink()
            kernel = _kernel(store, cb, events)

            summary = kernel.run_cycle(TICK_TS, TICK_TS)

            self.assertEqual(summary["runtime_mode"], "observe_only")
            self.assertEqual(summary["items_scanned"], 1)
            self.assertEqual(summary["items_blocked"], 1)
            self.assertEqual(store.list_reminders()[0].status, "scheduled")
            attempts = store.conn.execute("SELECT COUNT(*) AS n FROM delivery_attempts").fetchone()["n"]
            self.assertEqual(attempts, 0)
            self.assertEqual(kernel._test_processor.observed_item_ids, ["rem-tickerd-1"])  # type: ignore[attr-defined]

    def test_suspended_mode_blocks_before_processor_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = SqliteStateStore.from_path(str(Path(td) / "runtime.sqlite"))
            store.set_runtime_mode("suspended")
            _seed_due_reminder(store)
            cb = _callbacks(store, Path(td))
            events = ListEventSink()
            kernel = _kernel(store, cb, events)

            summary = kernel.run_cycle(TICK_TS, TICK_TS)

            self.assertEqual(summary["runtime_mode"], "suspended")
            self.assertEqual(summary["items_scanned"], 1)
            self.assertEqual(summary["items_blocked"], 1)
            self.assertEqual(store.list_reminders()[0].status, "scheduled")
            self.assertEqual(kernel._test_processor.observed_item_ids, [])  # type: ignore[attr-defined]

    def test_cycle_identity_reaches_outbound_attempt_and_audit_metadata(self) -> None:
        captured = {}

        def send_capture(msg):
            captured["trace_id"] = msg.trace_id
            captured["causation_id"] = msg.causation_id
            captured["metadata_json"] = msg.metadata_json
            return OpenClawSendResponseNormalized(
                normalized_outcome_class="success",
                provider_status_code="ok",
                provider_receipt_ref="wamid.tickerd.1",
                provider_error_class_hint=None,
                provider_error_message_sanitized=None,
                provider_confirmation_strength="confirmed",
                raw_observed_at_utc=datetime.now(UTC),
            )

        with tempfile.TemporaryDirectory() as td:
            store = SqliteStateStore.from_path(str(Path(td) / "runtime.sqlite"))
            _seed_due_reminder(store, channel="whatsapp", target_ref="15551234567")
            with patch.dict(os.environ, {"KINFLOW_OC_SENDFN_MODE": "test_stub"}, clear=False):
                cb = _callbacks(store, Path(td), send_fn=send_capture)
            events = ListEventSink()
            kernel = _kernel(store, cb, events)

            summary = kernel.run_cycle(TICK_TS, TICK_TS)

            self.assertEqual(captured["trace_id"], "kinflow-test-trace")
            self.assertEqual(captured["causation_id"], f"ROOT:{summary['cycle_id']}")
            self.assertEqual(captured["metadata_json"]["daemon_cycle_id"], summary["cycle_id"])
            row = store.conn.execute(
                "SELECT trace_id, causation_id FROM delivery_attempts ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            self.assertEqual(row["trace_id"], "kinflow-test-trace")
            self.assertEqual(row["causation_id"], f"ROOT:{summary['cycle_id']}")
            audit_payload = store.conn.execute(
                "SELECT payload_json FROM audit_log ORDER BY audit_index DESC LIMIT 1"
            ).fetchone()["payload_json"]
            self.assertIn(f"daemon_cycle_id={summary['cycle_id']}", audit_payload)


if __name__ == "__main__":
    unittest.main()
