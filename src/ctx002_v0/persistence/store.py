from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable, Protocol

from ..models import TARGET_REF_MAX_LENGTH, AuditRecord, DeliveryTarget, Event, Reminder
from ..reason_codes import ReasonCode
from .db import bootstrap_database


class VersionConflictError(RuntimeError):
    pass


class TargetRefValidationError(ValueError):
    reason_code = ReasonCode.FAILED_CONFIG_INVALID_TARGET.value


def _validate_target_ref_width(target_ref: str) -> None:
    if len(target_ref) > TARGET_REF_MAX_LENGTH:
        raise TargetRefValidationError(
            f"{ReasonCode.FAILED_CONFIG_INVALID_TARGET.value}: target_ref length exceeds {TARGET_REF_MAX_LENGTH}"
        )


class StateStore(Protocol):
    def get_message_receipt(self, channel: str, conversation_id: str, message_id: str) -> dict | None: ...

    def find_recent_receipt_by_intent_hash(
        self, intent_hash: str, now_utc: datetime, window_hours: int
    ) -> dict | None: ...

    def save_message_receipt(
        self,
        channel: str,
        conversation_id: str,
        message_id: str,
        correlation_id: str,
        intent_hash: str,
        result: dict,
        created_at_utc: datetime,
    ) -> None: ...

    def list_active_events(self) -> tuple[Event, ...]: ...

    def get_latest_event(self, event_id: str) -> Event | None: ...

    def has_event(self, event_id: str) -> bool: ...

    def next_event_id(self) -> str: ...

    def save_new_event(self, event: Event) -> None: ...

    def append_event_version(self, event: Event) -> None: ...

    def list_reminders(self) -> tuple[Reminder, ...]: ...

    def list_due_reminders(self, now_utc: datetime, limit: int | None = None) -> tuple[Reminder, ...]: ...

    def count_due_reminders(self, now_utc: datetime) -> int: ...

    def save_reminder(self, reminder: Reminder) -> None: ...

    def has_reminder_dedupe(self, dedupe_key: str) -> bool: ...

    def update_reminder(self, reminder: Reminder) -> None: ...

    def save_delivery_target(self, target: DeliveryTarget) -> None: ...

    def get_delivery_target(self, person_id: str) -> DeliveryTarget | None: ...

    def list_delivery_targets(self) -> tuple[DeliveryTarget, ...]: ...

    def append_audit(self, row: AuditRecord) -> None: ...

    def list_audit(self) -> tuple[AuditRecord, ...]: ...

    def get_runtime_mode(self) -> str: ...

    def set_runtime_mode(self, mode: str) -> None: ...

    def get_idempotency_window_hours(self) -> int: ...

    def get_max_retry_attempts(self) -> int: ...

    def append_delivery_attempt(
        self,
        *,
        attempt_id: str,
        reminder_id: str,
        attempt_index: int,
        attempted_at_utc: datetime,
        status: str,
        reason_code: str,
        provider_ref: str | None,
        provider_status_code: str | None,
        provider_error_text: str | None,
        provider_accept_only: bool,
        delivery_confidence: str,
        result_at_utc: datetime,
        trace_id: str,
        causation_id: str,
        source_adapter_attempt_id: str | None,
    ) -> None: ...


