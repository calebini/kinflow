from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from .reason_codes import ReasonCode

ReminderStatus = Literal[
    "scheduled",
    "attempted",
    "delivered",
    "failed",
    "suppressed",
    "invalidated",
    "blocked",
]


@dataclass(frozen=True)
class DeliveryTarget:
    person_id: str
    channel: str
    target_id: str
    timezone: str | None
    quiet_hours_start: int = 22
    quiet_hours_end: int = 7


@dataclass
class Event:
    event_id: str
    version: int
    title: str
    start_at_local: datetime
    timezone: str
    participants: tuple[str, ...]
    audience: tuple[str, ...]
    reminder_offset_minutes: int
    all_day: bool = False
    status: str = "active"
    source_message_ref: str = ""


@dataclass
class Reminder:
    reminder_id: str
    dedupe_key: str
    event_id: str
    event_version: int
    recipient_id: str
    trigger_at_utc: datetime
    offset_minutes: int
    status: ReminderStatus
    attempts: int = 0
    next_attempt_at_utc: datetime | None = None


@dataclass(frozen=True)
class AuditRecord:
    index: int
    correlation_id: str
    message_id: str
    stage: str
    reason_code: ReasonCode
    payload: str
