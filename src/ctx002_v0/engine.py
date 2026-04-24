from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .models import ALLOWED_DESTINATION_CHANNELS, TARGET_REF_MAX_LENGTH, AuditRecord, DeliveryTarget, Event, Reminder
from .persistence.store import InMemoryStateStore, SqliteStateStore, StateStore, VersionConflictError
from .reason_codes import ReasonCode

ProviderResult = bool | dict[str, Any]
ProviderFn = Callable[[Reminder], ProviderResult]


class DestinationValidationError(ValueError):
    reason_code = ReasonCode.FAILED_CONFIG_INVALID_TARGET


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

    def set_runtime_mode(self, mode: str) -> None:
        self._store.set_runtime_mode(mode)

    @staticmethod
    def _normalize_optional_string(value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            value = str(value)
        trimmed = value.strip()
        return trimmed or None

    @staticmethod
    def _has_control_characters(value: str) -> bool:
        return any(ord(ch) < 32 or ord(ch) == 127 for ch in value)

    @classmethod
    def _validate_destination_tuple(cls, channel: str | None, target_ref: str | None, *, prefix: str) -> tuple[str | None, str | None]:
        if channel is None and target_ref is None:
            return None, None
        if channel is None or target_ref is None:
            raise DestinationValidationError(f"{prefix} must provide both channel and target_ref")
        if channel not in ALLOWED_DESTINATION_CHANNELS:
            raise DestinationValidationError(f"{prefix} channel is not in allowed enum")
        if len(target_ref) > TARGET_REF_MAX_LENGTH:
            raise DestinationValidationError(f"{prefix} target_ref exceeds {TARGET_REF_MAX_LENGTH}")
        if cls._has_control_characters(target_ref):
            raise DestinationValidationError(f"{prefix} target_ref contains control characters")
        return channel, target_ref

    def _resolve_event_destination_fields(
        self,
        intent: dict,
        *,
        current_event: Event | None,
    ) -> tuple[str | None, str | None, str | None, str | None]:
        def _resolve(prefix: str, current_channel: str | None, current_target: str | None) -> tuple[str | None, str | None]:
            channel_key = f"{prefix}_channel"
            target_key = f"{prefix}_target_ref"
            has_channel = channel_key in intent
            has_target = target_key in intent

            if has_channel != has_target:
                raise DestinationValidationError(f"{prefix} update must include both channel and target_ref")

            if not has_channel and not has_target:
                return current_channel, current_target

            raw_channel = self._normalize_optional_string(intent.get(channel_key))
            raw_target = self._normalize_optional_string(intent.get(target_key))
            return self._validate_destination_tuple(raw_channel, raw_target, prefix=prefix)

        event_override_channel, event_override_target_ref = _resolve(
            "event_override",
            current_event.event_override_channel if current_event else None,
            current_event.event_override_target_ref if current_event else None,
        )
        request_context_default_channel, request_context_default_target_ref = _resolve(
            "request_context_default",
            current_event.request_context_default_channel if current_event else None,
            current_event.request_context_default_target_ref if current_event else None,
        )
        return (
            event_override_channel,
            event_override_target_ref,
            request_context_default_channel,
            request_context_default_target_ref,
        )

    def process_intent(self, intent: dict) -> dict:
        message_id = intent["message_id"]
        correlation_id = intent.get("correlation_id") or f"corr:{message_id}"
        now_utc = intent.get("received_at_utc") or datetime.now(UTC)
        channel = intent.get("channel", "engine")
        conversation_id = intent.get("conversation_id", "default")
        intent_hash = intent.get("intent_hash") or self._intent_hash(intent)

        existing = self._store.get_message_receipt(channel, conversation_id, message_id)
        if existing is not None:
            return existing

        window_hours = self._store.get_idempotency_window_hours()
        replay = self._store.find_recent_receipt_by_intent_hash(intent_hash, now_utc, window_hours)
        if replay is not None:
            self._store.save_message_receipt(
                channel,
                conversation_id,
                message_id,
                correlation_id,
                intent_hash,
                replay,
                now_utc,
            )
            return replay

        self._append_audit(correlation_id, message_id, "intake", ReasonCode.RESOLVER_NO_MATCH, "INTAKE")

        missing = self._missing_required_fields(intent)
        if missing:
            result = {
                "status": "needs_follow_up",
                "missing_fields": missing,
                "persisted": False,
            }
            self._store.save_message_receipt(
                channel,
                conversation_id,
                message_id,
                correlation_id,
                intent_hash,
                result,
                now_utc,
            )
            return result

        resolved_event_id, resolver_code = self._resolve_event(intent)
        self._append_audit(correlation_id, message_id, "resolver", resolver_code, resolved_event_id or "none")

        if resolver_code == ReasonCode.RESOLVER_AMBIGUOUS:
            result = {
                "status": "ambiguous",
                "persisted": False,
                "reason_code": resolver_code.value,
            }
            self._store.save_message_receipt(
                channel,
                conversation_id,
                message_id,
                correlation_id,
                intent_hash,
                result,
                now_utc,
            )
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
            self._store.save_message_receipt(
                channel,
                conversation_id,
                message_id,
                correlation_id,
                intent_hash,
                result,
                now_utc,
            )
            return result

        action = intent.get("action", "create")
        try:
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
        except DestinationValidationError as exc:
            self._append_audit(
                correlation_id,
                message_id,
                "mutation",
                ReasonCode.FAILED_CONFIG_INVALID_TARGET,
                str(exc),
            )
            result = {
                "status": "blocked",
                "persisted": False,
                "event_id": resolved_event_id,
                "reason_code": ReasonCode.FAILED_CONFIG_INVALID_TARGET.value,
            }
        except VersionConflictError:
            self._append_audit(
                correlation_id, message_id, "mutation", ReasonCode.VERSION_CONFLICT_RETRY, resolved_event_id or "none"
            )
            result = {
                "status": "conflict",
                "persisted": False,
                "event_id": resolved_event_id,
                "reason_code": ReasonCode.VERSION_CONFLICT_RETRY.value,
            }
        self._store.save_message_receipt(
            channel,
            conversation_id,
            message_id,
            correlation_id,
            intent_hash,
            result,
            now_utc,
        )
        return result

    def attempt_due_deliveries(self, now_utc: datetime, provider: ProviderFn) -> list[tuple[str, ReasonCode]]:
        if self._store.get_runtime_mode() == "capture_only":
            self._append_audit(
                "system", "capture_only", "delivery", ReasonCode.CAPTURE_ONLY_BLOCKED, "delivery blocked"
            )
            return [("capture_only", ReasonCode.CAPTURE_ONLY_BLOCKED)]

        outcomes: list[tuple[str, ReasonCode]] = []
        for reminder in self._store.list_due_reminders(now_utc):
            target = self._store.get_delivery_target(reminder.recipient_id)
            if target is None or target.timezone is None:
                reminder.status = "blocked"
                self._store.update_reminder(reminder)
                self._store.append_delivery_attempt(
                    attempt_id=f"att-{reminder.reminder_id}-{reminder.attempts + 1}",
                    reminder_id=reminder.reminder_id,
                    attempt_index=reminder.attempts + 1,
                    attempted_at_utc=now_utc,
                    status="blocked",
                    reason_code=ReasonCode.TZ_MISSING.value,
                    provider_ref=None,
                    provider_status_code=None,
                    provider_error_text="timezone missing",
                    provider_accept_only=False,
                    delivery_confidence="none",
                    result_at_utc=now_utc,
                    trace_id="delivery",
                    causation_id=reminder.reminder_id,
                    source_adapter_attempt_id=None,
                )
                outcomes.append((reminder.dedupe_key, ReasonCode.TZ_MISSING))
                self._append_audit(
                    "delivery", reminder.reminder_id, "delivery", ReasonCode.TZ_MISSING, reminder.dedupe_key
                )
                continue

            local_hour = now_utc.astimezone(ZoneInfo(target.timezone)).hour
            if self._is_quiet_hour(local_hour, target.quiet_hours_start, target.quiet_hours_end):
                reminder.status = "suppressed"
                self._store.update_reminder(reminder)
                self._store.append_delivery_attempt(
                    attempt_id=f"att-{reminder.reminder_id}-{reminder.attempts + 1}",
                    reminder_id=reminder.reminder_id,
                    attempt_index=reminder.attempts + 1,
                    attempted_at_utc=now_utc,
                    status="suppressed",
                    reason_code=ReasonCode.SUPPRESSED_QUIET_HOURS.value,
                    provider_ref=None,
                    provider_status_code=None,
                    provider_error_text="quiet_hours",
                    provider_accept_only=False,
                    delivery_confidence="none",
                    result_at_utc=now_utc,
                    trace_id="delivery",
                    causation_id=reminder.reminder_id,
                    source_adapter_attempt_id=None,
                )
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

            provider_result = provider(reminder)
            provider_ok: bool
            provider_ref: str | None = None
            provider_status_code: str | None = None
            provider_error_text: str | None = None
            provider_accept_only = False
            delivery_confidence = "none"

            if isinstance(provider_result, dict):
                provider_ok = bool(provider_result.get("ok", False))
                provider_ref = provider_result.get("provider_ref")
                provider_status_code = provider_result.get("provider_status_code")
                provider_error_text = provider_result.get("provider_error_text")
                provider_accept_only = bool(provider_result.get("provider_accept_only", False))
                delivery_confidence = provider_result.get("delivery_confidence") or "none"
            else:
                provider_ok = bool(provider_result)

            has_transport_evidence = self._has_transport_meaningful_ref(
                provider_ref,
                reminder_id=reminder.reminder_id,
                dedupe_key=delivery_key,
            )
            effective_provider_ref = provider_ref if has_transport_evidence else delivery_key

            if provider_ok:
                reminder.status = "delivered"
                self._store.update_reminder(reminder)
                self._visible_delivery_keys.add(delivery_key)
                outcomes.append((delivery_key, ReasonCode.DELIVERED_SUCCESS))
                self._store.append_delivery_attempt(
                    attempt_id=f"att-{reminder.reminder_id}-{reminder.attempts}",
                    reminder_id=reminder.reminder_id,
                    attempt_index=reminder.attempts,
                    attempted_at_utc=now_utc,
                    status="delivered",
                    reason_code=ReasonCode.DELIVERED_SUCCESS.value,
                    provider_ref=effective_provider_ref,
                    provider_status_code=provider_status_code or "ok",
                    provider_error_text=None,
                    provider_accept_only=provider_accept_only or not has_transport_evidence,
                    delivery_confidence=(
                        delivery_confidence
                        if delivery_confidence != "none"
                        else ("provider_confirmed" if has_transport_evidence else "provider_accepted")
                    ),
                    result_at_utc=now_utc,
                    trace_id="delivery",
                    causation_id=reminder.reminder_id,
                    source_adapter_attempt_id=None,
                )
                self._append_audit(
                    "delivery",
                    reminder.reminder_id,
                    "delivery",
                    ReasonCode.DELIVERED_SUCCESS,
                    effective_provider_ref,
                )
                continue

            fail_reason = ReasonCode.FAILED_PROVIDER_TRANSIENT
            fail_error_text = provider_error_text or "provider transient failure"
            self._append_audit(
                "delivery", reminder.reminder_id, "delivery", fail_reason, provider_ref or delivery_key
            )
            retry_limit = min(self.max_retries, self._store.get_max_retry_attempts())
            if reminder.attempts > retry_limit:
                reminder.status = "failed"
                self._store.update_reminder(reminder)
                self._store.append_delivery_attempt(
                    attempt_id=f"att-{reminder.reminder_id}-{reminder.attempts}",
                    reminder_id=reminder.reminder_id,
                    attempt_index=reminder.attempts,
                    attempted_at_utc=now_utc,
                    status="failed",
                    reason_code=ReasonCode.FAILED_RETRY_EXHAUSTED.value,
                    provider_ref=provider_ref,
                    provider_status_code=provider_status_code or "retry_exhausted",
                    provider_error_text=fail_error_text,
                    provider_accept_only=False,
                    delivery_confidence="none",
                    result_at_utc=now_utc,
                    trace_id="delivery",
                    causation_id=reminder.reminder_id,
                    source_adapter_attempt_id=None,
                )
                outcomes.append((delivery_key, ReasonCode.FAILED_RETRY_EXHAUSTED))
                self._append_audit(
                    "delivery",
                    reminder.reminder_id,
                    "delivery",
                    ReasonCode.FAILED_RETRY_EXHAUSTED,
                    provider_ref or delivery_key,
                )
            else:
                reminder.next_attempt_at_utc = now_utc + timedelta(minutes=self.retry_delay_minutes)
                self._store.update_reminder(reminder)
                self._store.append_delivery_attempt(
                    attempt_id=f"att-{reminder.reminder_id}-{reminder.attempts}",
                    reminder_id=reminder.reminder_id,
                    attempt_index=reminder.attempts,
                    attempted_at_utc=now_utc,
                    status="failed",
                    reason_code=fail_reason.value,
                    provider_ref=provider_ref,
                    provider_status_code=provider_status_code or "transient",
                    provider_error_text=fail_error_text,
                    provider_accept_only=False,
                    delivery_confidence="none",
                    result_at_utc=now_utc,
                    trace_id="delivery",
                    causation_id=reminder.reminder_id,
                    source_adapter_attempt_id=None,
                )
                outcomes.append((delivery_key, fail_reason))
        return outcomes

    @staticmethod
    def _has_transport_meaningful_ref(provider_ref: str | None, *, reminder_id: str, dedupe_key: str) -> bool:
        if provider_ref is None:
            return False
        token = provider_ref.strip()
        if not token:
            return False
        lowered = token.lower()
        blocked_tokens = {
            "none",
            "null",
            "n/a",
            "na",
            "placeholder",
            "synthetic",
            dedupe_key.lower(),
            reminder_id.lower(),
            f"att-{reminder_id}".lower(),
            f"rcpt:att-{reminder_id}".lower(),
        }
        if lowered in blocked_tokens:
            return False
        if lowered.startswith("att-") or lowered.startswith("rcpt:att-"):
            return False
        return True

    def run_reconciliation_batch(self, now_utc: datetime, *, batch_size: int = 50) -> dict:
        if self._store.get_runtime_mode() == "capture_only":
            self._append_audit(
                "system", "capture_only", "recovery", ReasonCode.CAPTURE_ONLY_BLOCKED, "recovery blocked"
            )
            return {"processed": 0, "has_more": False, "reason_code": ReasonCode.CAPTURE_ONLY_BLOCKED.value}

        due = list(self._store.list_due_reminders(now_utc, limit=batch_size))
        processed = 0
        for reminder in due:
            if (
                reminder.status == "attempted"
                and reminder.next_attempt_at_utc
                and reminder.next_attempt_at_utc <= now_utc
            ):
                reminder.status = "scheduled"
                reminder.next_attempt_at_utc = None
                self._store.update_reminder(reminder)
                self._append_audit(
                    "recovery",
                    reminder.reminder_id,
                    "recovery",
                    ReasonCode.RECOVERY_RECONCILED,
                    reminder.dedupe_key,
                )
                processed += 1

        total_due = self._store.count_due_reminders(now_utc)
        return {
            "processed": processed,
            "has_more": total_due > batch_size,
            "reason_code": ReasonCode.RECOVERY_RECONCILED.value,
        }

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
                bucket.append(
                    {"event_id": event.event_id, "title": event.title, "local_start": local_start.isoformat()}
                )

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
        (
            event_override_channel,
            event_override_target_ref,
            request_context_default_channel,
            request_context_default_target_ref,
        ) = self._resolve_event_destination_fields(intent, current_event=None)
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
            event_override_channel=event_override_channel,
            event_override_target_ref=event_override_target_ref,
            request_context_default_channel=request_context_default_channel,
            request_context_default_target_ref=request_context_default_target_ref,
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
        (
            event_override_channel,
            event_override_target_ref,
            request_context_default_channel,
            request_context_default_target_ref,
        ) = self._resolve_event_destination_fields(intent, current_event=current)
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
            event_override_channel=event_override_channel,
            event_override_target_ref=event_override_target_ref,
            request_context_default_channel=request_context_default_channel,
            request_context_default_target_ref=request_context_default_target_ref,
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
            event_override_channel=current.event_override_channel,
            event_override_target_ref=current.event_override_target_ref,
            request_context_default_channel=current.request_context_default_channel,
            request_context_default_target_ref=current.request_context_default_target_ref,
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
            dedupe_key = (
                f"{event.event_id}:{event.version}:{recipient_id}:{event.reminder_offset_minutes}:{trigger.isoformat()}"
            )

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
                    event_override_channel=event.event_override_channel,
                    event_override_target_ref=event.event_override_target_ref,
                    request_context_default_channel=event.request_context_default_channel,
                    request_context_default_target_ref=event.request_context_default_target_ref,
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
                event_override_channel=event.event_override_channel,
                event_override_target_ref=event.event_override_target_ref,
                request_context_default_channel=event.request_context_default_channel,
                request_context_default_target_ref=event.request_context_default_target_ref,
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

    @staticmethod
    def _intent_hash(intent: dict) -> str:
        stable = {
            "action": intent.get("action", "create"),
            "title": intent.get("title"),
            "start_at_local": intent.get("start_at_local").isoformat() if intent.get("start_at_local") else None,
            "participants": sorted(intent.get("participants", ())),
            "audience": sorted(intent.get("audience", ())),
            "reminder_offset_minutes": intent.get("reminder_offset_minutes"),
            "event_id": intent.get("event_id"),
            "event_timezone": intent.get("event_timezone"),
            "event_override_channel": intent.get("event_override_channel"),
            "event_override_target_ref": intent.get("event_override_target_ref"),
            "request_context_default_channel": intent.get("request_context_default_channel"),
            "request_context_default_target_ref": intent.get("request_context_default_target_ref"),
        }
        return sha256(json.dumps(stable, sort_keys=True).encode("utf-8")).hexdigest()
