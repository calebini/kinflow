from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "daemon_run.py"


def _validated_runner_subprocess_context(root: Path) -> tuple[list[str], dict[str, str], str]:
    resolved_root = root.resolve()
    resolved_script = SCRIPT.resolve()

    python_exec = ""
    if sys.executable:
        candidate = str(Path(sys.executable).resolve())
        if Path(candidate).exists():
            python_exec = candidate
    if not python_exec:
        fallback = shutil.which("python3")
        if fallback:
            python_exec = fallback

    if not python_exec:
        raise AssertionError("no usable python executable found (sys.executable empty/unset and python3 not found)")
    if not resolved_root.exists() or not resolved_root.is_dir():
        raise AssertionError(f"invalid cwd for subprocess: {resolved_root}")
    if not resolved_script.exists():
        raise AssertionError(f"runner script missing: {resolved_script}")

    env = os.environ.copy()
    env["PYTHONPATH"] = str((resolved_root / "src").resolve())
    return [python_exec, str(resolved_script)], env, str(resolved_root)


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
        from scripts.daemon_run import DispatchCallbacks, build_oc_adapter_binding
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

            cb = DispatchCallbacks(store, lambda _e: None, oc_adapter=build_oc_adapter_binding())
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

    def test_pf03_terminal_evidence_guard_blocks_invalid_adapter_result(self) -> None:
        from scripts.daemon_run import DispatchCallbacks, build_oc_adapter_binding
        from src.ctx002_v0.models import DeliveryTarget, Event, Reminder
        from src.ctx002_v0.oc_adapter import OpenClawSendResponseNormalized
        from src.ctx002_v0.persistence.store import SqliteStateStore

        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "runtime.sqlite"
            store = SqliteStateStore.from_path(str(db))
            store.save_delivery_target(DeliveryTarget(person_id="p1", channel="whatsapp", target_id="15551234567", timezone="UTC"))
            store.save_new_event(
                Event(
                    event_id="evt-w1",
                    version=1,
                    title="wa",
                    start_at_local=datetime.now(UTC) + timedelta(hours=1),
                    timezone="UTC",
                    participants=("p1",),
                    audience=("p1",),
                    reminder_offset_minutes=5,
                    source_message_ref="msg-wa",
                )
            )
            store.save_reminder(
                Reminder(
                    reminder_id="rem-w1",
                    dedupe_key="k-wa-1",
                    event_id="evt-w1",
                    event_version=1,
                    recipient_id="p1",
                    trigger_at_utc=datetime.now(UTC) - timedelta(minutes=1),
                    offset_minutes=5,
                    status="scheduled",
                )
            )

            def bad_send(_msg):
                return OpenClawSendResponseNormalized(
                    normalized_outcome_class="success",
                    provider_status_code=None,
                    provider_receipt_ref="abc",
                    provider_error_class_hint=None,
                    provider_error_message_sanitized=None,
                    provider_confirmation_strength="confirmed",
                    raw_observed_at_utc=datetime.now(UTC),
                )

            cb = DispatchCallbacks(store, lambda _e: None, oc_adapter=build_oc_adapter_binding(bad_send))
            ok = cb.process_candidate(cb.list_candidates()[0])
            self.assertFalse(ok)
            reminder = store.list_reminders()[0]
            self.assertEqual(reminder.status, "failed")
            row = store.conn.execute(
                "SELECT provider_status_code, status, reason_code FROM delivery_attempts ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            self.assertIsNone(row["provider_status_code"])
            self.assertEqual(row["status"], "failed")

    def test_pf04_fail_token_consequence_on_bypass(self) -> None:
        from scripts.daemon_run import DispatchCallbacks, build_oc_adapter_binding
        from src.ctx002_v0.models import DeliveryTarget, Event, Reminder
        from src.ctx002_v0.persistence.store import SqliteStateStore

        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "runtime.sqlite"
            store = SqliteStateStore.from_path(str(db))
            store.save_delivery_target(DeliveryTarget(person_id="p1", channel="whatsapp", target_id="15551234567", timezone="UTC"))
            store.save_new_event(
                Event(
                    event_id="evt-w2",
                    version=1,
                    title="wa",
                    start_at_local=datetime.now(UTC) + timedelta(hours=1),
                    timezone="UTC",
                    participants=("p1",),
                    audience=("p1",),
                    reminder_offset_minutes=5,
                    source_message_ref="msg-wa2",
                )
            )
            store.save_reminder(
                Reminder(
                    reminder_id="rem-w2",
                    dedupe_key="k-wa-2",
                    event_id="evt-w2",
                    event_version=1,
                    recipient_id="p1",
                    trigger_at_utc=datetime.now(UTC) - timedelta(minutes=1),
                    offset_minutes=5,
                    status="scheduled",
                )
            )
            cb = DispatchCallbacks(store, lambda _e: None, oc_adapter=build_oc_adapter_binding(), force_bypass=True)
            ok = cb.process_candidate(cb.list_candidates()[0])
            self.assertFalse(ok)
            attempt_row = store.conn.execute(
                "SELECT status, reason_code FROM delivery_attempts ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            self.assertEqual(attempt_row["status"], "failed")
            self.assertEqual(attempt_row["reason_code"], "FAILED_PROVIDER_PERMANENT")

            audit_payload = store.conn.execute(
                "SELECT payload_json FROM audit_log ORDER BY audit_index DESC LIMIT 1"
            ).fetchone()["payload_json"]
            self.assertIn("attempt_id=att-rem-w2-1", audit_payload)
            self.assertIn("reminder_id=rem-w2", audit_payload)
            self.assertIn("path_id=whatsapp-daemon", audit_payload)
            self.assertIn("fail_token=DISPATCH_ADAPTER_BYPASS_DETECTED", audit_payload)
            self.assertIn("terminal_decision=BLOCK", audit_payload)

    def test_pf05_startup_binding_gate_invalid(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kinflow-runner-test-") as td:
            root = Path(td).resolve()
            cmd, env, cwd = _validated_runner_subprocess_context(ROOT)
            env.update(
                {
                    "KINFLOW_DB_PATH": str((root / "runtime.sqlite").resolve()),
                    "KINFLOW_HEALTH_PATH": str((root / "health.json").resolve()),
                    "KINFLOW_STATE_STAMP_PATH": str((root / "dispatch_mode.state").resolve()),
                    "KINFLOW_LOCK_PATH": str((root / "daemon.lock").resolve()),
                    "KINFLOW_OWNER_META_PATH": str((root / "owner.json").resolve()),
                    "KINFLOW_DAEMON_TICK_MS": "1000",
                    "KINFLOW_DISABLE_OC_ADAPTER_BINDING": "1",
                }
            )
            proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            out, _ = proc.communicate(timeout=3)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("DISPATCH_ADAPTER_BINDING_INVALID", out)
            lines = [json.loads(line) for line in out.splitlines() if line.strip().startswith("{")]
            step7 = [r for r in lines if r.get("event") == "startup_step" and r.get("step") == 7]
            self.assertTrue(step7)
            self.assertFalse(step7[0].get("whatsapp_adapter_bound"))
            startup_steps = [r["step"] for r in lines if r.get("event") == "startup_step"]
            self.assertNotIn(10, startup_steps)

    def test_terminal_json_line_and_startup_order(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kinflow-runner-test-") as td:
            root = Path(td).resolve()
            cmd, env, cwd = _validated_runner_subprocess_context(ROOT)
            env.update(
                {
                    "KINFLOW_DB_PATH": str((root / "runtime.sqlite").resolve()),
                    "KINFLOW_HEALTH_PATH": str((root / "health.json").resolve()),
                    "KINFLOW_STATE_STAMP_PATH": str((root / "dispatch_mode.state").resolve()),
                    "KINFLOW_LOCK_PATH": str((root / "daemon.lock").resolve()),
                    "KINFLOW_OWNER_META_PATH": str((root / "owner.json").resolve()),
                    "KINFLOW_DAEMON_TICK_MS": "1000",
                }
            )

            required_non_empty = [
                "KINFLOW_DB_PATH",
                "KINFLOW_HEALTH_PATH",
                "KINFLOW_STATE_STAMP_PATH",
                "KINFLOW_LOCK_PATH",
                "KINFLOW_OWNER_META_PATH",
            ]
            for key in required_non_empty:
                self.assertTrue(env.get(key), f"env path missing: {key}")
                self.assertNotEqual(env[key].strip(), "", f"env path empty: {key}")

            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
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
            step7 = [r for r in lines if r.get("event") == "startup_step" and r.get("step") == 7][0]
            self.assertTrue(step7.get("whatsapp_adapter_bound"))
            terminal = lines[-1]
            self.assertEqual(terminal.get("event"), "terminal")
            self.assertIn("final_status", terminal)
            self.assertIn("trace_id", terminal)
            self.assertIn("owner_id", terminal)


if __name__ == "__main__":
    unittest.main()
