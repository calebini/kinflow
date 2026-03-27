from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from ctx002_v0.daemon import DaemonRuntime, validate_daemon_config
from ctx002_v0.engine import FamilySchedulerV0
from ctx002_v0.models import DeliveryTarget
from ctx002_v0.oc_adapter import OpenClawGatewayAdapter, OpenClawSendResponseNormalized, OutboundMessage
from ctx002_v0.persistence.store import SqliteStateStore
from ctx002_v0.reason_codes import ReasonCode


@dataclass
class DrillResult:
    drill_id: str
    objective: str
    passed: bool
    observed: dict
    residual_risk: str | None


def _cfg() -> dict:
    return {
        "runtime_mode": "normal",
        "daemon_tick_ms": 1000,
        "reconcile_tick_ms": 5000,
        "max_due_batch_size": 20,
        "max_reconcile_batch_size": 20,
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
        "db_reconnect_max_backoff_ms": 1000,
        "max_consecutive_fatal_cycles": 2,
        "transaction_scope_mode": "per_row",
    }


def _setup_store(db_path: str) -> tuple[SqliteStateStore, FamilySchedulerV0]:
    store = SqliteStateStore.from_path(db_path)
    scheduler = FamilySchedulerV0(state_store=store, max_retries=2, retry_delay_minutes=5)
    scheduler.register_delivery_target(
        DeliveryTarget(
            person_id="caleb",
            channel="whatsapp",
            target_id="120363425701060269@g.us",
            timezone="UTC",
        )
    )
    return store, scheduler


def _create_due_reminder(store: SqliteStateStore, scheduler: FamilySchedulerV0, now: datetime, msg_id: str) -> str:
    out = scheduler.process_intent(
        {
            "message_id": msg_id,
            "correlation_id": f"corr:{msg_id}",
            "received_at_utc": now,
            "action": "create",
            "title": "Phase4 drill event",
            "start_at_local": now.replace(tzinfo=None),
            "participants": ["caleb"],
            "audience": ["caleb"],
            "reminder_offset_minutes": 0,
            "confirmed": True,
            "event_timezone": "UTC",
        }
    )
    if out.get("status") != "ok":
        raise RuntimeError(f"create failed: {out}")
    reminder = list(store.list_reminders())[0]
    return reminder.reminder_id


def _run_cycle(store: SqliteStateStore, adapter: OpenClawGatewayAdapter, now: datetime) -> dict:
    events = []
    runtime: DaemonRuntime

    def list_candidates() -> list[dict]:
        return [{"id": r.reminder_id} for r in store.list_due_reminders(now)]

    def process_candidate(row: dict) -> bool:
        reminder = next(r for r in store.list_reminders() if r.reminder_id == row["id"])
        target = store.get_delivery_target(reminder.recipient_id)
        if target is None:
            return False

        cycle_id = f"{runtime.trace_id}:{runtime.cycle_seq}"
        causation_id = f"ROOT:{cycle_id}"
        attempt_index = reminder.attempts + 1
        attempt_id = f"{reminder.reminder_id}:{uuid4().hex}"

        outbound = OutboundMessage(
            delivery_id=reminder.reminder_id,
            attempt_id=attempt_id,
            attempt_index=attempt_index,
            trace_id=runtime.trace_id,
            causation_id=causation_id,
            channel_hint=target.channel,
            target_ref=target.target_id,
            subject_type="event_reminder",
            priority="normal",
            body_text="Phase4 drill reminder",
            dedupe_key=reminder.dedupe_key,
            created_at_utc=now,
            payload_json={"event_id": reminder.event_id},
            payload_schema_version=1,
            metadata_json={"daemon_cycle_id": cycle_id},
            metadata_schema_version=1,
        )
        result = adapter.send(outbound)

        status_map = {
            "DELIVERED": "delivered",
            "FAILED_TRANSIENT": "failed",
            "FAILED_PERMANENT": "failed",
            "SUPPRESSED": "suppressed",
            "BLOCKED": "blocked",
        }
        store.append_delivery_attempt(
            attempt_id=attempt_id,
            reminder_id=reminder.reminder_id,
            attempt_index=attempt_index,
            attempted_at_utc=now,
            status=status_map[result.status],
            reason_code=result.reason_code,
            provider_ref=result.provider_receipt_ref,
            provider_status_code=result.provider_status_code,
            provider_error_text=result.provider_error_text,
            provider_accept_only=result.provider_accept_only,
            delivery_confidence=result.delivery_confidence,
            result_at_utc=result.result_at_utc,
            trace_id=result.trace_id,
            causation_id=result.causation_id,
            source_adapter_attempt_id=result.attempt_id,
        )

        reminder.attempts = attempt_index
        if result.status == "DELIVERED":
            reminder.status = "delivered"
            reminder.next_attempt_at_utc = None
        elif result.status == "FAILED_TRANSIENT":
            reminder.status = "attempted"
            reminder.next_attempt_at_utc = now + timedelta(minutes=5)
        else:
            reminder.status = "failed"
            reminder.next_attempt_at_utc = None
        store.update_reminder(reminder)
        return True

    runtime = DaemonRuntime(
        validate_daemon_config(_cfg()),
        read_runtime_mode=lambda: store.get_runtime_mode(),
        list_candidates=list_candidates,
        process_candidate=process_candidate,
        run_reconcile=lambda: True,
        emit_event=events.append,
    )
    runtime.startup(now)
    summary = runtime.run_cycle(now, now)
    return {"summary": summary, "events": events, "audit_count": len(adapter.audit_events)}


