from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from ctx002_v0.persistence.db import (
    apply_migrations,
    connect_sqlite,
    discover_migrations,
    enforce_foreign_keys,
    ensure_schema_migrations_table,
)

ROOT = Path(__file__).resolve().parents[1]
MIG_DIR = ROOT / "migrations"


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _integrity_checks(conn: sqlite3.Connection) -> dict:
    checks: dict[str, object] = {}

    reason_codes = {r[0] for r in conn.execute("SELECT code FROM enum_reason_codes").fetchall()}
    checks["reason_codes_contains"] = {
        "DELIVERED_SUCCESS": "DELIVERED_SUCCESS" in reason_codes,
        "FAILED_PROVIDER_TRANSIENT": "FAILED_PROVIDER_TRANSIENT" in reason_codes,
        "CAPTURE_ONLY_BLOCKED": "CAPTURE_ONLY_BLOCKED" in reason_codes,
    }

    attempt_statuses = {r[0] for r in conn.execute("SELECT status FROM enum_attempt_status").fetchall()}
    checks["attempt_statuses_contains"] = {
        "blocked": "blocked" in attempt_statuses,
        "delivered": "delivered" in attempt_statuses,
        "failed": "failed" in attempt_statuses,
    }

    cols = {r[1] for r in conn.execute("PRAGMA table_info(delivery_attempts)").fetchall()}
    required_cols = [
        "provider_status_code",
        "provider_error_text",
        "provider_accept_only",
        "delivery_confidence",
        "result_at_utc",
        "trace_id",
        "causation_id",
        "source_adapter_attempt_id",
    ]
    checks["delivery_attempts_columns_present"] = all(c in cols for c in required_cols)

    checks["foreign_keys_enabled"] = conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1

    now = datetime.now(UTC).isoformat()

    conn.execute(
        "INSERT OR REPLACE INTO events(event_id,current_version,status,created_at_utc,updated_at_utc) "
        "VALUES (?,?,?,?,?)",
        ("evt-mig", 1, "active", now, now),
    )

    conn.execute(
        "INSERT OR REPLACE INTO event_versions("
        "event_id,version,title,start_at_local_iso,end_at_local_iso,all_day,event_timezone,"
        "participants_json,audience_json,reminder_offset_minutes,source_message_ref,"
        "intent_hash,normalized_fields_hash,created_at_utc"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "evt-mig",
            1,
            "Migration Event",
            now,
            None,
            0,
            "UTC",
            "[]",
            "[]",
            30,
            "msg-mig",
            "msg-mig",
            "msg-mig",
            now,
        ),
    )

    conn.execute(
        "INSERT OR REPLACE INTO delivery_targets("
        "target_id,person_id,channel,target_ref,timezone,quiet_hours_start,quiet_hours_end,is_active,updated_at_utc"
        ") VALUES (?,?,?,?,?,?,?,?,?)",
        ("caleb", "caleb", "whatsapp", "120363425701060269@g.us", "UTC", 22, 7, 1, now),
    )

    conn.execute(
        "INSERT OR REPLACE INTO reminders("
        "reminder_id,dedupe_key,event_id,event_version,recipient_target_id,offset_minutes,"
        "trigger_at_utc,next_attempt_at_utc,attempts,status,recipient_timezone_snapshot,tz_source,"
        "last_error_code,created_at_utc,updated_at_utc"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "rem-mig",
            "dedupe-mig",
            "evt-mig",
            1,
            "caleb",
            30,
            now,
            None,
            0,
            "scheduled",
            "UTC",
            "EXPLICIT",
            None,
            now,
            now,
        ),
    )

    insert_sql = (
        "INSERT INTO delivery_attempts("
        "attempt_id,reminder_id,attempt_index,attempted_at_utc,status,reason_code,"
        "provider_ref,provider_status_code,provider_error_text,provider_accept_only,"
        "delivery_confidence,result_at_utc,trace_id,causation_id,source_adapter_attempt_id"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
    )

    valid_insert_ok = True
    try:
        conn.execute(
            insert_sql,
            (
                "att-mig-1",
                "rem-mig",
                1,
                now,
                "delivered",
                "DELIVERED_SUCCESS",
                "msg-1",
                "ok",
                None,
                0,
                "provider_confirmed",
                now,
                "trace-mig",
                "cause-mig",
                "att-mig-1",
            ),
        )
        conn.commit()
    except Exception:
        valid_insert_ok = False
    checks["valid_delivery_attempt_insert"] = valid_insert_ok

    invalid_reason_rejected = False
    try:
        conn.execute(
            insert_sql,
            (
                "att-mig-2",
                "rem-mig",
                2,
                now,
                "failed",
                "NOT_A_REASON",
                None,
                "err",
                "oops",
                0,
                "none",
                now,
                "trace-mig",
                "cause-mig",
                "att-mig-2",
            ),
        )
        conn.commit()
    except Exception:
        invalid_reason_rejected = True
    checks["invalid_reason_rejected"] = invalid_reason_rejected

    return checks


