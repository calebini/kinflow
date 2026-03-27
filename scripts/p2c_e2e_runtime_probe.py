from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from ctx002_v0.daemon import DaemonRuntime, validate_daemon_config
from ctx002_v0.engine import FamilySchedulerV0
from ctx002_v0.models import DeliveryTarget
from ctx002_v0.oc_adapter import (
    AdapterCapabilities,
    OpenClawGatewayAdapter,
    OpenClawSendResponseNormalized,
    OutboundMessage,
    delivery_result_to_attempt_kwargs,
)
from ctx002_v0.persistence.store import SqliteStateStore
from ctx002_v0.reason_codes import ReasonCode


@dataclass
class ProviderReply:
    normalized_outcome_class: str
    provider_status_code: str | None
    provider_receipt_ref: str | None
    provider_error_class_hint: str | None
    provider_error_message_sanitized: str | None
    provider_confirmation_strength: str


class ProviderStub:
    def __init__(self, replies: list[ProviderReply], *, now_fn) -> None:
        self._replies = list(replies)
        self._now_fn = now_fn
        self.visible_send_count = 0

    def send(self, _: OutboundMessage) -> OpenClawSendResponseNormalized:
        self.visible_send_count += 1
        if self._replies:
            reply = self._replies.pop(0)
        else:
            reply = ProviderReply(
                normalized_outcome_class="success",
                provider_status_code="ok",
                provider_receipt_ref=f"msg-{self.visible_send_count}",
                provider_error_class_hint=None,
                provider_error_message_sanitized=None,
                provider_confirmation_strength="confirmed",
            )
        return OpenClawSendResponseNormalized(
            normalized_outcome_class=reply.normalized_outcome_class,
            provider_status_code=reply.provider_status_code,
            provider_receipt_ref=reply.provider_receipt_ref,
            provider_error_class_hint=reply.provider_error_class_hint,
            provider_error_message_sanitized=reply.provider_error_message_sanitized,
            provider_confirmation_strength=reply.provider_confirmation_strength,
            raw_observed_at_utc=self._now_fn(),
        )


def _config() -> dict[str, Any]:
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


def _now_factory(start: datetime):
    state = {"now": start}

    def now() -> datetime:
        return state["now"]

    def set_now(new_now: datetime) -> None:
        state["now"] = new_now

    return now, set_now


def _setup_store(db_path: str, now: datetime) -> tuple[SqliteStateStore, FamilySchedulerV0]:
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
    store.set_runtime_mode("normal")
    return store, scheduler


def _find_reminder(store: SqliteStateStore, reminder_id: str):
    for reminder in store.list_reminders():
        if reminder.reminder_id == reminder_id:
            return reminder
    raise KeyError(reminder_id)