class InMemoryStateStore:
    def __init__(self) -> None:
        self.event_versions: dict[str, list[Event]] = {}
        self.reminders: dict[str, Reminder] = {}
        self.delivery_targets: dict[str, DeliveryTarget] = {}
        self.audit: list[AuditRecord] = []
        self.receipts: dict[tuple[str, str, str], tuple[datetime, str, dict]] = {}
        self.event_counter = 0
        self.runtime_mode = "normal"
        self.idempotency_window_hours = 24
        self.max_retry_attempts = 3
        self.delivery_attempts: list[dict[str, object]] = []

    def get_message_receipt(self, channel: str, conversation_id: str, message_id: str) -> dict | None:
        row = self.receipts.get((channel, conversation_id, message_id))
        return row[2] if row else None

    def find_recent_receipt_by_intent_hash(self, intent_hash: str, now_utc: datetime, window_hours: int) -> dict | None:
        lower = now_utc - timedelta(hours=window_hours)
        for created_at, stored_hash, result in sorted(self.receipts.values(), key=lambda x: x[0], reverse=True):
            if stored_hash != intent_hash:
                continue
            if created_at < lower:
                continue
            return result
        return None

    def save_message_receipt(
        self,
        channel: str,
        conversation_id: str,
        message_id: str,
        correlation_id: str,
        intent_hash: str,
        result: dict,
        created_at_utc: datetime,
    ) -> None:
        self.receipts[(channel, conversation_id, message_id)] = (created_at_utc, intent_hash, result)

    def list_active_events(self) -> tuple[Event, ...]:
        current = []
        for versions in self.event_versions.values():
            if versions and versions[-1].status == "active":
                current.append(versions[-1])
        return tuple(sorted(current, key=lambda e: e.event_id))

    def get_latest_event(self, event_id: str) -> Event | None:
        versions = self.event_versions.get(event_id)
        if not versions:
            return None
        return versions[-1]

    def has_event(self, event_id: str) -> bool:
        return event_id in self.event_versions

    def next_event_id(self) -> str:
        self.event_counter += 1
        return f"evt-{self.event_counter:04d}"

    def save_new_event(self, event: Event) -> None:
        self.event_versions[event.event_id] = [event]

    def append_event_version(self, event: Event) -> None:
        self.event_versions.setdefault(event.event_id, []).append(event)

    def list_reminders(self) -> tuple[Reminder, ...]:
        return tuple(sorted(self.reminders.values(), key=lambda r: r.dedupe_key))

    def list_due_reminders(self, now_utc: datetime, limit: int | None = None) -> tuple[Reminder, ...]:
        rows = []
        for reminder in self.reminders.values():
            if reminder.status not in {"scheduled", "attempted"}:
                continue
            due = reminder.next_attempt_at_utc or reminder.trigger_at_utc
            if due <= now_utc:
                rows.append(reminder)
        ordered = sorted(rows, key=lambda r: (r.trigger_at_utc, r.reminder_id))
        if limit is None:
            return tuple(ordered)
        return tuple(ordered[:limit])

    def count_due_reminders(self, now_utc: datetime) -> int:
        return len(self.list_due_reminders(now_utc))

    def save_reminder(self, reminder: Reminder) -> None:
        self.reminders[reminder.dedupe_key] = reminder

    def has_reminder_dedupe(self, dedupe_key: str) -> bool:
        return dedupe_key in self.reminders

    def update_reminder(self, reminder: Reminder) -> None:
        self.reminders[reminder.dedupe_key] = reminder

    def save_delivery_target(self, target: DeliveryTarget) -> None:
        _validate_target_ref_width(target.target_id)
        self.delivery_targets[target.person_id] = target

    def get_delivery_target(self, person_id: str) -> DeliveryTarget | None:
        return self.delivery_targets.get(person_id)

    def list_delivery_targets(self) -> tuple[DeliveryTarget, ...]:
        return tuple(self.delivery_targets.values())

    def append_audit(self, row: AuditRecord) -> None:
        self.audit.append(row)

    def list_audit(self) -> tuple[AuditRecord, ...]:
        return tuple(self.audit)

    def get_runtime_mode(self) -> str:
        return self.runtime_mode

    def set_runtime_mode(self, mode: str) -> None:
        self.runtime_mode = mode

    def get_idempotency_window_hours(self) -> int:
        return self.idempotency_window_hours

    def get_max_retry_attempts(self) -> int:
        return self.max_retry_attempts

    def append_delivery_attempt(
        self,
        *,
        attempt_id: str,
        reminder_id: str,
        attempt_index: int,
        attempted_at_utc: datetime,
        status: str,
        reason_code: str,
        provider_ref: str | None,
        provider_status_code: str | None,
        provider_error_text: str | None,
        provider_accept_only: bool,
        delivery_confidence: str,
        result_at_utc: datetime,
        trace_id: str,
        causation_id: str,
        source_adapter_attempt_id: str | None,
    ) -> None:
        self.delivery_attempts.append(
            {
                "attempt_id": attempt_id,
                "reminder_id": reminder_id,
                "attempt_index": attempt_index,
                "attempted_at_utc": attempted_at_utc,
                "status": status,
                "reason_code": reason_code,
                "provider_ref": provider_ref,
                "provider_status_code": provider_status_code,
                "provider_error_text": provider_error_text,
                "provider_accept_only": provider_accept_only,
                "delivery_confidence": delivery_confidence,
                "result_at_utc": result_at_utc,
                "trace_id": trace_id,
                "causation_id": causation_id,
                "source_adapter_attempt_id": source_adapter_attempt_id,
            }
        )