def _scenario_forward_clean(tmp: Path) -> dict:
    db = tmp / "clean.sqlite"
    migrations = discover_migrations(MIG_DIR)
    conn = connect_sqlite(str(db))
    enforce_foreign_keys(conn)
    apply_migrations(conn, migrations)
    checks = _integrity_checks(conn)
    return {
        "scenario": "forward_clean_db",
        "db_path": str(db),
        "applied_migrations": [m.version for m in migrations],
        "checks": checks,
        "pass": all(checks.values()) if checks else False,
    }


def _scenario_forward_preexisting(tmp: Path) -> dict:
    db = tmp / "preexisting.sqlite"
    migrations = discover_migrations(MIG_DIR)
    first = [m for m in migrations if m.version.startswith("0001_")]

    conn = connect_sqlite(str(db))
    enforce_foreign_keys(conn)
    ensure_schema_migrations_table(conn)
    apply_migrations(conn, first)

    conn.execute(
        "INSERT OR IGNORE INTO enum_reason_codes(code,class,active,version_tag) "
        "VALUES ('DELIVERED','success',1,'legacy')"
    )
    conn.commit()

    apply_migrations(conn, migrations)
    checks = _integrity_checks(conn)
    delivered_present = conn.execute(
        "SELECT COUNT(*) FROM enum_reason_codes WHERE code='DELIVERED'"
    ).fetchone()[0]
    delivered_success_present = conn.execute(
        "SELECT COUNT(*) FROM enum_reason_codes WHERE code='DELIVERED_SUCCESS'"
    ).fetchone()[0]

    return {
        "scenario": "forward_preexisting_db",
        "db_path": str(db),
        "applied_migrations": [m.version for m in migrations],
        "checks": checks,
        "reason_code_post_state": {
            "DELIVERED_present": delivered_present,
            "DELIVERED_SUCCESS_present": delivered_success_present,
        },
        "pass": all(checks.values()) and delivered_present == 0 and delivered_success_present == 1,
    }


def _scenario_rollback_rehearsal(tmp: Path) -> dict:
    db = tmp / "rollback.sqlite"
    backup = tmp / "rollback.pre.sqlite"
    migrations = discover_migrations(MIG_DIR)

    conn = connect_sqlite(str(db))
    enforce_foreign_keys(conn)
    ensure_schema_migrations_table(conn)
    apply_migrations(conn, [m for m in migrations if m.version.startswith("0001_")])
    conn.close()

    shutil.copy2(db, backup)
    before_hash = _file_sha256(db)

    conn2 = connect_sqlite(str(db))
    enforce_foreign_keys(conn2)
    apply_migrations(conn2, migrations)
    conn2.close()
    after_forward_hash = _file_sha256(db)

    shutil.copy2(backup, db)
    after_restore_hash = _file_sha256(db)

    conn3 = connect_sqlite(str(db))
    enforce_foreign_keys(conn3)
    rows = conn3.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
    conn3.close()

    passed = before_hash != after_forward_hash and before_hash == after_restore_hash
    return {
        "scenario": "rollback_rehearsal_snapshot_restore",
        "db_path": str(db),
        "backup_path": str(backup),
        "hashes": {
            "before_forward": before_hash,
            "after_forward": after_forward_hash,
            "after_restore": after_restore_hash,
        },
        "schema_migration_rows_after_restore": rows,
        "pass": passed,
    }


def run(output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        s1 = _scenario_forward_clean(tmp)
        s2 = _scenario_forward_preexisting(tmp)
        s3 = _scenario_rollback_rehearsal(tmp)

    matrix = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "scenarios": [s1, s2, s3],
        "all_pass": all(s["pass"] for s in [s1, s2, s3]),
    }

    for s in matrix["scenarios"]:
        (output_dir / f"migration_{s['scenario']}.json").write_text(
            json.dumps(s, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    (output_dir / "migration_matrix.json").write_text(
        json.dumps(matrix, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return matrix


def main() -> None:
    parser = argparse.ArgumentParser(description="Kinflow Phase 5 migration rehearsal runner")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    out = run(Path(args.output_dir))
    print(json.dumps({"all_pass": out["all_pass"], "scenario_count": len(out["scenarios"])}, indent=2))
    raise SystemExit(0 if out["all_pass"] else 1)


if __name__ == "__main__":
    main()
