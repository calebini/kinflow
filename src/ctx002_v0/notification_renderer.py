from __future__ import annotations

import re
from dataclasses import dataclass

RENDERER_VERSION = "KINFLOW_NOTIFICATION_RENDERING_MIN_SPEC_v0.5.3"
FALLBACK_REASON_CODE = "RENDER_FALLBACK_USED"


@dataclass(frozen=True)
class RenderResult:
    message: str
    fallback_used: bool
    reason_code: str | None


def _sanitize_whitespace(value: str) -> str:
    # Replace control/newline/tab with spaces then collapse runs.
    cleaned = "".join(" " if (ord(ch) < 32 or ch == "\x7f") else ch for ch in value)
    return " ".join(cleaned.strip().split())


def _safe_id(value: object, *, fallback: str) -> str:
    try:
        text = _sanitize_whitespace(str(value))
        return text if text else fallback
    except Exception:
        return fallback


def _fallback(event_id: object, reminder_id: object) -> RenderResult:
    safe_event_id = _safe_id(event_id, fallback="unknown-event")
    safe_reminder_id = _safe_id(reminder_id, fallback="unknown-reminder")
    return RenderResult(
        message=f"[KINFLOW] Reminder {safe_event_id} ({safe_reminder_id})",
        fallback_used=True,
        reason_code=FALLBACK_REASON_CODE,
    )


def render_reminder_text(payload: dict[str, object]) -> RenderResult:
    try:
        event_id_raw = payload.get("event_id", "")
        reminder_id_raw = payload.get("reminder_id", "")
        title_raw = payload.get("title_display", "")
        time_raw = payload.get("display_time_hhmm", "")
        tz_raw = payload.get("display_tz_label", "")

        event_id = _safe_id(event_id_raw, fallback="")
        reminder_id = _safe_id(reminder_id_raw, fallback="")
        if not event_id or not reminder_id:
            return _fallback(event_id_raw, reminder_id_raw)

        title = _sanitize_whitespace(str(title_raw))
        if not title:
            return _fallback(event_id, reminder_id)
        # max 120 total characters including ellipsis.
        if len(title) > 120:
            title = title[:119] + "…"

        time_text = _sanitize_whitespace(str(time_raw))
        if not re.fullmatch(r"\d{2}:\d{2}", time_text):
            return _fallback(event_id, reminder_id)
        hour = int(time_text[:2])
        minute = int(time_text[3:5])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return _fallback(event_id, reminder_id)

        tz_label = _sanitize_whitespace(str(tz_raw))
        if not tz_label or len(tz_label) > 64:
            return _fallback(event_id, reminder_id)

        message = f"🔔 Reminder: {title} at {time_text} ({tz_label})"
        return RenderResult(message=message, fallback_used=False, reason_code=None)
    except Exception:
        return _fallback(payload.get("event_id", "unknown-event"), payload.get("reminder_id", "unknown-reminder"))