def _drill_restart_continuity(now: datetime) -> DrillResult:
    with tempfile.TemporaryDirectory() as td:
        db_path = f"{td}/kinflow.sqlite"
        store, scheduler = _setup_store(db_path)
        _create_due_reminder(store, scheduler, now, "phase4-restart")

        send_calls = {"n": 0}

        def send_fn(_: OutboundMessage) -> OpenClawSendResponseNormalized:
            send_calls["n"] += 1
            return OpenClawSendResponseNormalized(
                normalized_outcome_class="success",
                provider_status_code="ok",
                provider_receipt_ref=f"msg-{send_calls['n']}",
                provider_error_class_hint=None,
                provider_error_message_sanitized=None,
                provider_confirmation_strength="confirmed",
                raw_observed_at_utc=now,
            )

        adapter = OpenClawGatewayAdapter(send_fn=send_fn, now_fn=lambda: now, adapter_dedupe_window_ms=0)
        first = _run_cycle(store, adapter, now)
        first_rows = store.conn.execute("SELECT COUNT(*) AS n FROM delivery_attempts").fetchone()["n"]

        # Simulated controlled restart: new runtime instance on same persistence.
        second = _run_cycle(store, adapter, now + timedelta(seconds=1))
        second_rows = store.conn.execute("SELECT COUNT(*) AS n FROM delivery_attempts").fetchone()["n"]

        passed = (
            first["summary"]["rows_processed"] == 1
            and second["summary"]["rows_processed"] == 0
            and first_rows == 1
            and second_rows == 1
            and send_calls["n"] == 1
        )
        return DrillResult(
            drill_id="D1_CONTROLLED_RESTART",
            objective="clean restart and persistence continuity without duplicate visible send",
            passed=passed,
            observed={
                "first_cycle": first,
                "second_cycle": second,
                "delivery_attempt_rows": {"after_first": first_rows, "after_second": second_rows},
                "visible_send_count": send_calls["n"],
            },
            residual_risk=None if passed else "restart continuity mismatch",
        )


