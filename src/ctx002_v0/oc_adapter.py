from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Literal

from .persistence.reason_binding import ReasonCodeBinding, validate_reason_code_binding
from .reason_codes import ReasonCode

DeliveryStatus = Literal["DELIVERED", "FAILED_TRANSIENT", "FAILED_PERMANENT", "SUPPRESSED", "BLOCKED"]
DeliveryConfidence = Literal["provider_confirmed", "provider_accepted", "none"]
ErrorClass = Literal["transient", "permanent", "policy", "config", "unknown"]
RetryClassificationSource = Literal["policy_override", "provider_map", "fallback_default"]
ReplaySource = Literal["attempt_id_hit", "dedupe_key_window_hit", "none"]
RuntimeMode = Literal["normal", "capture_only"]
NormalizedOutcomeClass = Literal["success", "transient", "permanent", "blocked", "suppressed", "unknown"]
ProviderConfirmationStrength = Literal["accepted", "confirmed", "none"]

WHATSAPP_CANONICAL_RE = re.compile(r"^(?:whatsapp:)?(?:\+?[1-9]\d{6,14}|\d{10,30}@g\.us)$")


class AdapterContractError(RuntimeError):
    pass


@dataclass(frozen=True)
class OutboundMessage:
    delivery_id: str
    attempt_id: str
    attempt_index: int
    trace_id: str
    causation_id: str
    channel_hint: str
    target_ref: str
    subject_type: str
    priority: str
    body_text: str
    dedupe_key: str
    created_at_utc: datetime
    payload_json: dict[str, Any] | None = None
    payload_schema_version: int | None = None
    compat_structured_payload_json: dict[str, Any] | None = None
    compat_structured_payload_schema_version: int | None = None
    metadata_json: dict[str, Any] | None = None
    metadata_schema_version: int | None = None


@dataclass(frozen=True)
class ErrorObject:
    normalized_code: str
    retry_classification_source: RetryClassificationSource
    error_class: ErrorClass
    message_sanitized: str
    provider_code: str | None = None
    details_json: dict[str, Any] | None = None
    details_schema_version: int | None = None


@dataclass(frozen=True)
class DeliveryResult:
    status: DeliveryStatus
    reason_code: str
    retry_eligible: bool
    provider_receipt_ref: str | None
    provider_status_code: str | None
    provider_error_text: str | None
    provider_accept_only: bool
    delivery_confidence: DeliveryConfidence
    result_at_utc: datetime
    error_object: ErrorObject | None
    replay_indicator: bool
    replay_source: ReplaySource
    delivery_id: str
    attempt_id: str
    trace_id: str
    causation_id: str


@dataclass(frozen=True)
class AdapterCapabilities:
    supports_channel_hints: tuple[str, ...]
    supports_media: bool
    supports_priority: bool
    supports_delivery_receipts: bool
    supports_target_resolution: bool


@dataclass(frozen=True)
class AdapterHealth:
    state: Literal["UP", "DEGRADED", "DOWN"]
    snapshot_ts_utc: datetime
    max_health_age_ms: int
    health_fail_mode: Literal["strict", "non_strict"]
    details_json: dict[str, Any] | None
    details_schema_version: int | None
    event_ts_utc: datetime


@dataclass(frozen=True)
class OpenClawSendResponseNormalized:
    normalized_outcome_class: NormalizedOutcomeClass
    provider_status_code: str | None
    provider_receipt_ref: str | None
    provider_error_class_hint: ErrorClass | None
    provider_error_message_sanitized: str | None
    provider_confirmation_strength: ProviderConfirmationStrength
    raw_observed_at_utc: datetime


@dataclass(frozen=True)
class MappingRule:
    status: DeliveryStatus
    reason_code: str
    retry_eligible: bool
    error_class: ErrorClass | None = None


def delivery_result_to_attempt_kwargs(
    *,
    result: DeliveryResult,
    reminder_id: str,
    attempt_index: int,
    attempted_at_utc: datetime,
) -> dict[str, Any]:
    status_map = {
        "DELIVERED": "delivered",
        "FAILED_TRANSIENT": "failed",
        "FAILED_PERMANENT": "failed",
        "SUPPRESSED": "suppressed",
        "BLOCKED": "blocked",
    }
    return {
        "attempt_id": result.attempt_id,
        "reminder_id": reminder_id,
        "attempt_index": attempt_index,
        "attempted_at_utc": attempted_at_utc,
        "status": status_map[result.status],
        "reason_code": result.reason_code,
        "provider_ref": result.provider_receipt_ref,
        "provider_status_code": result.provider_status_code,
        "provider_error_text": result.provider_error_text,
        "provider_accept_only": result.provider_accept_only,
        "delivery_confidence": result.delivery_confidence,
        "result_at_utc": result.result_at_utc,
        "trace_id": result.trace_id,
        "causation_id": result.causation_id,
        "source_adapter_attempt_id": result.attempt_id,
    }