@dataclass
class SqliteStateStore:
    conn: sqlite3.Connection
    on_before_version_guard: Callable[[sqlite3.Connection, Event, int], None] | None = None

    @classmethod
    def from_path(cls, db_path: str) -> "SqliteStateStore":
        conn = bootstrap_database(db_path)
        store = cls(conn)
        store._ensure_system_state_defaults()
        return store

    def _ensure_system_state_defaults(self) -> None:
        now = datetime.now(UTC).isoformat()
        defaults = [
            ("runtime_mode", "enum", "normal"),
            ("idempotency_window_hours", "int", "24"),
            ("max_retry_attempts", "int", "3"),
        ]
        for key, value_type, value in defaults:
            self.conn.execute(
                "INSERT OR IGNORE INTO system_state(key, value_type, value, updated_at_utc) VALUES (?, ?, ?, ?)",
                (key, value_type, value, now),
            )
        self.conn.commit()

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> Event:
        return Event(
            event_id=row["event_id"],
            version=row["version"],
            title=row["title"],
            start_at_local=datetime.fromisoformat(row["start_at_local_iso"]),
            timezone=row["event_timezone"],
            participants=tuple(json.loads(row["participants_json"])),
            audience=tuple(json.loads(row["audience_json"])),
            reminder_offset_minutes=row["reminder_offset_minutes"],
            all_day=bool(row["all_day"]),
            status=row["status"],
            source_message_ref=row["source_message_ref"],
        )

    @staticmethod
    def _reminder_from_row(row: sqlite3.Row) -> Reminder:
        return Reminder(
            reminder_id=row["reminder_id"],
            dedupe_key=row["dedupe_key"],
            event_id=row["event_id"],
            event_version=row["event_version"],
            recipient_id=row["recipient_target_id"],
            trigger_at_utc=datetime.fromisoformat(row["trigger_at_utc"]),
            offset_minutes=row["offset_minutes"],
            status=row["status"],
            attempts=row["attempts"],
            next_attempt_at_utc=datetime.fromisoformat(row["next_attempt_at_utc"])
            if row["next_attempt_at_utc"]
            else None,
        )

    def get_message_receipt(self, channel: str, conversation_id: str, message_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT result_json FROM message_receipts WHERE channel = ? AND conversation_id = ? AND message_id = ?",
            (channel, conversation_id, message_id),
        ).fetchone()
        return json.loads(row["result_json"]) if row else None

    def find_recent_receipt_by_intent_hash(self, intent_hash: str, now_utc: datetime, window_hours: int) -> dict | None:
        lower = (now_utc - timedelta(hours=window_hours)).isoformat()
        row = self.conn.execute(
            """
            SELECT result_json
            FROM message_receipts
            WHERE intent_hash = ? AND created_at_utc >= ?
            ORDER BY created_at_utc DESC
            LIMIT 1
            """,
            (intent_hash, lower),
        ).fetchone()
        return json.loads(row["result_json"]) if row else None

    def save_message_receipt(
        self,
        channel: str,
        conversation_id: str,
        message_id: str,
        correlation_id: str,
        intent_hash: str,
        result: dict,
        created_at_utc: datetime,
    ) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO message_receipts(
                channel, conversation_id, message_id, correlation_id, intent_hash, result_json, created_at_utc
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                channel,
                conversation_id,
                message_id,
                correlation_id,
                intent_hash,
                json.dumps(result, sort_keys=True),
                created_at_utc.isoformat(),
            ),
        )
        self.conn.commit()

    def list_active_events(self) -> tuple[Event, ...]:
        rows = self.conn.execute(
            """
            SELECT ev.*, e.status
            FROM event_versions ev
            JOIN events e ON e.event_id = ev.event_id AND e.current_version = ev.version
            WHERE e.status = 'active'
            ORDER BY ev.event_id
            """
        ).fetchall()
        return tuple(self._event_from_row(row) for row in rows)

    def get_latest_event(self, event_id: str) -> Event | None:
        row = self.conn.execute(
            """
            SELECT ev.*, e.status
            FROM event_versions ev
            JOIN events e ON e.event_id = ev.event_id AND e.current_version = ev.version
            WHERE ev.event_id = ?
            """,
            (event_id,),
        ).fetchone()
        return self._event_from_row(row) if row else None

    def has_event(self, event_id: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM events WHERE event_id = ?", (event_id,)).fetchone()
        return bool(row)

    def next_event_id(self) -> str:
        rows = self.conn.execute("SELECT event_id FROM events").fetchall()
        max_num = 0
        for row in rows:
            event_id = row["event_id"]
            if event_id.startswith("evt-"):
                try:
                    max_num = max(max_num, int(event_id[4:]))
                except ValueError:
                    continue
        return f"evt-{(max_num + 1):04d}"

    def save_new_event(self, event: Event) -> None:
        now = datetime.now(UTC).isoformat()
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self.conn.execute(
                "INSERT INTO events(event_id,current_version,status,created_at_utc,updated_at_utc) "
                "VALUES (?, ?, ?, ?, ?)",
                (event.event_id, event.version, event.status, now, now),
            )
            self.conn.execute(
                """
                INSERT INTO event_versions(
                    event_id,version,title,start_at_local_iso,end_at_local_iso,all_day,event_timezone,
                    participants_json,audience_json,reminder_offset_minutes,source_message_ref,
                    intent_hash,normalized_fields_hash,created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.version,
                    event.title,
                    event.start_at_local.isoformat(),
                    None,
                    int(event.all_day),
                    event.timezone,
                    json.dumps(event.participants),
                    json.dumps(event.audience),
                    event.reminder_offset_minutes,
                    event.source_message_ref,
                    event.source_message_ref,
                    event.source_message_ref,
                    now,
                ),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def append_event_version(self, event: Event) -> None:
        now = datetime.now(UTC).isoformat()
        expected_previous_version = event.version - 1
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            current = self.conn.execute(
                "SELECT current_version FROM events WHERE event_id = ?", (event.event_id,)
            ).fetchone()
            if not current:
                raise RuntimeError(f"missing event: {event.event_id}")

            if self.on_before_version_guard is not None:
                self.on_before_version_guard(self.conn, event, expected_previous_version)

            guard = self.conn.execute(
                """
                UPDATE events
                SET current_version = ?, status = ?, updated_at_utc = ?
                WHERE event_id = ? AND current_version = ?
                """,
                (event.version, event.status, now, event.event_id, expected_previous_version),
            )
            if guard.rowcount != 1:
                raise VersionConflictError(f"VERSION_CONFLICT_RETRY:{event.event_id}:{expected_previous_version}")

            self.conn.execute(
                """
                INSERT INTO event_versions(
                    event_id,version,title,start_at_local_iso,end_at_local_iso,all_day,event_timezone,
                    participants_json,audience_json,reminder_offset_minutes,source_message_ref,
                    intent_hash,normalized_fields_hash,created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.version,
                    event.title,
                    event.start_at_local.isoformat(),
                    None,
                    int(event.all_day),
                    event.timezone,
                    json.dumps(event.participants),
                    json.dumps(event.audience),
                    event.reminder_offset_minutes,
                    event.source_message_ref,
                    event.source_message_ref,
                    event.source_message_ref,
                    now,
                ),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def list_reminders(self) -> tuple[Reminder, ...]:
        rows = self.conn.execute("SELECT * FROM reminders ORDER BY dedupe_key").fetchall()
        return tuple(self._reminder_from_row(row) for row in rows)

    def list_due_reminders(self, now_utc: datetime, limit: int | None = None) -> tuple[Reminder, ...]:
        sql = (
            "SELECT * FROM reminders "
            "WHERE status IN ('scheduled','attempted') "
            "AND COALESCE(next_attempt_at_utc, trigger_at_utc) <= ? "
            "ORDER BY trigger_at_utc ASC, reminder_id ASC"
        )
        params: list[object] = [now_utc.isoformat()]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self.conn.execute(sql, tuple(params)).fetchall()
        return tuple(self._reminder_from_row(row) for row in rows)

    def count_due_reminders(self, now_utc: datetime) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM reminders "
            "WHERE status IN ('scheduled','attempted') "
            "AND COALESCE(next_attempt_at_utc, trigger_at_utc) <= ?",
            (now_utc.isoformat(),),
        ).fetchone()
        return int(row["n"])

    def save_reminder(self, reminder: Reminder) -> None:
        now = datetime.now(UTC).isoformat()
        self.conn.execute(
            """
            INSERT OR REPLACE INTO reminders(
                reminder_id,dedupe_key,event_id,event_version,recipient_target_id,offset_minutes,
                trigger_at_utc,next_attempt_at_utc,attempts,status,recipient_timezone_snapshot,tz_source,
                last_error_code,created_at_utc,updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reminder.reminder_id,
                reminder.dedupe_key,
                reminder.event_id,
                reminder.event_version,
                reminder.recipient_id,
                reminder.offset_minutes,
                reminder.trigger_at_utc.isoformat(),
                reminder.next_attempt_at_utc.isoformat() if reminder.next_attempt_at_utc else None,
                reminder.attempts,
                reminder.status,
                "UNKNOWN",
                "MISSING" if reminder.status == "blocked" else "EXPLICIT",
                "TZ_MISSING" if reminder.status == "blocked" else None,
                now,
                now,
            ),
        )
        self.conn.commit()

    def has_reminder_dedupe(self, dedupe_key: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM reminders WHERE dedupe_key = ?", (dedupe_key,)).fetchone()
        return bool(row)

    def update_reminder(self, reminder: Reminder) -> None:
        self.conn.execute(
            """
            UPDATE reminders
            SET next_attempt_at_utc = ?, attempts = ?, status = ?, updated_at_utc = ?
            WHERE dedupe_key = ?
            """,
            (
                reminder.next_attempt_at_utc.isoformat() if reminder.next_attempt_at_utc else None,
                reminder.attempts,
                reminder.status,
                datetime.now(UTC).isoformat(),
                reminder.dedupe_key,
            ),
        )
        self.conn.commit()

    def save_delivery_target(self, target: DeliveryTarget) -> None:
        _validate_target_ref_width(target.target_id)
        self.conn.execute(
            """
            INSERT OR REPLACE INTO delivery_targets(
                target_id, person_id, channel, target_ref, timezone,
                quiet_hours_start, quiet_hours_end, is_active, updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                target.person_id,
                target.person_id,
                target.channel,
                target.target_id,
                target.timezone,
                target.quiet_hours_start,
                target.quiet_hours_end,
                datetime.now(UTC).isoformat(),
            ),
        )
        self.conn.commit()

    def get_delivery_target(self, person_id: str) -> DeliveryTarget | None:
        row = self.conn.execute("SELECT * FROM delivery_targets WHERE person_id = ?", (person_id,)).fetchone()
        if not row:
            return None
        return DeliveryTarget(
            person_id=row["person_id"],
            channel=row["channel"],
            target_id=row["target_ref"],
            timezone=row["timezone"],
            quiet_hours_start=row["quiet_hours_start"],
            quiet_hours_end=row["quiet_hours_end"],
        )

    def list_delivery_targets(self) -> tuple[DeliveryTarget, ...]:
        rows = self.conn.execute("SELECT * FROM delivery_targets ORDER BY person_id").fetchall()
        return tuple(
            DeliveryTarget(
                person_id=row["person_id"],
                channel=row["channel"],
                target_id=row["target_ref"],
                timezone=row["timezone"],
                quiet_hours_start=row["quiet_hours_start"],
                quiet_hours_end=row["quiet_hours_end"],
            )
            for row in rows
        )

    def append_audit(self, row: AuditRecord) -> None:
        self.conn.execute(
            """
            INSERT INTO audit_log(
                ts_utc, trace_id, causation_id, correlation_id, message_id,
                entity_type, entity_id, stage, reason_code, payload_schema_version, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(UTC).isoformat(),
                row.correlation_id,
                row.message_id,
                row.correlation_id,
                row.message_id,
                "event",
                row.message_id,
                row.stage,
                row.reason_code.value,
                1,
                json.dumps({"payload": row.payload}),
            ),
        )
        self.conn.commit()

    def list_audit(self) -> tuple[AuditRecord, ...]:
        rows = self.conn.execute("SELECT * FROM audit_log ORDER BY audit_index").fetchall()
        output = []
        for idx, row in enumerate(rows, start=1):
            payload = json.loads(row["payload_json"]).get("payload", "")

            output.append(
                AuditRecord(
                    index=idx,
                    correlation_id=row["correlation_id"],
                    message_id=row["message_id"],
                    stage=row["stage"],
                    reason_code=ReasonCode(row["reason_code"]),
                    payload=payload,
                )
            )
        return tuple(output)

    def get_runtime_mode(self) -> str:
        row = self.conn.execute("SELECT value FROM system_state WHERE key='runtime_mode'").fetchone()
        return row["value"] if row else "normal"

    def set_runtime_mode(self, mode: str) -> None:
        self.conn.execute(
            "UPDATE system_state SET value = ?, updated_at_utc = ? WHERE key = 'runtime_mode'",
            (mode, datetime.now(UTC).isoformat()),
        )
        self.conn.commit()

    def get_idempotency_window_hours(self) -> int:
        row = self.conn.execute("SELECT value FROM system_state WHERE key='idempotency_window_hours'").fetchone()
        return int(row["value"]) if row else 24

    def get_max_retry_attempts(self) -> int:
        row = self.conn.execute("SELECT value FROM system_state WHERE key='max_retry_attempts'").fetchone()
        return int(row["value"]) if row else 3

    def append_delivery_attempt(
        self,
        *,
        attempt_id: str,
        reminder_id: str,
        attempt_index: int,
        attempted_at_utc: datetime,
        status: str,
        reason_code: str,
        provider_ref: str | None,
        provider_status_code: str | None,
        provider_error_text: str | None,
        provider_accept_only: bool,
        delivery_confidence: str,
        result_at_utc: datetime,
        trace_id: str,
        causation_id: str,
        source_adapter_attempt_id: str | None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO delivery_attempts(
                attempt_id, reminder_id, attempt_index, attempted_at_utc, status, reason_code,
                provider_ref, provider_status_code, provider_error_text, provider_accept_only,
                delivery_confidence, result_at_utc, trace_id, causation_id, source_adapter_attempt_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt_id,
                reminder_id,
                attempt_index,
                attempted_at_utc.isoformat(),
                status,
                reason_code,
                provider_ref,
                provider_status_code,
                provider_error_text,
                int(provider_accept_only),
                delivery_confidence,
                result_at_utc.isoformat(),
                trace_id,
                causation_id,
                source_adapter_attempt_id,
            ),
        )
        self.conn.commit()
