from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "daemon_run.py"


class DaemonRunnerV013Tests(unittest.TestCase):
    def test_version_binding_validation_fails_mismatch(self) -> None:
        from scripts.daemon_run import RunnerExit, load_runner_config, validate_version_bindings

        env = {
            "KINFLOW_DB_PATH": ":memory:",
            "KINFLOW_EXPECT_RUNTIME_CONTRACT": "v9.9.9",
        }
        cfg = load_runner_config(env)
        with self.assertRaises(RunnerExit) as ctx:
            validate_version_bindings(cfg)
        self.assertEqual(ctx.exception.fail_token, "CONTRACT_VERSION_VALIDATION_FAILED")

    def test_health_shape_and_state_stamp_written(self) -> None:
        from scripts.daemon_run import load_runner_config, write_health, write_state_stamp

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            env = {
                "KINFLOW_DB_PATH": str(root / "runtime.sqlite"),
                "KINFLOW_HEALTH_PATH": str(root / "health.json"),
                "KINFLOW_STATE_STAMP_PATH": str(root / "dispatch_mode.state"),
            }
            cfg = load_runner_config(env)
            write_health(
                cfg,
                state="starting",
                is_ready=False,
                last_successful_cycle_id=None,
                last_failure_reason_code=None,
            )
            write_state_stamp(cfg)
            payload = json.loads((root / "health.json").read_text())
            self.assertEqual(
                set(payload.keys()),
                {
                    "state",
                    "is_ready",
                    "snapshot_ts_utc",
                    "last_successful_cycle_id",
                    "last_failure_reason_code",
                    "health_age_ms",
                },
            )
            self.assertFalse(payload["is_ready"])
            self.assertIn("dispatch_mode=daemon", (root / "dispatch_mode.state").read_text())

    def test_cycle_id_monotonic_and_overrun_no_burst(self) -> None:
        from scripts.daemon_run import load_runner_config
        from src.ctx002_v0.daemon import DaemonRuntime, validate_daemon_config

        with tempfile.TemporaryDirectory() as td:
            cfg = load_runner_config({"KINFLOW_DB_PATH": str(Path(td) / "db.sqlite"), "KINFLOW_DAEMON_TICK_MS": "1000"})
            daemon_cfg = validate_daemon_config(
                {
                    "runtime_mode": "normal",
                    "daemon_tick_ms": cfg.tick_ms,
                    "reconcile_tick_ms": 5000,
                    "max_due_batch_size": 100,
                    "max_reconcile_batch_size": 100,
                    "max_reconcile_batches_per_tick": 1,
                    "max_tick_deferral_for_oldest_due": 3,
                    "max_health_age_ms": 1000,
                    "health_fail_mode": "non_strict",
                    "health_emit_interval_ms": 1,
                    "idempotency_window_hours": 24,
                    "max_retry_attempts": 3,
                    "shutdown_grace_ms": 1000,
                    "db_reconnect_strategy": "fixed",
                    "db_reconnect_backoff_ms": 100,
                    "db_reconnect_max_attempts": 3,
                    "max_consecutive_fatal_cycles": 3,
                    "transaction_scope_mode": "per_row",
                }
            )
            rt = DaemonRuntime(
                daemon_cfg,
                read_runtime_mode=lambda: "normal",
                list_candidates=lambda: [],
                process_candidate=lambda _r: True,
                run_reconcile=lambda: True,
                emit_event=lambda _e: None,
            )
            s1 = rt.run_cycle(datetime.now(UTC), datetime.now(UTC))
            s2 = rt.run_cycle(datetime.now(UTC), datetime.now(UTC))
            self.assertTrue(s1["cycle_id"].endswith(":1"))
            self.assertTrue(s2["cycle_id"].endswith(":2"))

    def test_singleton_takeover_evidence_shape(self) -> None:
        from scripts.daemon_run import RunnerConfig, SingletonGuard, append_takeover_event

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            owner_path = root / "owner.json"
            owner_path.write_text(
                json.dumps(
                    {
                        "owner_id": "old-owner",
                        "heartbeat_ts_utc": (datetime.now(UTC) - timedelta(seconds=10)).isoformat(),
                    }
                )
            )
            cfg = RunnerConfig(
                tick_ms=1000,
                shutdown_grace_ms=1000,
                lock_timeout_ms=100,
                stale_threshold_ms=100,
                health_path=root / "health.json",
                state_stamp_path=root / "state.state",
                lock_path=root / "daemon.lock",
                owner_meta_path=owner_path,
                db_path=str(root / "db.sqlite"),
                expected_runtime_contract_version="v0.1.4",
                expected_deployment_contract_version="v0.1.4",
                max_consecutive_fatal_cycles=2,
                evidence_root=root / "evidence",
            )
            guard = SingletonGuard(cfg, "new-owner", 123, "host")
            evt = guard.acquire_and_verify()
            self.assertIsNotNone(evt)
            append_takeover_event(cfg, evt)
            line = (cfg.evidence_root / "singleton" / "takeover_events.jsonl").read_text().strip()
            row = json.loads(line)
            for field in [
                "event",
                "previous_owner_id",
                "new_owner_id",
                "previous_heartbeat_ts_utc",
                "takeover_ts_utc",
                "stale_threshold_ms",
                "db_path",
                "pid",
                "hostname",
            ]:
                self.assertIn(field, row)
            guard.release()

    def test_dispatch_noop_wiring_guard_detects_incomplete(self) -> None:
        from scripts.daemon_run import RunnerExit, ensure_dispatch_path_wired

        with self.assertRaises(RunnerExit) as ctx:
            ensure_dispatch_path_wired(None)
        self.assertEqual(ctx.exception.fail_token, "DISPATCH_PATH_WIRING_INCOMPLETE")

    def test_overdue_reminder_processed_and_persisted(self) -> None:
        from scripts.daemon_run import DispatchCallbacks
        from src.ctx002_v0.models import DeliveryTarget, Event, Reminder
        from src.ctx002_v0.persistence.store import SqliteStateStore

        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "runtime.sqlite"
            store = SqliteStateStore.from_path(str(db))
            store.save_delivery_target(
                DeliveryTarget(
                    person_id="p1",
                    channel="discord",
                    target_id="u1",
                    timezone="UTC",
                )
            )
            event = Event(
                event_id="evt-1",
                version=1,
                title="test",
                start_at_local=datetime.now(UTC) + timedelta(hours=1),
                timezone="UTC",
                participants=("p1",),
                audience=("p1",),
                reminder_offset_minutes=5,
                source_message_ref="msg-1",
            )
            store.save_new_event(event)

            reminder = Reminder(
                reminder_id="rem-1",
                dedupe_key="k1",
                event_id="evt-1",
                event_version=1,
                recipient_id="p1",
                trigger_at_utc=datetime.now(UTC) - timedelta(minutes=1),
                offset_minutes=5,
                status="scheduled",
            )
            store.save_reminder(reminder)

            cb = DispatchCallbacks(store, lambda _e: None)
            rows = cb.list_candidates()
            self.assertGreaterEqual(len(rows), 1)
            ok = cb.process_candidate(rows[0])
            self.assertTrue(ok)

            reminders = store.list_reminders()
            self.assertEqual(reminders[0].status, "delivered")
            attempts = store.conn.execute("SELECT COUNT(*) AS n FROM delivery_attempts").fetchone()["n"]
            audit = store.conn.execute("SELECT COUNT(*) AS n FROM audit_log WHERE stage='delivery'").fetchone()["n"]
            self.assertGreaterEqual(attempts, 1)
            self.assertGreaterEqual(audit, 1)

    def test_terminal_json_line_and_startup_order(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            env = os.environ.copy()
            env.update(
                {
                    "KINFLOW_DB_PATH": str(root / "runtime.sqlite"),
                    "KINFLOW_HEALTH_PATH": str(root / "health.json"),
                    "KINFLOW_STATE_STAMP_PATH": str(root / "dispatch_mode.state"),
                    "KINFLOW_LOCK_PATH": str(root / "daemon.lock"),
                    "KINFLOW_OWNER_META_PATH": str(root / "owner.json"),
                    "KINFLOW_DAEMON_TICK_MS": "1000",
                }
            )
            proc = subprocess.Popen(
                [sys.executable, str(SCRIPT)],
                cwd=str(ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            try:
                import time

                time.sleep(1.25)
                proc.terminate()
                out, _ = proc.communicate(timeout=3)
            finally:
                if proc.poll() is None:
                    proc.kill()

            lines = [json.loads(line) for line in out.splitlines() if line.strip().startswith("{")]
            startup_steps = [r["step"] for r in lines if r.get("event") == "startup_step"]
            self.assertEqual(startup_steps, list(range(1, 11)))
            terminal = lines[-1]
            self.assertEqual(terminal.get("event"), "terminal")
            self.assertIn("final_status", terminal)
            self.assertIn("trace_id", terminal)
            self.assertIn("owner_id", terminal)


if __name__ == "__main__":
    unittest.main()