class OpenClawGatewayAdapter:
    def __init__(
        self,
        *,
        send_fn: Callable[[OutboundMessage], OpenClawSendResponseNormalized],
        now_fn: Callable[[], datetime] | None = None,
        read_runtime_mode: Callable[[], RuntimeMode] | None = None,
        resolve_target_fn: Callable[[str], str | None] | None = None,
        capabilities: AdapterCapabilities | None = None,
        policy_override_map: dict[str, MappingRule] | None = None,
        provider_map: dict[NormalizedOutcomeClass, MappingRule] | None = None,
        adapter_dedupe_window_ms: int = 86_400_000,
        reason_binding: ReasonCodeBinding | None = None,
    ) -> None:
        self._send_fn = send_fn
        self._now_fn = now_fn or (lambda: datetime.now(UTC))
        self._read_runtime_mode = read_runtime_mode or (lambda: "normal")
        self._resolve_target_fn = resolve_target_fn
        self._capabilities = capabilities or AdapterCapabilities(
            supports_channel_hints=("discord", "signal", "telegram", "whatsapp", "openclaw_auto"),
            supports_media=False,
            supports_priority=True,
            supports_delivery_receipts=True,
            supports_target_resolution=False,
        )
        self._policy_override_map = policy_override_map or {}
        self._provider_map = provider_map or {
            "success": MappingRule("DELIVERED", ReasonCode.DELIVERED_SUCCESS.value, False, None),
            "transient": MappingRule(
                "FAILED_TRANSIENT", ReasonCode.FAILED_PROVIDER_TRANSIENT.value, True, "transient"
            ),
            "permanent": MappingRule(
                "FAILED_PERMANENT", ReasonCode.FAILED_PROVIDER_PERMANENT.value, False, "permanent"
            ),
            "blocked": MappingRule("BLOCKED", ReasonCode.FAILED_CONFIG_INVALID_TARGET.value, False, "config"),
            "suppressed": MappingRule("SUPPRESSED", ReasonCode.SUPPRESSED_QUIET_HOURS.value, False, "policy"),
            "unknown": MappingRule(
                "FAILED_TRANSIENT", ReasonCode.FAILED_PROVIDER_TRANSIENT.value, True, "unknown"
            ),
        }
        self._adapter_dedupe_window_ms = adapter_dedupe_window_ms

        if reason_binding is None:
            spec_path = Path(__file__).resolve().parents[2] / "specs" / "KINFLOW_REASON_CODES_CANONICAL.md"
            reason_binding = ReasonCodeBinding(
                spec_path=str(spec_path),
                spec_version="v1.0.6",
                spec_sha256="f6472addbf19a97c589b8b49a6334fbbb5e0678b670ca47e65d923f963bc02e6",
            )
        validate_reason_code_binding(reason_binding)

        self._canonical_by_attempt_id: dict[str, DeliveryResult] = {}
        self._canonical_by_dedupe: dict[str, list[DeliveryResult]] = {}
        self._audit_events: list[dict[str, Any]] = []
        self._last_health_snapshot: datetime | None = None

    def capabilities(self) -> AdapterCapabilities:
        return self._capabilities

    def health(self) -> AdapterHealth:
        now = self._now_fn()
        snapshot = self._last_health_snapshot
        if snapshot is None:
            state: Literal["UP", "DEGRADED", "DOWN"] = "DOWN"
            snapshot = now
        else:
            age_ms = int((now - snapshot).total_seconds() * 1000)
            state = "UP" if age_ms <= 5000 else "DEGRADED"
        return AdapterHealth(
            state=state,
            snapshot_ts_utc=snapshot,
            max_health_age_ms=5000,
            health_fail_mode="non_strict",
            details_json={"adapter": "openclaw", "audit_events": len(self._audit_events)},
            details_schema_version=1,
            event_ts_utc=now,
        )

    @property
    def audit_events(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._audit_events)

    def send(self, outbound: OutboundMessage) -> DeliveryResult:
        outbound = self._normalize_compat_payload_fields(outbound)
        self._validate_outbound(outbound)

        replay = self._replay_by_attempt_id(outbound)
        if replay is not None:
            self._append_audit("replay_returned", replay, outbound.dedupe_key, outbound)
            return replay

        replay = self._replay_by_dedupe_key_window(outbound)
        if replay is not None:
            self._append_audit("dedupe_hit", replay, outbound.dedupe_key, outbound)
            return replay

        capability_block = self._capability_block_if_any(outbound)
        if capability_block is not None:
            canonical = self._freeze_result(canonical=capability_block, dedupe_key=outbound.dedupe_key)
            self._append_audit("capability_blocked", canonical, outbound.dedupe_key, outbound)
            return canonical

        normalized_target = self._normalize_target(outbound)
        if normalized_target is None:
            canonical = self._freeze_result(
                canonical=self._blocked_result(
                    outbound,
                    reason_code=ReasonCode.FAILED_CAPABILITY_UNSUPPORTED.value,
                    message="target alias unresolved",
                    retry_classification_source="policy_override",
                    error_class="config",
                ),
                dedupe_key=outbound.dedupe_key,
            )
            self._append_audit("capability_blocked", canonical, outbound.dedupe_key, outbound)
            return canonical

        if self._read_runtime_mode() == "capture_only":
            canonical = self._freeze_result(
                canonical=self._blocked_result(
                    outbound,
                    reason_code=ReasonCode.CAPTURE_ONLY_BLOCKED.value,
                    message="capture_only runtime mode",
                    retry_classification_source="policy_override",
                    error_class="policy",
                ),
                dedupe_key=outbound.dedupe_key,
            )
            self._append_audit("capture_only_blocked", canonical, outbound.dedupe_key, outbound)
            return canonical

        provider_response = self._send_fn(
            OutboundMessage(
                **{
                    **outbound.__dict__,
                    "target_ref": normalized_target,
                }
            )
        )
        self._last_health_snapshot = self._now_fn()

        canonical = self._freeze_result(
            canonical=self._map_provider_response(outbound, provider_response),
            dedupe_key=outbound.dedupe_key,
        )
        self._append_audit("send_result", canonical, outbound.dedupe_key, outbound)
        return canonical

    def _append_audit(
        self,
        event_type: str,
        result: DeliveryResult,
        dedupe_key: str,
        outbound: OutboundMessage,
    ) -> None:
        daemon_cycle_id = None
        if outbound.metadata_json is not None:
            daemon_cycle_id = outbound.metadata_json.get("daemon_cycle_id")
        self._audit_events.append(
            {
                "event_ts_utc": self._now_fn().isoformat(),
                "audit_event_type": event_type,
                "delivery_id": result.delivery_id,
                "attempt_id": result.attempt_id,
                "trace_id": result.trace_id,
                "causation_id": result.causation_id,
                "dedupe_key": dedupe_key,
                "status": result.status,
                "reason_code": result.reason_code,
                "delivery_confidence": result.delivery_confidence,
                "provider_status_code": result.provider_status_code,
                "provider_receipt_ref": result.provider_receipt_ref,
                "replay_indicator": result.replay_indicator,
                "replay_source": result.replay_source,
                "result_at_utc": result.result_at_utc.isoformat(),
                "daemon_cycle_id": daemon_cycle_id,
            }
        )

    def _replay_by_attempt_id(self, outbound: OutboundMessage) -> DeliveryResult | None:
        canonical = self._canonical_by_attempt_id.get(outbound.attempt_id)
        if canonical is None:
            return None
        return DeliveryResult(**{**canonical.__dict__, "replay_indicator": True, "replay_source": "attempt_id_hit"})

    def _replay_by_dedupe_key_window(self, outbound: OutboundMessage) -> DeliveryResult | None:
        candidates = self._canonical_by_dedupe.get(outbound.dedupe_key, [])
        if not candidates:
            return None
        now = self._now_fn()
        for canonical in reversed(candidates):
            age_ms = int((now - canonical.result_at_utc).total_seconds() * 1000)
            if age_ms <= self._adapter_dedupe_window_ms:
                return DeliveryResult(
                    **{**canonical.__dict__, "replay_indicator": True, "replay_source": "dedupe_key_window_hit"}
                )
        return None

    def _freeze_result(self, *, canonical: DeliveryResult, dedupe_key: str) -> DeliveryResult:
        self._canonical_by_attempt_id[canonical.attempt_id] = canonical
        self._canonical_by_dedupe.setdefault(dedupe_key, []).append(canonical)
        return canonical

    def _capability_block_if_any(self, outbound: OutboundMessage) -> DeliveryResult | None:
        if outbound.channel_hint not in self._capabilities.supports_channel_hints:
            return self._blocked_result(
                outbound,
                reason_code=ReasonCode.FAILED_CAPABILITY_UNSUPPORTED.value,
                message=f"unsupported channel_hint: {outbound.channel_hint}",
                retry_classification_source="policy_override",
                error_class="config",
            )
        if outbound.priority == "high" and not self._capabilities.supports_priority:
            return self._blocked_result(
                outbound,
                reason_code=ReasonCode.FAILED_CAPABILITY_UNSUPPORTED.value,
                message="priority unsupported",
                retry_classification_source="policy_override",
                error_class="config",
            )
        return None

    def _normalize_target(self, outbound: OutboundMessage) -> str | None:
        if outbound.channel_hint != "whatsapp":
            return outbound.target_ref

        if WHATSAPP_CANONICAL_RE.fullmatch(outbound.target_ref):
            return outbound.target_ref.removeprefix("whatsapp:")

        if not self._capabilities.supports_target_resolution or self._resolve_target_fn is None:
            return None

        resolved = self._resolve_target_fn(outbound.target_ref)
        if resolved is None:
            return None

        if not WHATSAPP_CANONICAL_RE.fullmatch(resolved):
            return None
        return resolved.removeprefix("whatsapp:")

    def _map_provider_response(
        self,
        outbound: OutboundMessage,
        provider_response: OpenClawSendResponseNormalized,
    ) -> DeliveryResult:
        if not isinstance(provider_response.provider_status_code, (str, type(None))):
            raise AdapterContractError("provider_status_code must be string|null")
        if not isinstance(provider_response.provider_receipt_ref, (str, type(None))):
            raise AdapterContractError("provider_receipt_ref must be string|null")

        source: RetryClassificationSource
        confidence = self._derive_confidence(provider_response.provider_confirmation_strength)
        weak_evidence_trigger = (
            provider_response.normalized_outcome_class == "success" and confidence == "provider_accepted"
        )

        if weak_evidence_trigger:
            rule = MappingRule(
                status="DELIVERED",
                reason_code=ReasonCode.DELIVERED_SUCCESS.value,
                retry_eligible=False,
                error_class=None,
            )
            source = "provider_map"
        else:
            has_override = (
                provider_response.provider_status_code is not None
                and provider_response.provider_status_code in self._policy_override_map
            )
            if has_override:
                rule = self._policy_override_map[provider_response.provider_status_code]
                source = "policy_override"
            elif provider_response.normalized_outcome_class in self._provider_map:
                rule = self._provider_map[provider_response.normalized_outcome_class]
                source = "provider_map"
            else:
                rule = MappingRule(
                    status="FAILED_TRANSIENT",
                    reason_code=ReasonCode.FAILED_PROVIDER_TRANSIENT.value,
                    retry_eligible=True,
                    error_class="unknown",
                )
                source = "fallback_default"

        if rule.status != "DELIVERED":
            confidence = "none"

        provider_accept_only = rule.status == "DELIVERED" and confidence == "provider_accepted"
        if confidence == "provider_confirmed":
            provider_accept_only = False

        error_object = None
        if rule.status != "DELIVERED":
            error_object = ErrorObject(
                normalized_code=rule.reason_code,
                retry_classification_source=source,
                error_class=rule.error_class or provider_response.provider_error_class_hint or "unknown",
                message_sanitized=provider_response.provider_error_message_sanitized or "delivery failed",
                provider_code=provider_response.provider_status_code,
                details_json=None,
                details_schema_version=None,
            )

        result = DeliveryResult(
            status=rule.status,
            reason_code=rule.reason_code,
            retry_eligible=rule.retry_eligible,
            provider_receipt_ref=provider_response.provider_receipt_ref,
            provider_status_code=provider_response.provider_status_code,
            provider_error_text=provider_response.provider_error_message_sanitized,
            provider_accept_only=provider_accept_only,
            delivery_confidence=confidence,
            result_at_utc=self._now_fn(),
            error_object=error_object,
            replay_indicator=False,
            replay_source="none",
            delivery_id=outbound.delivery_id,
            attempt_id=outbound.attempt_id,
            trace_id=outbound.trace_id,
            causation_id=outbound.causation_id,
        )
        if weak_evidence_trigger and not (
            result.status == "DELIVERED"
            and result.reason_code == ReasonCode.DELIVERED_SUCCESS.value
            and result.delivery_confidence == "provider_accepted"
            and result.provider_accept_only is True
        ):
            raise AdapterContractError("WEAK_EVIDENCE_TUPLE_LOCK_VIOLATION")
        self._validate_result(result)
        return result

    @staticmethod
    def _derive_confidence(provider_confirmation_strength: ProviderConfirmationStrength) -> DeliveryConfidence:
        mapping: dict[ProviderConfirmationStrength, DeliveryConfidence] = {
            "accepted": "provider_accepted",
            "confirmed": "provider_confirmed",
            "none": "none",
        }
        return mapping[provider_confirmation_strength]

    @staticmethod
    def _normalize_compat_payload_fields(outbound: OutboundMessage) -> OutboundMessage:
        payload_json = outbound.payload_json
        payload_schema_version = outbound.payload_schema_version

        if outbound.compat_structured_payload_json is not None:
            if payload_json is not None and payload_json != outbound.compat_structured_payload_json:
                raise AdapterContractError("DIVERGENT_PAYLOAD_ALIAS_VALUES")
            payload_json = outbound.compat_structured_payload_json

        if outbound.compat_structured_payload_schema_version is not None:
            if (
                payload_schema_version is not None
                and payload_schema_version != outbound.compat_structured_payload_schema_version
            ):
                raise AdapterContractError("DIVERGENT_PAYLOAD_SCHEMA_ALIAS_VALUES")
            payload_schema_version = outbound.compat_structured_payload_schema_version

        payload = {
            **outbound.__dict__,
            "payload_json": payload_json,
            "payload_schema_version": payload_schema_version,
        }
        return OutboundMessage(**payload)

    @staticmethod
    def _validate_outbound(outbound: OutboundMessage) -> None:
        if outbound.attempt_index < 1:
            raise AdapterContractError("attempt_index must be >= 1")
        if not outbound.body_text or len(outbound.body_text) > 4000:
            raise AdapterContractError("body_text out of bounds")
        if outbound.payload_json is None and outbound.payload_schema_version is not None:
            raise AdapterContractError("payload_json null requires payload_schema_version null")
        if outbound.payload_json is not None and outbound.payload_schema_version is None:
            raise AdapterContractError("payload_json non-null requires payload_schema_version non-null")
        if outbound.metadata_json is None and outbound.metadata_schema_version is not None:
            raise AdapterContractError("metadata_json null requires metadata_schema_version null")
        if outbound.metadata_json is not None and outbound.metadata_schema_version is None:
            raise AdapterContractError("metadata_json non-null requires metadata_schema_version non-null")

    @staticmethod
    def _validate_result(result: DeliveryResult) -> None:
        if result.status == "DELIVERED":
            if result.reason_code != ReasonCode.DELIVERED_SUCCESS.value:
                raise AdapterContractError("status DELIVERED requires reason DELIVERED_SUCCESS")
            if result.error_object is not None:
                raise AdapterContractError("status DELIVERED requires error_object null")
            if result.delivery_confidence not in {"provider_confirmed", "provider_accepted"}:
                raise AdapterContractError("status DELIVERED requires provider_confirmed/provider_accepted")
        else:
            if result.error_object is None:
                raise AdapterContractError("non-delivered status requires error_object")
            if result.delivery_confidence != "none":
                raise AdapterContractError("non-delivered status requires delivery_confidence=none")
            if result.error_object and result.error_object.normalized_code != result.reason_code:
                raise AdapterContractError("error_object.normalized_code must equal reason_code")

        if result.delivery_confidence == "provider_confirmed" and result.provider_accept_only:
            raise AdapterContractError("provider_confirmed requires provider_accept_only=false")
        if result.delivery_confidence == "provider_accepted" and not result.provider_accept_only:
            raise AdapterContractError("provider_accepted requires provider_accept_only=true")
        if result.provider_accept_only and not (
            result.status == "DELIVERED" and result.delivery_confidence == "provider_accepted"
        ):
            raise AdapterContractError("provider_accept_only=true only allowed for delivered/provider_accepted")

    def _blocked_result(
        self,
        outbound: OutboundMessage,
        *,
        reason_code: str,
        message: str,
        retry_classification_source: RetryClassificationSource,
        error_class: ErrorClass,
    ) -> DeliveryResult:
        result = DeliveryResult(
            status="BLOCKED",
            reason_code=reason_code,
            retry_eligible=False,
            provider_receipt_ref=None,
            provider_status_code=None,
            provider_error_text=message,
            provider_accept_only=False,
            delivery_confidence="none",
            result_at_utc=self._now_fn(),
            error_object=ErrorObject(
                normalized_code=reason_code,
                retry_classification_source=retry_classification_source,
                error_class=error_class,
                message_sanitized=message,
            ),
            replay_indicator=False,
            replay_source="none",
            delivery_id=outbound.delivery_id,
            attempt_id=outbound.attempt_id,
            trace_id=outbound.trace_id,
            causation_id=outbound.causation_id,
        )
        self._validate_result(result)
        return result
