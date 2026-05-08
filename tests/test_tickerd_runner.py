from __future__ import annotations

import contextlib
import fcntl
import json
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from scripts import tickerd_daemon_run
from src.ctx002_v0.models import DeliveryTarget, Event, Reminder
from src.ctx002_v0.persistence.store import SqliteStateStore


def _env(root: Path, *, max_fatal: int = 3) -> dict[str, str]:
    return {
        "KINFLOW_DB_PATH": str(root / "runtime.sqlite"),
        "KINFLOW_HEALTH_PATH": str(root / "health.json"),
        "KINFLOW_STATE_STAMP_PATH": str(root / "dispatch_mode.state"),
        "KINFLOW_LOCK_PATH": str(root / "daemon.lock"),
        "KINFLOW_OWNER_META_PATH": str(root / "owner.json"),
        "KINFLOW_DAEMON_TICK_MS": "10",
        "KINFLOW_LOCK_TIMEOUT_MS": "25",
        "KINFLOW_STALE_THRESHOLD_MS": "60000",
        "KINFLOW_MAX_CONSECUTIVE_FATAL": str(max_fatal),
        "KINFLOW_OC_SENDFN_MODE": "test_stub",
    }


def _seed_due_reminder(
    db_path: Path,
    *,
    channel: str = "discord",
    target_ref: str = "u1",
    reminder_id: str = "rem-runner-1",
) -> None:
    store = SqliteStateStore.from_path(str(db_path))
    store.save_delivery_target(DeliveryTarget(person_id="p1", channel=channel, target_id=target_ref, timezone="UTC"))
    store.save_new_event(
        Event(
            event_id="evt-runner-1",
            version=1,
            title="runner",
            start_at_local=datetime.now(UTC) + timedelta(hours=1),
            timezone="UTC",
            participants=("p1",),
            audience=("p1",),
            reminder_offset_minutes=5,
            source_message_ref="msg-runner-1",
        )
    )
    store.save_reminder(
        Reminder(
            reminder_id=reminder_id,
            dedupe_key=f"k-{reminder_id}",
            event_id="evt-runner-1",
            event_version=1,
            recipient_id="p1",
            trigger_at_utc=datetime.now(UTC) - timedelta(minutes=1),
            offset_minutes=5,
            status="scheduled",
        )
    )
    store.conn.close()


@contextlib.contextmanager
def _captured_events():
    events: list[dict[str, object]] = []
    with patch.object(tickerd_daemon_run, "_emit", lambda record: events.append(record)):
        yield events


class TickerdForegroundRunnerTests(unittest.TestCase):
    def test_runner_dispatches_due_work_and_writes_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            env = _env(root)
            _seed_due_reminder(Path(env["KINFLOW_DB_PATH"]))

            with patch.dict(os.environ, env, clear=False), _captured_events() as events:
                exit_code = tickerd_daemon_run.run(max_cycles=1, install_signal_handlers=False)

            self.assertEqual(exit_code, 0)
            terminal = [event for event in events if event.get("event") == "terminal"][-1]
            self.assertEqual(terminal["final_status"], "OK")
            self.assertEqual(terminal["cycles_completed"], 1)

            health = json.loads(Path(env["KINFLOW_HEALTH_PATH"]).read_text())
            self.assertFalse(health["is_ready"])
            self.assertEqual(health["state"], "stopping")
            self.assertTrue(health["last_successful_cycle_id"])

            owner = json.loads(Path(env["KINFLOW_OWNER_META_PATH"]).read_text())
            self.assertTrue(owner["owner_id"])
            self.assertIn("dispatch_mode=daemon", Path(env["KINFLOW_STATE_STAMP_PATH"]).read_text())

            store = SqliteStateStore.from_path(env["KINFLOW_DB_PATH"])
            try:
                self.assertEqual(store.list_reminders()[0].status, "delivered")
                attempt = store.conn.execute(
                    "SELECT status, trace_id, causation_id FROM delivery_attempts ORDER BY rowid DESC LIMIT 1"
                ).fetchone()
                self.assertEqual(attempt["status"], "delivered")
                self.assertNotEqual(attempt["trace_id"], "daemon_runner")
                self.assertTrue(attempt["causation_id"].startswith("ROOT:"))
            finally:
                store.conn.close()

    def test_runner_reports_adapter_binding_failure_as_kinflow_fail_token(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            env = {**_env(root), "KINFLOW_DISABLE_OC_ADAPTER_BINDING": "1"}

            with patch.dict(os.environ, env, clear=False), _captured_events() as events:
                exit_code = tickerd_daemon_run.run(max_cycles=1, install_signal_handlers=False)

            self.assertEqual(exit_code, 1)
            fail = [event for event in events if event.get("event") == "runner_fail_stop"][-1]
            self.assertEqual(fail["fail_token"], "DISPATCH_ADAPTER_BINDING_INVALID")
            health = json.loads(Path(env["KINFLOW_HEALTH_PATH"]).read_text())
            self.assertEqual(health["state"], "failed")
            self.assertEqual(health["last_failure_reason_code"], "DISPATCH_ADAPTER_BINDING_INVALID")

    def test_runner_reports_singleton_lock_failure_as_kinflow_fail_token(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            env = _env(root)
            lock_path = Path(env["KINFLOW_LOCK_PATH"])
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            with lock_path.open("a+", encoding="utf-8") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                with patch.dict(os.environ, env, clear=False), _captured_events() as events:
                    exit_code = tickerd_daemon_run.run(max_cycles=1, install_signal_handlers=False)
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

            self.assertEqual(exit_code, 1)
            fail = [event for event in events if event.get("event") == "runner_fail_stop"][-1]
            self.assertEqual(fail["fail_token"], "LOCK_ACQUIRE_FAILED")
            health = json.loads(Path(env["KINFLOW_HEALTH_PATH"]).read_text())
            self.assertEqual(health["state"], "failed")
            self.assertEqual(health["last_failure_reason_code"], "LOCK_ACQUIRE_FAILED")

    def test_runner_exits_on_fatal_threshold_for_cycle_failures(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            env = {**_env(root, max_fatal=1), "KINFLOW_FORCE_WHATSAPP_BYPASS": "1"}
            _seed_due_reminder(Path(env["KINFLOW_DB_PATH"]), channel="whatsapp", target_ref="15551234567")

            with patch.dict(os.environ, env, clear=False), _captured_events() as events:
                exit_code = tickerd_daemon_run.run(max_cycles=5, install_signal_handlers=False)

            self.assertEqual(exit_code, 2)
            terminal = [event for event in events if event.get("event") == "terminal"][-1]
            self.assertEqual(terminal["final_status"], "FAILED")
            self.assertEqual(terminal["reason"], "fatal_threshold_exceeded")
            threshold = [event for event in events if event.get("event") == "fatal_threshold_exceeded"]
            self.assertTrue(threshold)

            health = json.loads(Path(env["KINFLOW_HEALTH_PATH"]).read_text())
            self.assertEqual(health["state"], "failed")
            self.assertEqual(health["last_failure_reason_code"], "fatal_threshold_exceeded")

            store = SqliteStateStore.from_path(env["KINFLOW_DB_PATH"])
            try:
                attempt = store.conn.execute(
                    "SELECT status, reason_code FROM delivery_attempts ORDER BY rowid DESC LIMIT 1"
                ).fetchone()
                self.assertEqual(attempt["status"], "failed")
                self.assertEqual(attempt["reason_code"], "FAILED_ADAPTER_RESULT_MISSING")
            finally:
                store.conn.close()


if __name__ == "__main__":
    unittest.main()
