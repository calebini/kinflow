from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ctx002_v0 import FamilySchedulerV0
from ctx002_v0.notification_renderer import FALLBACK_REASON_CODE, RENDERER_VERSION, render_reminder_text


def _now_utc() -> datetime:
    return datetime.now(tz=UTC)


def _load_targets(db_path: str) -> dict[str, dict[str, str]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT person_id, channel, target_ref, timezone FROM delivery_targets WHERE is_active = 1"
        ).fetchall()
        return {
            r["person_id"]: {
                "channel": r["channel"],
                "target_ref": r["target_ref"],
                "timezone": r["timezone"],
            }
            for r in rows
        }
    finally:
        conn.close()


def _send_via_openclaw(channel: str, target: str, message: str) -> tuple[bool, dict[str, Any]]:
    cmd = [
        "openclaw",
        "message",
        "send",
        "--channel",
        channel,
        "--target",
        target,
        "--message",
        message,
        "--json",
    ]
    run = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    parsed: Any = None
    try:
        parsed = json.loads((run.stdout or "").strip() or "null")
    except json.JSONDecodeError:
        parsed = None
    ok = run.returncode == 0
    return ok, {
        "argv": cmd,
        "returncode": run.returncode,
        "stdout": run.stdout,
        "stderr": run.stderr,
        "parsed": parsed,
    }


def _reason_code_registry_gate(
    *,
    registry_path: Path,
    required_code: str = FALLBACK_REASON_CODE,
) -> tuple[bool, str | None]:
    if not registry_path.exists():
        return False, "RENDER_REGISTRY_GATE_UNAVAILABLE"
    text = registry_path.read_text(encoding="utf-8")
    if re.search(rf"\b{re.escape(required_code)}\b", text) is None:
        return False, "REASON_CODE_REGISTRATION_MISSING"
    return True, None


def _db_reason_code_gate(
    *,
    db_path: str,
    required_code: str = FALLBACK_REASON_CODE,
) -> tuple[bool, str | None]:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT 1 FROM enum_reason_codes WHERE code = ?", (required_code,)).fetchone()
        if row is None:
            return False, "REASON_CODE_REGISTRATION_MISSING"
        return True, None
    finally:
        conn.close()


def _debug_suffix_gate(
    *,
    runtime_mode: str,
    debug_suffix_enabled: bool,
) -> tuple[bool, str | None]:
    if runtime_mode == "production" and debug_suffix_enabled:
        return False, "DEBUG_SUFFIX_PROD_FORBIDDEN"
    return True, None


