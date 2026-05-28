from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from .reason_codes import ReasonCode

TARGET_REF_MAX_LENGTH = 256
ALLOWED_DESTINATION_CHANNELS = ("discord", "signal", "telegram", "whatsapp", "openclaw_auto")

DESTINATION_SOURCE_EVENT_OVERRIDE = "event_override"
DESTINATION_SOURCE_REQUEST_CONTEXT_DEFAULT = "request_context_default"
DESTINATION_SOURCE_RECIPIENT_DEFAULT = "recipient_default"
DESTINATION_SOURCE_NONE = "none"

DESTINATION_RESOLUTION_STATUS_OK = "ok"
DESTINATION_RESOLUTION_STATUS_INVALID = "invalid"
DESTINATION_RESOLUTION_STATUS_MISSING = "missing"

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
    event_override_channel: str | None = None
    event_override_target_ref: str | None = None
    request_context_default_channel: str | None = None
    request_context_default_target_ref: str | None = None


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
    event_override_channel: str | None = None
    event_override_target_ref: str | None = None
    request_context_default_channel: str | None = None
    request_context_default_target_ref: str | None = None


@dataclass(frozen=True)
class AuditRecord:
    index: int
    correlation_id: str
    message_id: str
    stage: str
    reason_code: ReasonCode
    payload: str
