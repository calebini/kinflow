from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from ..models import AuditRecord, DeliveryTarget, Event, Reminder
from .db import bootstrap_database


class StateStore(Protocol):
    def get_message_receipt(self, message_id: str) -> dict | None: ...

    def save_message_receipt(self, message_id: str, result: dict) -> None: ...

    def list_active_events(self) -> tuple[Event, ...]: ...

    def get_latest_event(self, event_id: str) -> Event | None: ...

    def has_event(self, event_id: str) -> bool: ...

    def next_event_id(self) -> str: ...

    def save_new_event(self, event: Event) -> None: ...

    def append_event_version(self, event: Event) -> None: ...

    def list_reminders(self) -> tuple[Reminder, ...]: ...

    def save_reminder(self, reminder: Reminder) -> None: ...

    def has_reminder_dedupe(self, dedupe_key: str) -> bool: ...

    def update_reminder(self, reminder: Reminder) -> None: ...

    def save_delivery_target(self, target: DeliveryTarget) -> None: ...

    def get_delivery_target(self, person_id: str) -> DeliveryTarget | None: ...

    def list_delivery_targets(self) -> tuple[DeliveryTarget, ...]: ...

    def append_audit(self, row: AuditRecord) -> None: ...

    def list_audit(self) -> tuple[AuditRecord, ...]: ...


class InMemoryStateStore:
    def __init__(self) -> None:
        self.event_versions: dict[str, list[Event]] = {}
        self.reminders: dict[str, Reminder] = {}
        self.delivery_targets: dict[str, DeliveryTarget] = {}
        self.audit: list[AuditRecord] = []
        self.receipts: dict[str, dict] = {}
        self.event_counter = 0

    def get_message_receipt(self, message_id: str) -> dict | None:
        return self.receipts.get(message_id)

    def save_message_receipt(self, message_id: str, result: dict) -> None:
        self.receipts[message_id] = result

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

    def save_reminder(self, reminder: Reminder) -> None:
        self.reminders[reminder.dedupe_key] = reminder

    def has_reminder_dedupe(self, dedupe_key: str) -> bool:
        return dedupe_key in self.reminders

    def update_reminder(self, reminder: Reminder) -> None:
        self.reminders[reminder.dedupe_key] = reminder

    def save_delivery_target(self, target: DeliveryTarget) -> None:
        self.delivery_targets[target.person_id] = target

    def get_delivery_target(self, person_id: str) -> DeliveryTarget | None:
        return self.delivery_targets.get(person_id)

    def list_delivery_targets(self) -> tuple[DeliveryTarget, ...]:
        return tuple(self.delivery_targets.values())

    def append_audit(self, row: AuditRecord) -> None:
        self.audit.append(row)

    def list_audit(self) -> tuple[AuditRecord, ...]:
        return tuple(self.audit)


@dataclass
class SqliteStateStore:
    conn: sqlite3.Connection

    @classmethod
    def from_path(cls, db_path: str) -> "SqliteStateStore":
        conn = bootstrap_database(db_path)
        return cls(conn)

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
            next_attempt_at_utc=datetime.fromisoformat(row["next_attempt_at_utc"]) if row["next_attempt_at_utc"] else None,
        )

    def get_message_receipt(self, message_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT result_json FROM message_receipts WHERE channel = ? AND conversation_id = ? AND message_id = ?",
            ("engine", "default", message_id),
        ).fetchone()
        return json.loads(row["result_json"]) if row else None

    def save_message_receipt(self, message_id: str, result: dict) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO message_receipts(channel, conversation_id, message_id, correlation_id, intent_hash, result_json, created_at_utc)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "engine",
                "default",
                message_id,
                f"corr:{message_id}",
                message_id,
                json.dumps(result, sort_keys=True),
                datetime.now(UTC).isoformat(),
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
                "INSERT INTO events(event_id,current_version,status,created_at_utc,updated_at_utc) VALUES (?, ?, ?, ?, ?)",
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
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            current = self.conn.execute("SELECT current_version FROM events WHERE event_id = ?", (event.event_id,)).fetchone()
            if not current:
                raise RuntimeError(f"missing event: {event.event_id}")
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
            self.conn.execute(
                "UPDATE events SET current_version = ?, status = ?, updated_at_utc = ? WHERE event_id = ?",
                (event.version, event.status, now, event.event_id),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def list_reminders(self) -> tuple[Reminder, ...]:
        rows = self.conn.execute("SELECT * FROM reminders ORDER BY dedupe_key").fetchall()
        return tuple(self._reminder_from_row(row) for row in rows)

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
        self.conn.execute(
            """
            INSERT OR REPLACE INTO delivery_targets(
                target_id, person_id, channel, target_ref, timezone, quiet_hours_start, quiet_hours_end, is_active, updated_at_utc
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
            from ..reason_codes import ReasonCode

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
