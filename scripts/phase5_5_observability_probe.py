from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ctx002_v0.persistence.db import (
    apply_migrations,
    connect_sqlite,
    discover_migrations,
    enforce_foreign_keys,
)

ROOT = Path(__file__).resolve().parents[1]
MIG_DIR = ROOT / "migrations"
EXPECTED_CONTEXTS = [
    "Kinflow CI / lint",
    "Kinflow CI / test",
    "Kinflow CI / contracts",
]


def _seed_minimum_entities(conn: sqlite3.Connection, now_iso: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO events(event_id,current_version,status,created_at_utc,updated_at_utc) "
        "VALUES (?,?,?,?,?)",
        ("evt-obs", 1, "active", now_iso, now_iso),
    )
    conn.execute(
        "INSERT OR REPLACE INTO event_versions("
        "event_id,version,title,start_at_local_iso,end_at_local_iso,all_day,event_timezone,"
        "participants_json,audience_json,reminder_offset_minutes,source_message_ref,"
        "intent_hash,normalized_fields_hash,created_at_utc"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "evt-obs",
            1,
            "Observability Event",
            now_iso,
            None,
            0,
            "UTC",
            "[]",
            "[]",
            30,
            "msg-obs",
            "msg-obs",
            "msg-obs",
            now_iso,
        ),
    )
    conn.execute(
        "INSERT OR REPLACE INTO delivery_targets("
        "target_id,person_id,channel,target_ref,timezone,quiet_hours_start,quiet_hours_end,is_active,updated_at_utc"
        ") VALUES (?,?,?,?,?,?,?,?,?)",
        ("caleb", "caleb", "whatsapp", "120363425701060269@g.us", "UTC", 22, 7, 1, now_iso),
    )
    conn.execute(
        "INSERT OR REPLACE INTO reminders("
        "reminder_id,dedupe_key,event_id,event_version,recipient_target_id,offset_minutes,"
        "trigger_at_utc,next_attempt_at_utc,attempts,status,recipient_timezone_snapshot,tz_source,"
        "last_error_code,created_at_utc,updated_at_utc"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "rem-obs",
            "dedupe-obs",
            "evt-obs",
            1,
            "caleb",
            30,
            now_iso,
            None,
            0,
            "scheduled",
            "UTC",
            "EXPLICIT",
            None,
            now_iso,
            now_iso,
        ),
    )
    conn.commit()


def _insert_attempt(
    conn: sqlite3.Connection,
    *,
    attempt_id: str,
    attempt_index: int,
    status: str,
    reason_code: str,
    source_adapter_attempt_id: str | None,
    now_iso: str,
) -> None:
    conn.execute(
        "INSERT INTO delivery_attempts("
        "attempt_id,reminder_id,attempt_index,attempted_at_utc,status,reason_code,"
        "provider_ref,provider_status_code,provider_error_text,provider_accept_only,"
        "delivery_confidence,result_at_utc,trace_id,causation_id,source_adapter_attempt_id"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            attempt_id,
            "rem-obs",
            attempt_index,
            now_iso,
            status,
            reason_code,
            f"provider-{attempt_id}",
            "ok" if status == "delivered" else "err",
            None if status == "delivered" else "synthetic",
            0,
            "provider_confirmed" if status == "delivered" else "none",
            now_iso,
            "delivery",
            "rem-obs",
            source_adapter_attempt_id,
        ),
    )


def _eval_sql_signals(conn: sqlite3.Connection, lookback_iso: str) -> dict:
    replay = conn.execute(
        "SELECT COUNT(*) FROM delivery_attempts "
        "WHERE attempted_at_utc >= ? "
        "AND source_adapter_attempt_id IS NOT NULL "
        "AND source_adapter_attempt_id <> attempt_id",
        (lookback_iso,),
    ).fetchone()[0]
    retry = conn.execute(
        "SELECT COUNT(*) FROM delivery_attempts "
        "WHERE attempted_at_utc >= ? AND reason_code='FAILED_RETRY_EXHAUSTED'",
        (lookback_iso,),
    ).fetchone()[0]
    blocked = conn.execute(
        "SELECT COUNT(*) FROM delivery_attempts "
        "WHERE attempted_at_utc >= ? AND status='blocked'",
        (lookback_iso,),
    ).fetchone()[0]
    breakdown_rows = conn.execute(
        "SELECT reason_code, COUNT(*) FROM delivery_attempts "
        "WHERE attempted_at_utc >= ? AND status='blocked' GROUP BY reason_code ORDER BY COUNT(*) DESC, reason_code ASC",
        (lookback_iso,),
    ).fetchall()
    blocked_breakdown = {row[0]: row[1] for row in breakdown_rows}

    return {
        "duplicate_replay_send_anomaly": {
            "count": replay,
            "threshold": ">=1",
            "triggered": replay >= 1,
        },
        "retry_exhaustion": {
            "count": retry,
            "threshold": ">=1",
            "triggered": retry >= 1,
        },
        "blocked_outcomes": {
            "count": blocked,
            "threshold": ">=3",
            "triggered": blocked >= 3,
            "reason_code_breakdown": blocked_breakdown,
        },
    }


