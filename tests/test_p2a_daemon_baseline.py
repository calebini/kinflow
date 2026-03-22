from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from ctx002_v0.daemon import (
    DaemonContractNonConformant,
    DaemonRuntime,
    FairnessTracker,
    HealthSnapshot,
    ReconnectState,
    compute_health_freshness,
    compute_reconnect_delay_ms,
    next_tick_boundary_ms,
    reconcile_due,
    validate_daemon_config,
)


def _config(**overrides):
    base = {
        "runtime_mode": "normal",
        "daemon_tick_ms": 1000,
        "reconcile_tick_ms": 5000,
        "max_due_batch_size": 10,
        "max_reconcile_batch_size": 10,
        "max_reconcile_batches_per_tick": 2,
        "max_tick_deferral_for_oldest_due": 3,
        "max_health_age_ms": 5000,
        "health_fail_mode": "strict",
        "health_emit_interval_ms": 1000,
        "idempotency_window_hours": 24,
        "max_retry_attempts": 2,
        "shutdown_grace_ms": 1000,
        "db_reconnect_strategy": "fixed",
        "db_reconnect_backoff_ms": 100,
        "db_reconnect_max_attempts": 3,
        "db_reconnect_max_backoff_ms": 800,
        "max_consecutive_fatal_cycles": 2,
        "transaction_scope_mode": "per_row",
    }
    base.update(overrides)
    return validate_daemon_config(base)


class P2ADaemonBaselineTests(unittest.TestCase):
    def test_cadence_overrun_and_sleep_boundary(self) -> None:
        self.assertEqual(next_tick_boundary_ms(1001, 1000), 2000)
        self.assertEqual(next_tick_boundary_ms(2999, 1000), 3000)
        self.assertEqual(next_tick_boundary_ms(3000, 1000), 4000)

        due, boundary = reconcile_due(now_ms=17999, reconcile_tick_ms=5000, last_reconcile_boundary_ms=5000)
        self.assertTrue(due)
        self.assertEqual(boundary, 15000)

    def test_startup_readiness_transition_ordering(self) -> None:
        emitted = []
        runtime = DaemonRuntime(
            _config(),
            read_runtime_mode=lambda: "normal",
            list_candidates=lambda: [],
            process_candidate=lambda _: True,
            run_reconcile=lambda: True,
            emit_event=emitted.append,
        )
        snap = runtime.startup(datetime(2026, 3, 22, tzinfo=UTC))
        self.assertFalse(snap.state == "DOWN")
        self.assertTrue(snap.is_ready)
        self.assertEqual(emitted[0]["step"], "init_health_down")
        self.assertEqual(emitted[1]["step"], "ready_true")

    def test_capture_only_per_row_blocking(self) -> None:
        emitted = []
        runtime = DaemonRuntime(
            _config(),
            read_runtime_mode=lambda: "capture_only",
            list_candidates=lambda: [{"id": "r1"}, {"id": "r2"}],
            process_candidate=lambda _: True,
            run_reconcile=lambda: True,
            emit_event=emitted.append,
        )
        out = runtime.run_cycle(
            datetime(2026, 3, 22, 0, 0, 1, tzinfo=UTC),
            datetime(2026, 3, 22, 0, 0, 1, tzinfo=UTC),
        )
        blocked = [e for e in emitted if e.get("event") == "CAPTURE_ONLY_BLOCKED"]
        self.assertEqual(len(blocked), 2)
        self.assertEqual(out["rows_blocked"], 2)
        self.assertEqual(out["rows_processed"], 0)

    def test_fairness_deferral_accounting(self) -> None:
        tracker = FairnessTracker()
        tracker.record_loop(["a", "b"], ["a"], {})
        tracker.record_loop(["a", "b"], ["a"], {})
        self.assertEqual(tracker.deferral_tick_count("a"), 0)
        self.assertEqual(tracker.deferral_tick_count("b"), 2)

        tracker.record_loop(["b"], [], {"b": "CAPTURE_ONLY_BLOCKED"})
        self.assertEqual(tracker.deferral_tick_count("b"), 2)

    def test_reconnect_strategy_formula_and_exhaustion(self) -> None:
        self.assertEqual(compute_reconnect_delay_ms("fixed", 100, 3), 100)
        self.assertEqual(compute_reconnect_delay_ms("linear", 100, 3), 300)
        self.assertEqual(compute_reconnect_delay_ms("exponential_capped", 100, 4, 500), 500)

        state = ReconnectState()
        cfg = _config(db_reconnect_max_attempts=2)
        self.assertEqual(state.register_failure(cfg), 100)
        self.assertEqual(state.register_failure(cfg), 100)
        with self.assertRaises(DaemonContractNonConformant):
            state.register_failure(cfg)

    def test_health_snapshot_stale_transitions(self) -> None:
        snap = HealthSnapshot(
            state="UP",
            is_ready=True,
            snapshot_ts_utc=datetime(2026, 3, 22, 0, 0, 0, tzinfo=UTC),
            max_health_age_ms=1000,
            health_fail_mode="strict",
            last_successful_cycle_id="c1",
            last_failure_reason_code=None,
        )
        age, state = compute_health_freshness(snap, snap.snapshot_ts_utc + timedelta(milliseconds=1500))
        self.assertEqual(age, 1500)
        self.assertEqual(state, "DOWN")

        snap2 = HealthSnapshot(**{**snap.__dict__, "health_fail_mode": "non_strict"})
        _, state2 = compute_health_freshness(snap2, snap2.snapshot_ts_utc + timedelta(milliseconds=1500))
        self.assertEqual(state2, "DEGRADED")

    def test_correlation_semantics_root_rules(self) -> None:
        emitted = []
        runtime = DaemonRuntime(
            _config(),
            read_runtime_mode=lambda: "normal",
            list_candidates=lambda: [],
            process_candidate=lambda _: True,
            run_reconcile=lambda: True,
            emit_event=emitted.append,
        )
        runtime.startup(datetime(2026, 3, 22, tzinfo=UTC))
        out = runtime.run_cycle(datetime(2026, 3, 22, 0, 0, 1, tzinfo=UTC), datetime(2026, 3, 22, 0, 0, 1, tzinfo=UTC))
        self.assertEqual(out["causation_id"], f"ROOT:{out['cycle_id']}")
        startup = [e for e in emitted if e.get("stage") == "startup"]
        self.assertTrue(all(e["causation_id"].startswith("ROOT:STARTUP:") for e in startup))


if __name__ == "__main__":
    unittest.main()