def _drill_failure_injection(now: datetime) -> DrillResult:
    with tempfile.TemporaryDirectory() as td:
        db_path = f"{td}/kinflow.sqlite"
        store, scheduler = _setup_store(db_path)
        _create_due_reminder(store, scheduler, now, "phase4-failure")

        replies = [
            OpenClawSendResponseNormalized(
                normalized_outcome_class="transient",
                provider_status_code="timeout",
                provider_receipt_ref=None,
                provider_error_class_hint="transient",
                provider_error_message_sanitized="timeout",
                provider_confirmation_strength="none",
                raw_observed_at_utc=now,
            ),
            OpenClawSendResponseNormalized(
                normalized_outcome_class="success",
                provider_status_code="ok",
                provider_receipt_ref="msg-final",
                provider_error_class_hint=None,
                provider_error_message_sanitized=None,
                provider_confirmation_strength="confirmed",
                raw_observed_at_utc=now + timedelta(minutes=5),
            ),
        ]

        def send_fn(_: OutboundMessage) -> OpenClawSendResponseNormalized:
            return replies.pop(0)

        clock = {"now": now}
        adapter = OpenClawGatewayAdapter(send_fn=send_fn, now_fn=lambda: clock["now"], adapter_dedupe_window_ms=0)

        first = _run_cycle(store, adapter, now)
        clock["now"] = now + timedelta(minutes=5)
        second = _run_cycle(store, adapter, now + timedelta(minutes=5))

        rows = store.conn.execute(
            "SELECT attempt_index, reason_code, delivery_confidence, provider_accept_only "
            "FROM delivery_attempts ORDER BY attempt_index"
        ).fetchall()
        reasons = [r["reason_code"] for r in rows]
        invariant_confirmed = all(
            not (r["delivery_confidence"] == "provider_confirmed" and int(r["provider_accept_only"]) == 1)
            for r in rows
        )
        expected = [ReasonCode.FAILED_PROVIDER_TRANSIENT.value, ReasonCode.DELIVERED_SUCCESS.value]
        passed = reasons == expected and invariant_confirmed

        return DrillResult(
            drill_id="D2_FAILURE_INJECTION",
            objective="simulate transient adapter failure and verify deterministic classification + recovery path",
            passed=passed,
            observed={
                "first_cycle": first,
                "second_cycle": second,
                "attempt_rows": [dict(r) for r in rows],
                "reasons": reasons,
                "invariant_provider_confirmed_accept_only_false": invariant_confirmed,
            },
            residual_risk=None if passed else "failure classification or retry recovery drift",
        )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _drill_rollback() -> DrillResult:
    with tempfile.TemporaryDirectory() as td:
        cfg = Path(td) / "openclaw.sim.json"
        backup = Path(td) / "openclaw.sim.json.bak"

        original = {
            "tools": {"agentToAgent": {"enabled": True}},
            "note": "phase4 rollback simulation",
        }
        cfg.write_text(json.dumps(original, indent=2), encoding="utf-8")
        original_hash = _sha256(cfg)

        shutil.copy2(cfg, backup)

        mutated = {
            "tools": {"agentToAgent": {"enabled": False}},
            "note": "phase4 rollback simulation",
        }
        cfg.write_text(json.dumps(mutated, indent=2), encoding="utf-8")
        mutated_hash = _sha256(cfg)

        shutil.copy2(backup, cfg)
        restored_hash = _sha256(cfg)

        passed = original_hash != mutated_hash and restored_hash == original_hash
        return DrillResult(
            drill_id="D3_ROLLBACK_DRILL",
            objective="simulate rollback procedure and prove restoration to original state hash",
            passed=passed,
            observed={
                "original_hash": original_hash,
                "mutated_hash": mutated_hash,
                "restored_hash": restored_hash,
                "rollback_restored": restored_hash == original_hash,
                "simulation_paths": {"config": str(cfg), "backup": str(backup)},
            },
            residual_risk=None if passed else "rollback restoration hash mismatch",
        )


def run(output_dir: Path) -> dict:
    now = datetime(2026, 3, 26, 11, 40, tzinfo=UTC)
    drills = [
        _drill_restart_continuity(now),
        _drill_failure_injection(now),
        _drill_rollback(),
    ]

    output_dir.mkdir(parents=True, exist_ok=True)
    for d in drills:
        (output_dir / f"{d.drill_id}.json").write_text(
            json.dumps(
                {
                    "drill_id": d.drill_id,
                    "objective": d.objective,
                    "passed": d.passed,
                    "observed": d.observed,
                    "residual_risk": d.residual_risk,
                },
                indent=2,
                default=str,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

    matrix = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "drills": [asdict(d) for d in drills],
        "all_pass": all(d.passed for d in drills),
    }
    (output_dir / "drill_matrix.json").write_text(
        json.dumps(matrix, indent=2, default=str, sort_keys=True),
        encoding="utf-8",
    )
    return matrix


def main() -> None:
    parser = argparse.ArgumentParser(description="Kinflow Phase 4 hardening kickoff drill runner")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    out = run(Path(args.output_dir))
    print(json.dumps({"all_pass": out["all_pass"], "drill_count": len(out["drills"])}, indent=2))
    raise SystemExit(0 if out["all_pass"] else 1)


if __name__ == "__main__":
    main()