def _append_fallback_audit_marker(
    *,
    db_path: str,
    event_id: str,
    reminder_id: str,
    reason_code: str,
) -> None:
    conn = sqlite3.connect(db_path)
    try:
        now = _now_utc().isoformat()
        payload = {
            "event": FALLBACK_REASON_CODE,
            "reason_code": reason_code,
            "event_id": event_id or "unknown-event",
            "reminder_id": reminder_id or "unknown-reminder",
            "renderer_version": RENDERER_VERSION,
        }
        conn.execute(
            """
            INSERT INTO audit_log(
                ts_utc, trace_id, causation_id, correlation_id, message_id,
                entity_type, entity_id, stage, reason_code, payload_schema_version, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                "dispatch_runner",
                reminder_id or "unknown-reminder",
                reminder_id or "unknown-reminder",
                reminder_id or "unknown-reminder",
                "reminder",
                reminder_id or "unknown-reminder",
                "delivery",
                reason_code,
                1,
                json.dumps(payload, sort_keys=True),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def run_tick(
    db_path: str,
    out_dir: Path,
    *,
    registry_path: Path,
    runtime_mode: str = "production",
    debug_suffix_enabled: bool = False,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)

    registry_ok, registry_error = _reason_code_registry_gate(registry_path=registry_path)
    if not registry_ok:
        payload = {
            "timestamp_utc": _now_utc().isoformat(),
            "status": "NO_GO",
            "error": registry_error,
        }
        (out_dir / "dispatch_tick_result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload

    db_gate_ok, db_gate_error = _db_reason_code_gate(db_path=db_path)
    if not db_gate_ok:
        payload = {
            "timestamp_utc": _now_utc().isoformat(),
            "status": "NO_GO",
            "error": db_gate_error,
        }
        (out_dir / "dispatch_tick_result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload

    debug_ok, debug_error = _debug_suffix_gate(runtime_mode=runtime_mode, debug_suffix_enabled=debug_suffix_enabled)
    if not debug_ok:
        payload = {
            "timestamp_utc": _now_utc().isoformat(),
            "status": "NO_GO",
            "error": debug_error,
        }
        (out_dir / "dispatch_tick_result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload

    scheduler = FamilySchedulerV0(household_timezone="Europe/Paris", db_path=db_path)
    targets = _load_targets(db_path)
    event_titles = {event.event_id: event.title for event in scheduler.active_events}

    send_logs: list[dict[str, Any]] = []

    def provider(reminder) -> bool:
        target = targets.get(reminder.recipient_id)
        if target is None:
            send_logs.append(
                {
                    "reminder_id": reminder.reminder_id,
                    "recipient_id": reminder.recipient_id,
                    "error": "missing_active_delivery_target",
                }
            )
            return False

        tz_name = target.get("timezone") or "UTC"
        local_time = reminder.trigger_at_utc.astimezone(ZoneInfo(tz_name)).strftime("%H:%M")
        render = render_reminder_text(
            {
                "event_id": reminder.event_id,
                "reminder_id": reminder.reminder_id,
                "title_display": event_titles.get(reminder.event_id, reminder.event_id),
                "display_time_hhmm": local_time,
                "display_tz_label": tz_name,
                "debug_suffix_enabled": debug_suffix_enabled,
            }
        )

        message = render.message
        if debug_suffix_enabled:
            message = f"{message} [event_id={reminder.event_id} reminder_id={reminder.reminder_id}]"

        ok, log = _send_via_openclaw(target["channel"], target["target_ref"], message)
        log["reminder_id"] = reminder.reminder_id
        log["event_id"] = reminder.event_id
        log["render_result"] = {
            "message": render.message,
            "fallback_used": render.fallback_used,
            "reason_code": render.reason_code,
        }

        if render.fallback_used:
            _append_fallback_audit_marker(
                db_path=db_path,
                event_id=reminder.event_id,
                reminder_id=reminder.reminder_id,
                reason_code=render.reason_code or FALLBACK_REASON_CODE,
            )
            log["fallback_audit_marker_emitted"] = True

        send_logs.append(log)
        return ok

    now = _now_utc()
    outcomes = scheduler.attempt_due_deliveries(now, provider=provider)

    payload = {
        "timestamp_utc": now.isoformat(),
        "db_path": db_path,
        "status": "OK",
        "outcomes": [{"dedupe_key": d, "reason_code": r.value} for d, r in outcomes],
        "send_logs": send_logs,
    }
    (out_dir / "dispatch_tick_result.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Kinflow dispatch tick runner using existing engine semantics")
    parser.add_argument("--db-path", default="/home/agent/projects/apps/kinflow/.anchor_runtime.sqlite")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--reason-registry-path",
        default="/home/agent/projects/apps/kinflow/specs/KINFLOW_REASON_CODES_CANONICAL.md",
    )
    parser.add_argument("--runtime-mode", default="production")
    parser.add_argument("--debug-suffix-enabled", action="store_true")
    args = parser.parse_args()

    out = Path(args.output_dir)
    result = run_tick(
        args.db_path,
        out,
        registry_path=Path(args.reason_registry_path),
        runtime_mode=args.runtime_mode,
        debug_suffix_enabled=args.debug_suffix_enabled,
    )
    print(
        json.dumps(
            {
                "status": result.get("status", "OK"),
                "error": result.get("error"),
                "db_path": args.db_path,
                "outcome_count": len(result.get("outcomes", [])),
                "artifact": str(out / "dispatch_tick_result.json"),
            },
            sort_keys=True,
        )
    )

    if result.get("status") == "NO_GO":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