def _run_daemon_cycle(
    *,
    store: SqliteStateStore,
    adapter: OpenClawGatewayAdapter,
    now: datetime,
    max_retries: int = 2,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []

    runtime: DaemonRuntime

    def list_candidates() -> list[dict[str, str]]:
        return [{"id": r.reminder_id} for r in store.list_due_reminders(now)]

    def process_candidate(row: dict[str, str]) -> bool:
        reminder = _find_reminder(store, row["id"])
        target = store.get_delivery_target(reminder.recipient_id)
        if target is None:
            raise RuntimeError("missing target")

        cycle_id = f"{runtime.trace_id}:{runtime.cycle_seq}"
        causation_id = f"ROOT:{cycle_id}"
        attempt_index = reminder.attempts + 1

        outbound = OutboundMessage(
            delivery_id=reminder.reminder_id,
            attempt_id=f"{reminder.reminder_id}:{uuid4().hex}",
            attempt_index=attempt_index,
            trace_id=runtime.trace_id,
            causation_id=causation_id,
            channel_hint=target.channel,
            target_ref=target.target_id,
            subject_type="event_reminder",
            priority="normal",
            body_text=f"Reminder {reminder.event_id}",
            dedupe_key=reminder.dedupe_key,
            created_at_utc=now,
            payload_json={"event_id": reminder.event_id},
            payload_schema_version=1,
            metadata_json={"daemon_cycle_id": cycle_id},
            metadata_schema_version=1,
        )

        result = adapter.send(outbound)
        store.append_delivery_attempt(
            **delivery_result_to_attempt_kwargs(
                result=result,
                reminder_id=reminder.reminder_id,
                attempt_index=attempt_index,
                attempted_at_utc=now,
            )
        )

        reminder.attempts = attempt_index
        if result.status == "DELIVERED":
            reminder.status = "delivered"
            reminder.next_attempt_at_utc = None
        elif result.status == "FAILED_TRANSIENT":
            if reminder.attempts > max_retries:
                reminder.status = "failed"
                reminder.next_attempt_at_utc = None
            else:
                reminder.status = "attempted"
                reminder.next_attempt_at_utc = now + timedelta(minutes=5)
        elif result.status == "FAILED_PERMANENT":
            reminder.status = "failed"
            reminder.next_attempt_at_utc = None
        elif result.status == "SUPPRESSED":
            reminder.status = "suppressed"
            reminder.next_attempt_at_utc = None
        else:
            reminder.status = "blocked"
            reminder.next_attempt_at_utc = None
        store.update_reminder(reminder)

        receipts.append(
            {
                "reminder_id": reminder.reminder_id,
                "attempt_index": attempt_index,
                "status": result.status,
                "reason_code": result.reason_code,
                "delivery_confidence": result.delivery_confidence,
                "provider_accept_only": result.provider_accept_only,
                "trace_id": result.trace_id,
                "causation_id": result.causation_id,
                "replay_indicator": result.replay_indicator,
                "replay_source": result.replay_source,
            }
        )
        return True

    runtime = DaemonRuntime(
        validate_daemon_config(_config()),
        read_runtime_mode=lambda: store.get_runtime_mode(),
        list_candidates=list_candidates,
        process_candidate=process_candidate,
        run_reconcile=lambda: True,
        emit_event=events.append,
    )
    runtime.startup(now)
    summary = runtime.run_cycle(now, now)
    return {"summary": summary, "events": events, "receipts": receipts}


def _intent(message_id: str, now: datetime, **overrides) -> dict[str, Any]:
    payload = {
        "message_id": message_id,
        "correlation_id": f"corr:{message_id}",
        "received_at_utc": now,
        "action": "create",
        "title": "Family dinner",
        "start_at_local": now.replace(tzinfo=None) + timedelta(minutes=30),
        "participants": ["caleb"],
        "audience": ["caleb"],
        "reminder_offset_minutes": 0,
        "confirmed": True,
        "event_timezone": "UTC",
    }
    payload.update(overrides)
    return payload


def _scenario_create_flow(now: datetime) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as td:
        store, scheduler = _setup_store(f"{td}/kinflow.sqlite", now)
        create = scheduler.process_intent(_intent("msg-create", now, start_at_local=now.replace(tzinfo=None)))

        provider = ProviderStub([], now_fn=lambda: now)
        adapter = OpenClawGatewayAdapter(send_fn=provider.send, now_fn=lambda: now)
        run = _run_daemon_cycle(store=store, adapter=adapter, now=now)

        row = store.conn.execute(
            "SELECT status, reason_code, delivery_confidence, "
            "provider_accept_only, trace_id, causation_id "
            "FROM delivery_attempts"
        ).fetchone()
        audit_row = adapter.audit_events[-1]
        passed = (
            create["status"] == "ok"
            and row is not None
            and row["reason_code"] == ReasonCode.DELIVERED_SUCCESS.value
            and row["delivery_confidence"] in {"provider_confirmed", "provider_accepted"}
            and bool(audit_row.get("daemon_cycle_id"))
        )
        return {
            "scenario": "create_flow_delivery_linkage",
            "passed": passed,
            "inputs": {"intent": "create", "runtime_mode": "normal"},
            "observed": {
                "daemon_summary": run["summary"],
                "delivery_attempt": dict(row) if row else None,
                "audit_event": audit_row,
                "visible_send_count": provider.visible_send_count,
            },
        }


def _scenario_update_flow(now: datetime) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as td:
        store, scheduler = _setup_store(f"{td}/kinflow.sqlite", now)
        t1 = now + timedelta(hours=1)
        create = scheduler.process_intent(_intent("msg-upd-create", now, start_at_local=t1.replace(tzinfo=None)))
        event_id = create["event_id"]

        t2 = now + timedelta(hours=2)
        update = scheduler.process_intent(
            _intent(
                "msg-upd-update",
                now,
                action="update",
                event_id=event_id,
                start_at_local=t2.replace(tzinfo=None),
            )
        )

        reminders = list(store.list_reminders())
        invalidated = [r.reminder_id for r in reminders if r.status == "invalidated"]
        scheduled = [r.reminder_id for r in reminders if r.status == "scheduled"]

        provider = ProviderStub([], now_fn=lambda: t2)
        adapter = OpenClawGatewayAdapter(send_fn=provider.send, now_fn=lambda: t2)
        run = _run_daemon_cycle(store=store, adapter=adapter, now=t2)

        row = store.conn.execute("SELECT COUNT(*) AS n FROM delivery_attempts").fetchone()
        passed = (
            update["status"] == "ok"
            and len(invalidated) >= 1
            and len(scheduled) >= 1
            and row["n"] >= 1
            and run["summary"]["rows_processed"] >= 1
        )
        return {
            "scenario": "update_flow_regeneration_linkage",
            "passed": passed,
            "inputs": {"intent": "update", "event_id": event_id},
            "observed": {
                "invalidated_reminders": invalidated,
                "scheduled_reminders": scheduled,
                "daemon_summary": run["summary"],
            },
        }


def _scenario_cancel_flow(now: datetime) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as td:
        store, scheduler = _setup_store(f"{td}/kinflow.sqlite", now)
        t1 = now + timedelta(hours=1)
        create = scheduler.process_intent(_intent("msg-can-create", now, start_at_local=t1.replace(tzinfo=None)))
        event_id = create["event_id"]
        cancel = scheduler.process_intent(
            _intent("msg-can-cancel", now, action="cancel", event_id=event_id, confirmed=True)
        )

        reminders = list(store.list_reminders())
        invalidated = [r.reminder_id for r in reminders if r.status == "invalidated"]

        provider = ProviderStub([], now_fn=lambda: now)
        adapter = OpenClawGatewayAdapter(send_fn=provider.send, now_fn=lambda: now)
        run = _run_daemon_cycle(store=store, adapter=adapter, now=now)

        passed = cancel["status"] == "ok" and len(invalidated) >= 1 and run["summary"]["rows_scanned"] == 0
        return {
            "scenario": "cancel_flow_invalidation",
            "passed": passed,
            "inputs": {"intent": "cancel", "event_id": event_id},
            "observed": {
                "invalidated_reminders": invalidated,
                "daemon_summary": run["summary"],
                "visible_send_count": provider.visible_send_count,
            },
        }


def _scenario_blocked_paths(now: datetime) -> dict[str, Any]:
    subcases: list[dict[str, Any]] = []

    def _run_one(*, target_ref: str, capabilities: AdapterCapabilities, adapter_runtime_mode: str) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as td:
            store, scheduler = _setup_store(f"{td}/kinflow.sqlite", now)
            target = store.get_delivery_target("caleb")
            if target is None:
                raise RuntimeError("missing target")
            store.save_delivery_target(
                DeliveryTarget(
                    person_id=target.person_id,
                    channel="whatsapp",
                    target_id=target_ref,
                    timezone=target.timezone,
                )
            )
            scheduler.process_intent(_intent("msg-block", now, start_at_local=now.replace(tzinfo=None)))
            provider = ProviderStub([], now_fn=lambda: now)
            adapter = OpenClawGatewayAdapter(
                send_fn=provider.send,
                now_fn=lambda: now,
                read_runtime_mode=lambda: adapter_runtime_mode,
                capabilities=capabilities,
            )
            run = _run_daemon_cycle(store=store, adapter=adapter, now=now)
            row = store.conn.execute(
                "SELECT status, reason_code FROM delivery_attempts ORDER BY attempt_index DESC LIMIT 1"
            ).fetchone()
            return {
                "daemon_summary": run["summary"],
                "delivery_attempt": dict(row) if row else None,
                "visible_send_count": provider.visible_send_count,
            }

    subcases.append(
        {
            "case": "capability_unsupported",
            "observed": _run_one(
                target_ref="120363425701060269@g.us",
                capabilities=AdapterCapabilities(
                    supports_channel_hints=("discord",),
                    supports_media=False,
                    supports_priority=True,
                    supports_delivery_receipts=True,
                    supports_target_resolution=False,
                ),
                adapter_runtime_mode="normal",
            ),
            "expected_reason": ReasonCode.FAILED_CAPABILITY_UNSUPPORTED.value,
        }
    )
    subcases.append(
        {
            "case": "invalid_target_shape_unresolved_alias",
            "observed": _run_one(
                target_ref="whatsapp:g-caleb-loop",
                capabilities=AdapterCapabilities(
                    supports_channel_hints=("whatsapp",),
                    supports_media=False,
                    supports_priority=True,
                    supports_delivery_receipts=True,
                    supports_target_resolution=False,
                ),
                adapter_runtime_mode="normal",
            ),
            "expected_reason": ReasonCode.FAILED_CAPABILITY_UNSUPPORTED.value,
        }
    )
    subcases.append(
        {
            "case": "capture_only_block",
            "observed": _run_one(
                target_ref="120363425701060269@g.us",
                capabilities=AdapterCapabilities(
                    supports_channel_hints=("whatsapp",),
                    supports_media=False,
                    supports_priority=True,
                    supports_delivery_receipts=True,
                    supports_target_resolution=False,
                ),
                adapter_runtime_mode="capture_only",
            ),
            "expected_reason": ReasonCode.CAPTURE_ONLY_BLOCKED.value,
        }
    )

    passed = True
    for case in subcases:
        row = case["observed"]["delivery_attempt"]
        if row is None or row["status"] != "blocked" or row["reason_code"] != case["expected_reason"]:
            passed = False

    return {
        "scenario": "blocked_paths_deterministic",
        "passed": passed,
        "inputs": {"subcases": [c["case"] for c in subcases]},
        "observed": subcases,
    }


def _scenario_retry_path(now: datetime) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as td:
        store, scheduler = _setup_store(f"{td}/kinflow.sqlite", now)
        scheduler.process_intent(_intent("msg-retry", now, start_at_local=now.replace(tzinfo=None)))

        clock = {"now": now}
        provider = ProviderStub(
            [
                ProviderReply(
                    normalized_outcome_class="transient",
                    provider_status_code="timeout",
                    provider_receipt_ref=None,
                    provider_error_class_hint="transient",
                    provider_error_message_sanitized="timeout",
                    provider_confirmation_strength="none",
                ),
                ProviderReply(
                    normalized_outcome_class="success",
                    provider_status_code="ok",
                    provider_receipt_ref="msg-final",
                    provider_error_class_hint=None,
                    provider_error_message_sanitized=None,
                    provider_confirmation_strength="confirmed",
                ),
            ],
            now_fn=lambda: clock["now"],
        )
        adapter = OpenClawGatewayAdapter(
            send_fn=provider.send,
            now_fn=lambda: clock["now"],
            adapter_dedupe_window_ms=0,
        )

        first = _run_daemon_cycle(store=store, adapter=adapter, now=now)
        second_time = now + timedelta(minutes=5)
        clock["now"] = second_time
        second = _run_daemon_cycle(store=store, adapter=adapter, now=second_time)

        rows = store.conn.execute(
            "SELECT attempt_index, reason_code FROM delivery_attempts ORDER BY attempt_index"
        ).fetchall()
        reasons = [r["reason_code"] for r in rows]
        passed = reasons == [ReasonCode.FAILED_PROVIDER_TRANSIENT.value, ReasonCode.DELIVERED_SUCCESS.value]
        return {
            "scenario": "retry_path_transient_then_success",
            "passed": passed,
            "inputs": {"provider_replies": ["transient", "success"]},
            "observed": {
                "first_cycle": first["summary"],
                "second_cycle": second["summary"],
                "attempt_reasons": reasons,
                "visible_send_count": provider.visible_send_count,
            },
        }


def _scenario_replay_dedupe(now: datetime) -> dict[str, Any]:
    provider = ProviderStub([], now_fn=lambda: now)
    adapter = OpenClawGatewayAdapter(send_fn=provider.send, now_fn=lambda: now, adapter_dedupe_window_ms=60_000)

    base = {
        "delivery_id": "del-replay",
        "attempt_index": 1,
        "trace_id": "trace-replay",
        "causation_id": "ROOT:trace-replay:1",
        "channel_hint": "whatsapp",
        "target_ref": "120363425701060269@g.us",
        "subject_type": "event_reminder",
        "priority": "normal",
        "body_text": "Replay test",
        "dedupe_key": "dedupe-replay-1",
        "created_at_utc": now,
        "payload_json": {"p": 1},
        "payload_schema_version": 1,
        "metadata_json": {"daemon_cycle_id": "cycle-replay"},
        "metadata_schema_version": 1,
    }
    r1 = adapter.send(OutboundMessage(attempt_id="att-replay-1", **base))
    r2 = adapter.send(OutboundMessage(attempt_id="att-replay-2", **base))

    passed = (
        provider.visible_send_count == 1
        and not r1.replay_indicator
        and r2.replay_indicator
        and r2.replay_source == "dedupe_key_window_hit"
    )
    return {
        "scenario": "replay_dedupe_no_duplicate_visible_send",
        "passed": passed,
        "inputs": {"attempt_ids": ["att-replay-1", "att-replay-2"]},
        "observed": {
            "result_first": asdict(r1),
            "result_second": asdict(r2),
            "visible_send_count": provider.visible_send_count,
        },
    }


def run_probe(output_dir: Path) -> dict[str, Any]:
    now = datetime(2026, 3, 25, 23, 20, tzinfo=UTC)
    scenarios = [
        _scenario_create_flow(now),
        _scenario_update_flow(now),
        _scenario_cancel_flow(now),
        _scenario_blocked_paths(now),
        _scenario_retry_path(now),
        _scenario_replay_dedupe(now),
    ]

    output_dir.mkdir(parents=True, exist_ok=True)
    for row in scenarios:
        (output_dir / f"receipt_{row['scenario']}.json").write_text(
            json.dumps(row, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )

    all_pass = all(row["passed"] for row in scenarios)
    summary = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "all_pass": all_pass,
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
    }
    (output_dir / "scenario_matrix.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run KINFLOW P2-C e2e runtime verification probe")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    summary = run_probe(Path(args.output_dir))
    print(json.dumps({"all_pass": summary["all_pass"], "scenario_count": summary["scenario_count"]}, indent=2))
    raise SystemExit(0 if summary["all_pass"] else 1)


if __name__ == "__main__":
    main()
