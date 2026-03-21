from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Callable
from zoneinfo import ZoneInfo

from .models import AuditRecord, DeliveryTarget, Event, Reminder
from .persistence.store import InMemoryStateStore, SqliteStateStore, StateStore
from .reason_codes import ReasonCode

ProviderFn = Callable[[Reminder], bool]


class FamilySchedulerV0:
    """Deterministic v0 core for CTX-002."""

    def __init__(
        self,
        *,
        household_timezone: str = "UTC",
        event_fallback_timezone: str = "UTC",
        similarity_threshold: float = 0.8,
        max_retries: int = 2,
        retry_delay_minutes: int = 5,
        db_path: str | None = None,
        state_store: StateStore | None = None,
    ) -> None:
        self.household_timezone = household_timezone
        self.event_fallback_timezone = event_fallback_timezone
        self.similarity_threshold = similarity_threshold
        self.max_retries = max_retries
        self.retry_delay_minutes = retry_delay_minutes

        if state_store is not None:
            self._store = state_store
        elif db_path:
            self._store = SqliteStateStore.from_path(db_path)
        else:
            self._store = InMemoryStateStore()

        self._visible_delivery_keys: set[str] = set()

    @property
    def _event_versions(self) -> dict[str, list[Event]]:
        if isinstance(self._store, InMemoryStateStore):
            return self._store.event_versions
        raise AttributeError("_event_versions only available for in-memory store")

    @property
    def audit(self) -> tuple[AuditRecord, ...]:
        return self._store.list_audit()

    @property
    def reminders(self) -> tuple[Reminder, ...]:
        return self._store.list_reminders()

    @property
    def active_events(self) -> tuple[Event, ...]:
        return self._store.list_active_events()

    def register_delivery_target(self, target: DeliveryTarget) -> None:
        self._store.save_delivery_target(target)

    def process_intent(self, intent: dict) -> dict:
        message_id = intent["message_id"]
        correlation_id = intent.get("correlation_id") or f"corr:{message_id}"

        existing = self._store.get_message_receipt(message_id)
        if existing is not None:
            return existing

        self._append_audit(correlation_id, message_id, "intake", ReasonCode.RESOLVER_NO_MATCH, "INTAKE")

        missing = self._missing_required_fields(intent)
        if missing:
            result = {
                "status": "needs_follow_up",
                "missing_fields": missing,
                "persisted": False,
            }
            self._store.save_message_receipt(message_id, result)
            return result

        resolved_event_id, resolver_code = self._resolve_event(intent)
        self._append_audit(correlation_id, message_id, "resolver", resolver_code, resolved_event_id or "none")

        if resolver_code == ReasonCode.RESOLVER_AMBIGUOUS:
            result = {
                "status": "ambiguous",
                "persisted": False,
                "reason_code": resolver_code.value,
            }
            self._store.save_message_receipt(message_id, result)
            return result

        if not intent.get("confirmed", False):
            self._append_audit(
                correlation_id,
                message_id,
                "confirmation",
                ReasonCode.BLOCKED_CONFIRMATION_REQUIRED,
                "confirmation missing",
            )
            result = {
                "status": "blocked",
                "persisted": False,
                "reason_code": ReasonCode.BLOCKED_CONFIRMATION_REQUIRED.value,
            }
            self._store.save_message_receipt(message_id, result)
            return result

        action = intent.get("action", "create")
        now_utc = intent.get("received_at_utc") or datetime.now(UTC)
        if action == "cancel":
            event = self._cancel_event(resolved_event_id, intent, now_utc)
        elif resolved_event_id and action in {"update", "create"}:
            event = self._update_event(resolved_event_id, intent, now_utc)
        else:
            event = self._create_event(intent)

        result = {
            "status": "ok",
            "persisted": True,
            "event_id": event.event_id,
            "event_version": event.version,
            "reason_code": resolver_code.value,
        }
        self._store.save_message_receipt(message_id, result)
        return result

    def attempt_due_deliveries(self, now_utc: datetime, provider: ProviderFn) -> list[tuple[str, ReasonCode]]:
        outcomes: list[tuple[str, ReasonCode]] = []
        reminders = list(self.reminders)
        for reminder in reminders:
            if reminder.status not in {"scheduled", "attempted"}:
                continue
            due = reminder.next_attempt_at_utc or reminder.trigger_at_utc
            if due > now_utc:
                continue

            target = self._store.get_delivery_target(reminder.recipient_id)
            if target is None or target.timezone is None:
                reminder.status = "blocked"
                self._store.update_reminder(reminder)
                outcomes.append((reminder.dedupe_key, ReasonCode.TZ_MISSING))
                self._append_audit("delivery", reminder.reminder_id, "delivery", ReasonCode.TZ_MISSING, reminder.dedupe_key)
                continue

            local_hour = now_utc.astimezone(ZoneInfo(target.timezone)).hour
            if self._is_quiet_hour(local_hour, target.quiet_hours_start, target.quiet_hours_end):
                reminder.status = "suppressed"
                self._store.update_reminder(reminder)
                outcomes.append((reminder.dedupe_key, ReasonCode.SUPPRESSED_QUIET_HOURS))
                self._append_audit(
                    "delivery",
                    reminder.reminder_id,
                    "delivery",
                    ReasonCode.SUPPRESSED_QUIET_HOURS,
                    reminder.dedupe_key,
                )
                continue

            reminder.status = "attempted"
            reminder.attempts += 1
            delivery_key = reminder.dedupe_key
            self._store.update_reminder(reminder)
            if delivery_key in self._visible_delivery_keys:
                continue

            ok = provider(reminder)
            if ok:
                reminder.status = "delivered"
                self._store.update_reminder(reminder)
                self._visible_delivery_keys.add(delivery_key)
                outcomes.append((delivery_key, ReasonCode.DELIVERED))
                self._append_audit("delivery", reminder.reminder_id, "delivery", ReasonCode.DELIVERED, delivery_key)
                continue

            self._append_audit("delivery", reminder.reminder_id, "delivery", ReasonCode.FAILED_PROVIDER, delivery_key)
            if reminder.attempts > self.max_retries:
                reminder.status = "failed"
                self._store.update_reminder(reminder)
                outcomes.append((delivery_key, ReasonCode.FAILED_RETRY_EXHAUSTED))
                self._append_audit(
                    "delivery",
                    reminder.reminder_id,
                    "delivery",
                    ReasonCode.FAILED_RETRY_EXHAUSTED,
                    delivery_key,
                )
            else:
                reminder.next_attempt_at_utc = now_utc + timedelta(minutes=self.retry_delay_minutes)
                self._store.update_reminder(reminder)
                outcomes.append((delivery_key, ReasonCode.FAILED_PROVIDER))
        return outcomes

    def generate_daily_brief(self, now_utc: datetime, recipient_id: str) -> dict:
        target = self._store.get_delivery_target(recipient_id)
        if target is None:
            raise KeyError(recipient_id)
        tz = ZoneInfo(target.timezone or self.household_timezone)
        local_day = now_utc.astimezone(tz).date()

        today = []
        upcoming = []
        for event in self.active_events:
            local_start = event.start_at_local.astimezone(ZoneInfo(event.timezone)).astimezone(tz)
            bucket = today if local_start.date() == local_day else upcoming
            if recipient_id in event.audience:
                bucket.append({"event_id": event.event_id, "title": event.title, "local_start": local_start.isoformat()})

        return {
            "today": sorted(today, key=lambda row: row["local_start"]),
            "upcoming": sorted(upcoming, key=lambda row: row["local_start"]),
            "conflicts": self._find_conflicts(today),
            "action_items": ["confirm changes before save"],
        }

    def deterministic_snapshot(self) -> dict:
        return {
            "events": [asdict(event) for event in self.active_events],
            "reminders": [asdict(reminder) for reminder in self.reminders],
            "audit": [
                {
                    "index": row.index,
                    "corr": row.correlation_id,
                    "msg": row.message_id,
                    "stage": row.stage,
                    "reason": row.reason_code.value,
                    "payload": row.payload,
                }
                for row in self.audit
            ],
        }

    def deterministic_hash(self) -> str:
        payload = str(self.deterministic_snapshot()).encode("utf-8")
        return sha256(payload).hexdigest()

    def _create_event(self, intent: dict) -> Event:
        tz_name, tz_reason = self._resolve_event_timezone(intent)
        self._append_audit(intent["message_id"], intent["message_id"], "timezone", tz_reason, tz_name)
        event_id = self._store.next_event_id()
        event = Event(
            event_id=event_id,
            version=1,
            title=intent["title"],
            start_at_local=intent["start_at_local"],
            timezone=tz_name,
            participants=tuple(sorted(intent["participants"])),
            audience=tuple(sorted(intent["audience"])),
            reminder_offset_minutes=intent["reminder_offset_minutes"],
            all_day=bool(intent.get("all_day", False)),
            source_message_ref=intent["message_id"],
        )
        self._store.save_new_event(event)
        self._schedule_reminders(event)
        return event

    def _update_event(self, event_id: str, intent: dict, now_utc: datetime) -> Event:
        current = self._store.get_latest_event(event_id)
        if current is None:
            raise ValueError(f"missing event: {event_id}")
        tz_name, tz_reason = self._resolve_event_timezone(intent, current.timezone)
        self._append_audit(intent["message_id"], intent["message_id"], "timezone", tz_reason, tz_name)
        updated = Event(
            event_id=event_id,
            version=current.version + 1,
            title=intent.get("title", current.title),
            start_at_local=intent.get("start_at_local", current.start_at_local),
            timezone=tz_name,
            participants=tuple(sorted(intent.get("participants", current.participants))),
            audience=tuple(sorted(intent.get("audience", current.audience))),
            reminder_offset_minutes=intent.get("reminder_offset_minutes", current.reminder_offset_minutes),
            all_day=bool(intent.get("all_day", current.all_day)),
            status="active",
            source_message_ref=intent["message_id"],
        )
        self._store.append_event_version(updated)
        self._invalidate_prior_version_reminders(event_id, updated.version, now_utc, ReasonCode.UPDATED_REGENERATED)
        self._schedule_reminders(updated)
        return updated

    def _cancel_event(self, event_id: str | None, intent: dict, now_utc: datetime) -> Event:
        if event_id is None:
            raise ValueError("cancel requires an event")
        current = self._store.get_latest_event(event_id)
        if current is None:
            raise ValueError(f"missing event: {event_id}")
        cancelled = Event(
            event_id=current.event_id,
            version=current.version + 1,
            title=current.title,
            start_at_local=current.start_at_local,
            timezone=current.timezone,
            participants=current.participants,
            audience=current.audience,
            reminder_offset_minutes=current.reminder_offset_minutes,
            all_day=current.all_day,
            status="cancelled",
            source_message_ref=intent["message_id"],
        )
        self._store.append_event_version(cancelled)
        self._invalidate_prior_version_reminders(event_id, cancelled.version, now_utc, ReasonCode.CANCEL_INVALIDATED)
        return cancelled

    def _resolve_event(self, intent: dict) -> tuple[str | None, ReasonCode]:
        explicit_id = intent.get("event_id")
        if explicit_id and self._store.has_event(explicit_id):
            return explicit_id, ReasonCode.RESOLVER_EXPLICIT

        candidates: list[tuple[str, float]] = []
        for event in self.active_events:
            score = 0.0
            if intent.get("title") == event.title:
                score += 0.5
            if intent.get("start_at_local") == event.start_at_local:
                score += 0.3
            if set(intent.get("participants", ())) == set(event.participants):
                score += 0.2
            if score >= self.similarity_threshold:
                candidates.append((event.event_id, score))

        if len(candidates) == 1:
            return candidates[0][0], ReasonCode.RESOLVER_MATCHED

        if len(candidates) > 1:
            top = max(score for _, score in candidates)
            top_count = sum(1 for _, score in candidates if score == top)
            if top_count >= 1:
                return None, ReasonCode.RESOLVER_AMBIGUOUS

        return None, ReasonCode.RESOLVER_NO_MATCH

    def _schedule_reminders(self, event: Event) -> None:
        event_tz = ZoneInfo(event.timezone)
        start_utc = event.start_at_local.replace(tzinfo=event_tz).astimezone(UTC)
        trigger = start_utc - timedelta(minutes=event.reminder_offset_minutes)

        for recipient_id in event.audience:
            target = self._store.get_delivery_target(recipient_id)
            reminder_id = f"rem-{event.event_id}-v{event.version}-{recipient_id}-{event.reminder_offset_minutes}"
            dedupe_key = f"{event.event_id}:{event.version}:{recipient_id}:{event.reminder_offset_minutes}:{trigger.isoformat()}"

            if target is None or target.timezone is None:
                reminder = Reminder(
                    reminder_id=reminder_id,
                    dedupe_key=dedupe_key,
                    event_id=event.event_id,
                    event_version=event.version,
                    recipient_id=recipient_id,
                    trigger_at_utc=trigger,
                    offset_minutes=event.reminder_offset_minutes,
                    status="blocked",
                )
                self._store.save_reminder(reminder)
                self._append_audit("scheduler", reminder_id, "schedule", ReasonCode.TZ_MISSING, dedupe_key)
                continue

            if self._store.has_reminder_dedupe(dedupe_key):
                continue

            reminder = Reminder(
                reminder_id=reminder_id,
                dedupe_key=dedupe_key,
                event_id=event.event_id,
                event_version=event.version,
                recipient_id=recipient_id,
                trigger_at_utc=trigger,
                offset_minutes=event.reminder_offset_minutes,
                status="scheduled",
            )
            self._store.save_reminder(reminder)

    def _resolve_event_timezone(self, intent: dict, existing: str | None = None) -> tuple[str, ReasonCode]:
        if intent.get("event_timezone"):
            return intent["event_timezone"], ReasonCode.TZ_EXPLICIT
        if existing:
            return existing, ReasonCode.TZ_HOUSEHOLD_DEFAULT
        if self.household_timezone:
            return self.household_timezone, ReasonCode.TZ_HOUSEHOLD_DEFAULT
        return self.event_fallback_timezone, ReasonCode.TZ_FALLBACK_USED

    def _invalidate_prior_version_reminders(
        self,
        event_id: str,
        new_version: int,
        now_utc: datetime,
        reason: ReasonCode,
    ) -> None:
        for reminder in self.reminders:
            if reminder.event_id != event_id:
                continue
            if reminder.event_version >= new_version:
                continue
            if reminder.trigger_at_utc <= now_utc:
                continue
            if reminder.status in {"invalidated", "delivered", "failed", "suppressed", "blocked"}:
                continue
            reminder.status = "invalidated"
            self._store.update_reminder(reminder)
            self._append_audit("mutation", reminder.reminder_id, "mutation", reason, reminder.dedupe_key)

    @staticmethod
    def _is_quiet_hour(hour: int, start: int, end: int) -> bool:
        if start < end:
            return start <= hour < end
        return hour >= start or hour < end

    def _append_audit(
        self,
        correlation_id: str,
        message_id: str,
        stage: str,
        reason_code: ReasonCode,
        payload: str,
    ) -> None:
        self._store.append_audit(
            AuditRecord(
                index=len(self.audit) + 1,
                correlation_id=correlation_id,
                message_id=message_id,
                stage=stage,
                reason_code=reason_code,
                payload=payload,
            )
        )

    @staticmethod
    def _find_conflicts(events: list[dict]) -> list[tuple[str, str]]:
        conflicts: list[tuple[str, str]] = []
        for i in range(len(events)):
            for j in range(i + 1, len(events)):
                if events[i]["local_start"] == events[j]["local_start"]:
                    conflicts.append((events[i]["event_id"], events[j]["event_id"]))
        return conflicts

    @staticmethod
    def _missing_required_fields(intent: dict) -> list[str]:
        if intent.get("action") == "cancel":
            return []
        missing = []
        if not intent.get("start_at_local") and not intent.get("all_day"):
            missing.append("date_time_or_all_day")
        if not intent.get("participants") and not intent.get("audience"):
            missing.append("audience_participants")
        if intent.get("reminder_offset_minutes") is None:
            missing.append("reminder_preference")
        return missing