def _ci_protection_state() -> dict:
    main_branch = json.loads(
        subprocess.check_output(["gh", "api", "repos/calebini/kinflow/branches/main"], text=True)
    )
    protection = json.loads(
        subprocess.check_output(["gh", "api", "repos/calebini/kinflow/branches/main/protection"], text=True)
    )

    contexts = protection.get("required_status_checks", {}).get("contexts", [])
    strict = protection.get("required_status_checks", {}).get("strict", False)
    approvals = protection.get("required_pull_request_reviews", {}).get("required_approving_review_count", 0)

    return {
        "head_commit_sha": main_branch["commit"]["sha"],
        "strict_mode": strict,
        "configured_contexts": contexts,
        "contexts_exact_match": sorted(contexts) == sorted(EXPECTED_CONTEXTS),
        "required_approvals": approvals,
        "drift_triggered": (not strict) or (sorted(contexts) != sorted(EXPECTED_CONTEXTS)) or approvals < 1,
    }


def run(output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(UTC)
    now_iso = now.isoformat()
    lookback_iso = (now - timedelta(minutes=60)).isoformat()

    with tempfile.TemporaryDirectory() as td:
        temp = Path(td)
        trigger_db = temp / "signals_trigger.sqlite"
        clear_db = temp / "signals_clear.sqlite"

        migrations = discover_migrations(MIG_DIR)

        conn_trigger = connect_sqlite(str(trigger_db))
        enforce_foreign_keys(conn_trigger)
        apply_migrations(conn_trigger, migrations)
        _seed_minimum_entities(conn_trigger, now_iso)
        _insert_attempt(
            conn_trigger,
            attempt_id="att-trigger-1",
            attempt_index=1,
            status="delivered",
            reason_code="DELIVERED_SUCCESS",
            source_adapter_attempt_id="att-trigger-1",
            now_iso=now_iso,
        )
        _insert_attempt(
            conn_trigger,
            attempt_id="att-trigger-2",
            attempt_index=2,
            status="delivered",
            reason_code="DELIVERED_SUCCESS",
            source_adapter_attempt_id="att-trigger-1",
            now_iso=now_iso,
        )
        _insert_attempt(
            conn_trigger,
            attempt_id="att-trigger-3",
            attempt_index=3,
            status="failed",
            reason_code="FAILED_RETRY_EXHAUSTED",
            source_adapter_attempt_id=None,
            now_iso=now_iso,
        )
        for idx in range(4, 7):
            _insert_attempt(
                conn_trigger,
                attempt_id=f"att-trigger-{idx}",
                attempt_index=idx,
                status="blocked",
                reason_code="TZ_MISSING" if idx < 6 else "CAPTURE_ONLY_BLOCKED",
                source_adapter_attempt_id=None,
                now_iso=now_iso,
            )
        conn_trigger.commit()

        conn_clear = connect_sqlite(str(clear_db))
        enforce_foreign_keys(conn_clear)
        apply_migrations(conn_clear, migrations)
        _seed_minimum_entities(conn_clear, now_iso)
        _insert_attempt(
            conn_clear,
            attempt_id="att-clear-1",
            attempt_index=1,
            status="delivered",
            reason_code="DELIVERED_SUCCESS",
            source_adapter_attempt_id="att-clear-1",
            now_iso=now_iso,
        )
        conn_clear.commit()

        trigger_signals = _eval_sql_signals(conn_trigger, lookback_iso)
        clear_signals = _eval_sql_signals(conn_clear, lookback_iso)

    ci_actual = _ci_protection_state()
    ci_drift_simulated = {
        "head_commit_sha": ci_actual["head_commit_sha"],
        "strict_mode": False,
        "configured_contexts": ["lint", "test"],
        "contexts_exact_match": False,
        "required_approvals": 0,
        "drift_triggered": True,
    }

    signal_matrix = [
        {
            "signal_id": "duplicate_replay_send_anomaly",
            "source": "delivery_attempts(source_adapter_attempt_id vs attempt_id)",
            "threshold": ">=1 in 60m",
            "test_evidence": {
                "trigger": trigger_signals["duplicate_replay_send_anomaly"],
                "clear": clear_signals["duplicate_replay_send_anomaly"],
            },
            "status": "PASS"
            if trigger_signals["duplicate_replay_send_anomaly"]["triggered"]
            and not clear_signals["duplicate_replay_send_anomaly"]["triggered"]
            else "FAIL",
        },
        {
            "signal_id": "retry_exhaustion",
            "source": "delivery_attempts(reason_code=FAILED_RETRY_EXHAUSTED)",
            "threshold": ">=1 in 60m",
            "test_evidence": {
                "trigger": trigger_signals["retry_exhaustion"],
                "clear": clear_signals["retry_exhaustion"],
            },
            "status": "PASS"
            if trigger_signals["retry_exhaustion"]["triggered"] and not clear_signals["retry_exhaustion"]["triggered"]
            else "FAIL",
        },
        {
            "signal_id": "blocked_outcomes",
            "source": "delivery_attempts(status=blocked + reason breakdown)",
            "threshold": ">=3 in 60m",
            "test_evidence": {
                "trigger": trigger_signals["blocked_outcomes"],
                "clear": clear_signals["blocked_outcomes"],
            },
            "status": "PASS"
            if trigger_signals["blocked_outcomes"]["triggered"] and not clear_signals["blocked_outcomes"]["triggered"]
            else "FAIL",
        },
        {
            "signal_id": "ci_protection_drift",
            "source": "GitHub branch protection(main) strict+contexts+approvals",
            "threshold": "strict=true && contexts exact && approvals>=1",
            "test_evidence": {
                "trigger": ci_drift_simulated,
                "clear": ci_actual,
            },
            "status": "PASS" if ci_drift_simulated["drift_triggered"] and not ci_actual["drift_triggered"] else "FAIL",
        },
    ]

    alert_routing = [
        {
            "signal_id": "duplicate_replay_send_anomaly",
            "severity": "high",
            "runbook": "docs/KINFLOW_OPERATOR_RUNBOOK_PHASE4.md#incident-response-flow",
        },
        {
            "signal_id": "retry_exhaustion",
            "severity": "high",
            "runbook": "docs/KINFLOW_OPERATOR_RUNBOOK_PHASE4.md#incident-response-flow",
        },
        {
            "signal_id": "blocked_outcomes",
            "severity": "medium",
            "runbook": "docs/KINFLOW_OPERATOR_RUNBOOK_PHASE4.md#incident-response-flow",
        },
        {
            "signal_id": "ci_protection_drift",
            "severity": "critical",
            "runbook": "docs/KINFLOW_PHASE5_CI_ENFORCEMENT_REMEDIATION_REPORT.md",
        },
    ]

    manifest = {
        "phase": "5.5",
        "generated_at_utc": now_iso,
        "artifacts": [
            "observability/phase5_5/sqlite_signal_queries.sql",
            "observability/phase5_5/alert_policy.yaml",
            "scripts/phase5_5_observability_probe.py",
        ],
    }

    output = {
        "generated_at_utc": now_iso,
        "lookback_iso_utc": lookback_iso,
        "signal_matrix": signal_matrix,
        "alert_routing": alert_routing,
        "ci_actual": ci_actual,
        "ci_drift_simulated": ci_drift_simulated,
        "manifest": manifest,
    }

    (output_dir / "signal_matrix.json").write_text(json.dumps(signal_matrix, indent=2), encoding="utf-8")
    (output_dir / "alert_routing_matrix.json").write_text(json.dumps(alert_routing, indent=2), encoding="utf-8")
    (output_dir / "ci_actual_state.json").write_text(json.dumps(ci_actual, indent=2), encoding="utf-8")
    (output_dir / "ci_drift_simulated_state.json").write_text(
        json.dumps(ci_drift_simulated, indent=2), encoding="utf-8"
    )
    (output_dir / "observability_artifact_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (output_dir / "phase5_5_probe_output.json").write_text(json.dumps(output, indent=2), encoding="utf-8")

    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 5.5 observability kickoff probe")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    out = run(Path(args.output_dir))
    all_pass = all(row["status"] == "PASS" for row in out["signal_matrix"])
    print(json.dumps({"signal_rows": len(out["signal_matrix"]), "all_pass": all_pass}, indent=2))
    raise SystemExit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
