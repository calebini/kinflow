from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import fcntl

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ctx002_v0.daemon import DaemonRuntime, validate_daemon_config
from ctx002_v0.models import AuditRecord, Reminder
from ctx002_v0.oc_adapter import OpenClawGatewayAdapter, OpenClawSendResponseNormalized, OutboundMessage
from ctx002_v0.persistence.reason_binding import ReasonCodeBinding
from ctx002_v0.persistence.store import SqliteStateStore
from ctx002_v0.reason_codes import ReasonCode

RUNTIME_CONTRACT_VERSION = "v0.1.4"
DEPLOYMENT_CONTRACT_VERSION = "v0.1.4"
SPEC_VERSION_BOUND = "v0.1.3"

FAIL_TOKENS = {
    "STARTUP_CONFIG_MISSING",
    "STARTUP_CONFIG_INVALID",
    "CONTRACT_VERSION_VALIDATION_FAILED",
    "DB_OPEN_FAILED",
    "LOCK_ACQUIRE_FAILED",
    "HEALTH_WRITE_FAILED",
    "RUNTIME_CYCLE_FATAL",
    "FATAL_THRESHOLD_EXCEEDED",
    "GRACEFUL_SHUTDOWN_TIMEOUT",
    "RUNNER_SEAM_GAP_DETECTED",
    "DISPATCH_PATH_NOOP_WIRING_DETECTED",
    "DISPATCH_PATH_WIRING_INCOMPLETE",
    "DISPATCH_ADAPTER_BINDING_INVALID",
    "DISPATCH_ADAPTER_BYPASS_DETECTED",
    "DELIVERED_WITHOUT_ADAPTER_RESULT",
    "FALLBACK_PATH_USED_WITHOUT_FLAG",
    "ADAPTER_ALIGNMENT_SEAM_GAP",
    "BOUNDARY_GATEWAY_URL_UNRESOLVED",
    "BOUNDARY_CHANNEL_UNRESOLVED",
    "BOUNDARY_DESTINATION_UNRESOLVED",
    "BOUNDARY_IDEMPOTENCY_UNRESOLVED",
    "BOUNDARY_SESSION_ACCOUNT_CONFLICT",
    "BOUNDARY_REAL_SENDFN_UNAVAILABLE",
    "BOUNDARY_GATEWAY_CALL_FAILED",
    "BOUNDARY_RESPONSE_UNMAPPABLE",
}


@dataclass(frozen=True)
class RunnerConfig:
    tick_ms: int
    shutdown_grace_ms: int
    lock_timeout_ms: int
    stale_threshold_ms: int
    health_path: Path
    state_stamp_path: Path
    lock_path: Path
    owner_meta_path: Path
    db_path: str
    expected_runtime_contract_version: str
    expected_deployment_contract_version: str
    max_consecutive_fatal_cycles: int
    evidence_root: Path


class RunnerExit(RuntimeError):
    def __init__(self, fail_token: str, detail: str) -> None:
        if fail_token not in FAIL_TOKENS:
            raise RuntimeError(f"non-canonical fail token: {fail_token}")
        super().__init__(detail)
        self.fail_token = fail_token
        self.detail = detail


class SingletonGuard:
    def __init__(self, cfg: RunnerConfig, owner_id: str, pid: int, hostname: str) -> None:
        self.cfg = cfg
        self.owner_id = owner_id
        self.pid = pid
        self.hostname = hostname
        self._fd = None

    def acquire_and_verify(self) -> dict[str, Any] | None:
        self.cfg.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.cfg.owner_meta_path.parent.mkdir(parents=True, exist_ok=True)
        fd = open(self.cfg.lock_path, "a+", encoding="utf-8")
        deadline = time.monotonic() + (self.cfg.lock_timeout_ms / 1000)

        while True:
            try:
                fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    fd.close()
                    raise RunnerExit("LOCK_ACQUIRE_FAILED", "lock timeout")
                time.sleep(0.05)

        takeover_event = None
        previous_owner = _read_json_or_none(self.cfg.owner_meta_path)
        now = _now_iso()
        if previous_owner:
            prev_ts = previous_owner.get("heartbeat_ts_utc")
            if prev_ts:
                age_ms = _age_ms(prev_ts)
                if age_ms is not None and age_ms > self.cfg.stale_threshold_ms:
                    takeover_event = {
                        "event": "LOCK_TAKEOVER",
                        "previous_owner_id": previous_owner.get("owner_id"),
                        "new_owner_id": self.owner_id,
                        "previous_heartbeat_ts_utc": prev_ts,
                        "takeover_ts_utc": now,
                        "stale_threshold_ms": self.cfg.stale_threshold_ms,
                        "db_path": self.cfg.db_path,
                        "pid": self.pid,
                        "hostname": self.hostname,
                    }

        owner_meta = {
            "owner_id": self.owner_id,
            "pid": self.pid,
            "hostname": self.hostname,
            "heartbeat_ts_utc": now,
        }
        _write_json(self.cfg.owner_meta_path, owner_meta)
        verify = _read_json_or_none(self.cfg.owner_meta_path) or {}
        if verify.get("owner_id") != self.owner_id:
            fd.close()
            raise RunnerExit("LOCK_ACQUIRE_FAILED", "ownership verification failed")

        self._fd = fd
        return takeover_event

    def refresh_heartbeat(self) -> None:
        _write_json(
            self.cfg.owner_meta_path,
            {
                "owner_id": self.owner_id,
                "pid": self.pid,
                "hostname": self.hostname,
                "heartbeat_ts_utc": _now_iso(),
            },
        )

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd.fileno(), fcntl.LOCK_UN)
        finally:
            self._fd.close()
            self._fd = None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _age_ms(ts_iso: str) -> int | None:
    try:
        then = datetime.fromisoformat(ts_iso)
        return int((datetime.now(UTC) - then).total_seconds() * 1000)
    except Exception:
        return None


def _read_json_or_none(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True))
    tmp.replace(path)


def _emit(record: dict[str, Any]) -> None:
    print(json.dumps(record, sort_keys=True), flush=True)


def load_runner_config(env: dict[str, str] | None = None) -> RunnerConfig:
    env = env or os.environ
    required = ["KINFLOW_DB_PATH"]
    missing = [k for k in required if not env.get(k)]
    if missing:
        raise RunnerExit("STARTUP_CONFIG_MISSING", f"missing env: {', '.join(missing)}")

    try:
        cfg = RunnerConfig(
            tick_ms=int(env.get("KINFLOW_DAEMON_TICK_MS", "1000")),
            shutdown_grace_ms=int(env.get("KINFLOW_SHUTDOWN_GRACE_MS", "3000")),
            lock_timeout_ms=int(env.get("KINFLOW_LOCK_TIMEOUT_MS", "1500")),
            stale_threshold_ms=int(env.get("KINFLOW_STALE_THRESHOLD_MS", "60000")),
            health_path=Path(env.get("KINFLOW_HEALTH_PATH", "/var/lib/kinflow/health.json")),
            state_stamp_path=Path(env.get("KINFLOW_STATE_STAMP_PATH", "/var/lib/kinflow/dispatch_mode.state")),
            lock_path=Path(env.get("KINFLOW_LOCK_PATH", "/var/lib/kinflow/daemon.lock")),
            owner_meta_path=Path(env.get("KINFLOW_OWNER_META_PATH", "/var/lib/kinflow/daemon.owner.json")),
            db_path=env["KINFLOW_DB_PATH"],
            expected_runtime_contract_version=env.get("KINFLOW_EXPECT_RUNTIME_CONTRACT", RUNTIME_CONTRACT_VERSION),
            expected_deployment_contract_version=env.get("KINFLOW_EXPECT_DEPLOYMENT_CONTRACT", DEPLOYMENT_CONTRACT_VERSION),
            max_consecutive_fatal_cycles=int(env.get("KINFLOW_MAX_CONSECUTIVE_FATAL", "3")),
            evidence_root=Path(env.get("KINFLOW_EVIDENCE_ROOT", str(ROOT / "tmp" / "runner-evidence"))),
        )
    except ValueError as exc:
        raise RunnerExit("STARTUP_CONFIG_INVALID", f"invalid numeric env: {exc}") from exc

    if cfg.tick_ms <= 0 or cfg.max_consecutive_fatal_cycles <= 0:
        raise RunnerExit("STARTUP_CONFIG_INVALID", "tick/fatal threshold must be >0")
    return cfg


def validate_version_bindings(cfg: RunnerConfig) -> None:
    if (
        cfg.expected_runtime_contract_version != RUNTIME_CONTRACT_VERSION
        or cfg.expected_deployment_contract_version != DEPLOYMENT_CONTRACT_VERSION
    ):
        raise RunnerExit(
            "CONTRACT_VERSION_VALIDATION_FAILED",
            "contract version mismatch",
        )


def resolve_db_path(cfg: RunnerConfig) -> str:
    db_path = cfg.db_path
    if not db_path:
        raise RunnerExit("DB_OPEN_FAILED", "empty db path")
    if db_path != ":memory:":
        Path(db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    return db_path


def write_health(
    cfg: RunnerConfig,
    *,
    state: str,
    is_ready: bool,
    last_successful_cycle_id: str | None,
    last_failure_reason_code: str | None,
) -> None:
    payload = {
        "state": state,
        "is_ready": is_ready,
        "snapshot_ts_utc": _now_iso(),
        "last_successful_cycle_id": last_successful_cycle_id,
        "last_failure_reason_code": last_failure_reason_code,
        "health_age_ms": 0,
    }
    try:
        _write_json(cfg.health_path, payload)
    except Exception as exc:
        raise RunnerExit("HEALTH_WRITE_FAILED", str(exc)) from exc


def write_state_stamp(cfg: RunnerConfig) -> None:
    cfg.state_stamp_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.state_stamp_path.write_text("dispatch_mode=daemon\n")


def _takeover_log_path(cfg: RunnerConfig) -> Path:
    return cfg.evidence_root / "singleton" / "takeover_events.jsonl"


def append_takeover_event(cfg: RunnerConfig, event: dict[str, Any]) -> None:
    path = _takeover_log_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, sort_keys=True) + "\n")


class BoundaryFailStopError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _default_adapter_send(msg: OutboundMessage) -> OpenClawSendResponseNormalized:
    return OpenClawSendResponseNormalized(
        normalized_outcome_class="success",
        provider_status_code="ok",
        provider_receipt_ref=f"rcpt:{msg.attempt_id}",
        provider_error_class_hint=None,
        provider_error_message_sanitized=None,
        provider_confirmation_strength="confirmed",
        raw_observed_at_utc=datetime.now(UTC),
    )


def _read_gateway_runtime_inputs(env: dict[str, str] | None = None) -> dict[str, str | None]:
    env = env or os.environ
    gateway_url = (env.get("KINFLOW_GATEWAY_URL") or "").strip()
    if not gateway_url:
        raise BoundaryFailStopError("BOUNDARY_GATEWAY_URL_UNRESOLVED", "missing KINFLOW_GATEWAY_URL")
    return {
        "gateway_url": gateway_url,
        "gateway_token": (env.get("KINFLOW_GATEWAY_TOKEN") or "").strip() or None,
        "gateway_password": (env.get("KINFLOW_GATEWAY_PASSWORD") or "").strip() or None,
        "gateway_tls_fingerprint": (env.get("KINFLOW_GATEWAY_TLS_FINGERPRINT") or "").strip() or None,
        "gateway_timeout_ms": str(int(env.get("KINFLOW_GATEWAY_TIMEOUT_MS", "10000"))),
    }


def _parse_optional_send_fields(outbound: OutboundMessage) -> dict[str, Any]:
    payload = outbound.payload_json if isinstance(outbound.payload_json, dict) else {}
    metadata = outbound.metadata_json if isinstance(outbound.metadata_json, dict) else {}

    def _first_non_empty(*keys: str) -> str | None:
        for key in keys:
            for source in (payload, metadata):
                value = source.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return None

    media_url = _first_non_empty("media_url", "mediaUrl")
    media_urls: list[str] = []
    for key in ("media_urls", "mediaUrls"):
        for source in (payload, metadata):
            value = source.get(key)
            if isinstance(value, list):
                media_urls = [str(item).strip() for item in value if str(item).strip()]
                if media_urls:
                    break
        if media_urls:
            break

    gif_playback_raw = payload.get("gif_playback")
    if gif_playback_raw is None:
        gif_playback_raw = payload.get("gifPlayback")
    if gif_playback_raw is None:
        gif_playback_raw = metadata.get("gif_playback")
    if gif_playback_raw is None:
        gif_playback_raw = metadata.get("gifPlayback")

    return {
        "account_id": _first_non_empty("account_id", "accountId"),
        "session_key": _first_non_empty("session_key", "sessionKey"),
        "media_url": media_url,
        "media_urls": media_urls,
        "gif_playback": bool(gif_playback_raw) if gif_playback_raw is not None else None,
        "effective_account_id": _first_non_empty("effective_account_id", "effectiveAccountId"),
        "effective_session_key": _first_non_empty("effective_session_key", "effectiveSessionKey"),
    }


def _has_session_account_conflict(optional_fields: dict[str, Any]) -> bool:
    account_id = optional_fields.get("account_id")
    session_key = optional_fields.get("session_key")
    if not (account_id and session_key):
        return False

    effective_account_id = optional_fields.get("effective_account_id")
    effective_session_key = optional_fields.get("effective_session_key")
    if effective_account_id and effective_account_id != account_id:
        return True
    if effective_session_key and effective_session_key != session_key:
        return True
    return False


def _extract_gateway_call_json(stdout: str) -> dict[str, Any] | None:
    text = (stdout or "").strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass
    return None


def _normalize_gateway_send_response(payload: dict[str, Any]) -> OpenClawSendResponseNormalized:
    # successful gateway send/no transport error -> success
    if not isinstance(payload, dict):
        raise BoundaryFailStopError("BOUNDARY_RESPONSE_UNMAPPABLE", "gateway payload not an object")

    provider_receipt_ref = None
    for key in ("messageId", "id", "receipt", "ref"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            candidate = value.strip()
            lowered = candidate.lower()
            if lowered.startswith("att-") or lowered.startswith("rcpt:att-"):
                provider_receipt_ref = None
            else:
                provider_receipt_ref = candidate
            break

    provider_confirmation_strength = "confirmed" if provider_receipt_ref else "accepted"

    return OpenClawSendResponseNormalized(
        normalized_outcome_class="success",
        provider_status_code="ok",
        provider_receipt_ref=provider_receipt_ref,
        provider_error_class_hint=None,
        provider_error_message_sanitized=None,
        provider_confirmation_strength=provider_confirmation_strength,
        raw_observed_at_utc=datetime.now(UTC),
    )


def _gateway_failure_response(*, code: str, message: str) -> OpenClawSendResponseNormalized:
    lowered = message.lower()
    if "timeout" in lowered or "timed out" in lowered or "unavailable" in lowered or "rate" in lowered:
        outcome = "transient"
        error_class = "transient"
    elif "blocked" in lowered or "policy" in lowered:
        outcome = "blocked"
        error_class = "policy"
    elif "suppressed" in lowered or "skipped" in lowered:
        outcome = "suppressed"
        error_class = "policy"
    elif "auth" in lowered or "invalid request" in lowered or "unsupported" in lowered or "unknown target" in lowered:
        outcome = "permanent"
        error_class = "permanent"
    else:
        outcome = "transient"
        error_class = "transient"

    return OpenClawSendResponseNormalized(
        normalized_outcome_class=outcome,
        provider_status_code=code,
        provider_receipt_ref=None,
        provider_error_class_hint=error_class,
        provider_error_message_sanitized=message.strip()[:500] if message else code,
        provider_confirmation_strength="none",
        raw_observed_at_utc=datetime.now(UTC),
    )


def build_real_gateway_send_fn(env: dict[str, str] | None = None):
    inputs = _read_gateway_runtime_inputs(env)

    def _send(msg: OutboundMessage) -> OpenClawSendResponseNormalized:
        channel = (msg.channel_hint or "").strip().lower()
        if not channel:
            raise BoundaryFailStopError("BOUNDARY_CHANNEL_UNRESOLVED", "missing outbound channel")
        destination = (msg.target_ref or "").strip()
        if not destination:
            raise BoundaryFailStopError("BOUNDARY_DESTINATION_UNRESOLVED", "missing outbound destination")
        idempotency_key = (msg.dedupe_key or "").strip()
        if not idempotency_key:
            raise BoundaryFailStopError("BOUNDARY_IDEMPOTENCY_UNRESOLVED", "missing outbound idempotency key")

        optional_fields = _parse_optional_send_fields(msg)
        if _has_session_account_conflict(optional_fields):
            raise BoundaryFailStopError(
                "BOUNDARY_SESSION_ACCOUNT_CONFLICT",
                "session/account conflict in effective lane context",
            )

        params: dict[str, Any] = {
            "channel": channel,
            "to": destination,
            "message": msg.body_text,
            "idempotencyKey": idempotency_key,
        }
        if optional_fields.get("account_id"):
            params["accountId"] = optional_fields["account_id"]
        if optional_fields.get("session_key"):
            params["sessionKey"] = optional_fields["session_key"]
        if optional_fields.get("media_url"):
            params["mediaUrl"] = optional_fields["media_url"]
        if optional_fields.get("media_urls"):
            params["mediaUrls"] = optional_fields["media_urls"]
        if optional_fields.get("gif_playback") is not None:
            params["gifPlayback"] = optional_fields["gif_playback"]

        cmd = [
            "openclaw",
            "gateway",
            "call",
            "send",
            "--url",
            str(inputs["gateway_url"]),
            "--timeout",
            str(inputs["gateway_timeout_ms"]),
            "--params",
            json.dumps(params, sort_keys=True),
            "--json",
        ]
        if inputs["gateway_token"]:
            cmd.extend(["--token", str(inputs["gateway_token"])])
        if inputs["gateway_password"]:
            cmd.extend(["--password", str(inputs["gateway_password"])])

        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=int(inputs["gateway_timeout_ms"]))
        if completed.returncode != 0:
            return _gateway_failure_response(
                code="BOUNDARY_GATEWAY_CALL_FAILED",
                message=(completed.stderr or completed.stdout or "gateway call failed"),
            )

        parsed = _extract_gateway_call_json(completed.stdout)
        if parsed is None:
            raise BoundaryFailStopError("BOUNDARY_RESPONSE_UNMAPPABLE", "gateway call returned non-json payload")
        return _normalize_gateway_send_response(parsed)

    return _send


def build_oc_adapter_binding(send_fn=None) -> OpenClawGatewayAdapter | None:
    if os.environ.get("KINFLOW_DISABLE_OC_ADAPTER_BINDING") == "1":
        return None

    resolved_send_fn = send_fn
    if resolved_send_fn is None:
        send_mode = (os.environ.get("KINFLOW_OC_SENDFN_MODE") or "production").strip().lower()
        if send_mode == "test_stub":
            resolved_send_fn = _default_adapter_send
        else:
            try:
                resolved_send_fn = build_real_gateway_send_fn()
            except BoundaryFailStopError as exc:
                raise RunnerExit(exc.code, exc.detail) from exc
            except Exception as exc:
                raise RunnerExit("BOUNDARY_REAL_SENDFN_UNAVAILABLE", str(exc)) from exc

    spec_path = ROOT / "specs" / "KINFLOW_REASON_CODES_CANONICAL.md"
    spec_hash = __import__("hashlib").sha256(spec_path.read_bytes()).hexdigest()
    binding = ReasonCodeBinding(spec_path=str(spec_path), spec_version="v1.0.3", spec_sha256=spec_hash)
    return OpenClawGatewayAdapter(send_fn=resolved_send_fn, reason_binding=binding)


FAIL_TOKEN_REASON_CODE_MAP = {
    "DISPATCH_ADAPTER_BYPASS_DETECTED": ReasonCode.FAILED_PROVIDER_PERMANENT.value,
    "DELIVERED_WITHOUT_ADAPTER_RESULT": ReasonCode.FAILED_PROVIDER_PERMANENT.value,
    "FALLBACK_PATH_USED_WITHOUT_FLAG": ReasonCode.FAILED_PROVIDER_PERMANENT.value,
}


class DispatchCallbacks:
    def __init__(
        self,
        store: SqliteStateStore,
        emit_fn,
        *,
        oc_adapter: OpenClawGatewayAdapter,
        allow_fallback: bool = False,
        force_bypass: bool = False,
    ) -> None:
        self.store = store
        self.emit = emit_fn
        self.oc_adapter = oc_adapter
        self.allow_fallback = allow_fallback
        self.force_bypass = force_bypass

    def list_candidates(self) -> list[dict[str, Any]]:
        due = self.store.list_due_reminders(datetime.now(UTC), limit=100)
        return [{"id": r.reminder_id, "reminder": r} for r in due]

    def process_candidate(self, row: dict[str, Any]) -> bool:
        reminder: Reminder = row["reminder"]
        now = datetime.now(UTC)
        target = self.store.get_delivery_target(reminder.recipient_id)

        if target is None or target.timezone is None:
            self._persist_non_terminal_failure(reminder, ReasonCode.TZ_MISSING.value, "timezone missing", now)
            self._append_delivery_audit(reminder.reminder_id, ReasonCode.TZ_MISSING, reminder.dedupe_key)
            self.emit({"event": "dispatch_blocked", "reason_code": ReasonCode.TZ_MISSING.value, "reminder_id": reminder.reminder_id})
            return False

        reminder.status = "attempted"
        reminder.attempts += 1
        self.store.update_reminder(reminder)

        if target.channel == "whatsapp":
            if self.force_bypass:
                return self._fail_token_consequence("DISPATCH_ADAPTER_BYPASS_DETECTED", reminder, "whatsapp-daemon", now)
            if self.oc_adapter is None:
                if not self.allow_fallback:
                    return self._fail_token_consequence("FALLBACK_PATH_USED_WITHOUT_FLAG", reminder, "whatsapp-daemon", now)
                return self._persist_non_terminal_failure(reminder, ReasonCode.FAILED_CONFIG_INVALID_TARGET.value, "fallback send disabled", now)

            outbound = OutboundMessage(
                delivery_id=f"dly-{reminder.reminder_id}-{reminder.attempts}",
                attempt_id=f"att-{reminder.reminder_id}-{reminder.attempts}",
                attempt_index=reminder.attempts,
                trace_id="daemon_runner",
                causation_id=reminder.reminder_id,
                channel_hint="whatsapp",
                target_ref=target.target_id,
                subject_type="event_reminder",
                priority="normal",
                body_text="A/B lane probe A minimal send",
                dedupe_key=reminder.dedupe_key,
                created_at_utc=now,
                metadata_json={"daemon_cycle_id": row.get("cycle_id", "unknown")},
                metadata_schema_version=1,
            )
            try:
                result = self.oc_adapter.send(outbound)
            except BoundaryFailStopError as exc:
                self.emit(
                    {
                        "event": "dispatch_boundary_fail_stop",
                        "boundary_code": exc.code,
                        "reminder_id": reminder.reminder_id,
                    }
                )
                return self._persist_non_terminal_failure(
                    reminder,
                    ReasonCode.FAILED_PROVIDER_PERMANENT.value,
                    exc.code,
                    now,
                    attempt_id=outbound.attempt_id,
                )
            if not self._delivered_evidence_ok(result):
                return self._fail_token_consequence("DELIVERED_WITHOUT_ADAPTER_RESULT", reminder, "whatsapp-daemon", now)

            reminder.status = "delivered"
            self.store.update_reminder(reminder)
            self.store.append_delivery_attempt(
                attempt_id=outbound.attempt_id,
                reminder_id=reminder.reminder_id,
                attempt_index=reminder.attempts,
                attempted_at_utc=now,
                status="delivered",
                reason_code=result.reason_code,
                provider_ref=result.provider_receipt_ref,
                provider_status_code=result.provider_status_code,
                provider_error_text=result.provider_error_text,
                provider_accept_only=result.provider_accept_only,
                delivery_confidence=result.delivery_confidence,
                result_at_utc=result.result_at_utc,
                trace_id=result.trace_id,
                causation_id=result.causation_id,
                source_adapter_attempt_id=result.attempt_id,
            )
            self._append_delivery_audit(reminder.reminder_id, ReasonCode.DELIVERED_SUCCESS, f"adapter_result={result.status};terminal_decision=ALLOW;reason_code={result.reason_code}")
            return True

        reminder.status = "delivered"
        self.store.update_reminder(reminder)
        self.store.append_delivery_attempt(
            attempt_id=f"att-{reminder.reminder_id}-{reminder.attempts}",
            reminder_id=reminder.reminder_id,
            attempt_index=reminder.attempts,
            attempted_at_utc=now,
            status="delivered",
            reason_code=ReasonCode.DELIVERED_SUCCESS.value,
            provider_ref=reminder.dedupe_key,
            provider_status_code="ok",
            provider_error_text=None,
            provider_accept_only=False,
            delivery_confidence="provider_confirmed",
            result_at_utc=now,
            trace_id="daemon_runner",
            causation_id=reminder.reminder_id,
            source_adapter_attempt_id=None,
        )
        self._append_delivery_audit(reminder.reminder_id, ReasonCode.DELIVERED_SUCCESS, reminder.dedupe_key)
        return True

    def run_reconcile(self) -> bool:
        now = datetime.now(UTC)
        processed = 0
        for reminder in self.store.list_due_reminders(now, limit=100):
            if reminder.status == "attempted" and reminder.next_attempt_at_utc and reminder.next_attempt_at_utc <= now:
                reminder.status = "scheduled"
                reminder.next_attempt_at_utc = None
                self.store.update_reminder(reminder)
                processed += 1
        self.emit({"event": "reconcile_summary", "processed": processed, "at_utc": now.isoformat()})
        return True

    @staticmethod
    def _classify_send_evidence_ref(provider_ref: str | None) -> str:
        if provider_ref is None:
            return "local_non_verifiable"
        token = provider_ref.strip()
        if not token:
            return "local_non_verifiable"
        lowered = token.lower()
        blocked = {"none", "null", "n/a", "na", "placeholder", "synthetic"}
        if lowered in blocked:
            return "local_non_verifiable"
        if lowered.startswith("att-") or lowered.startswith("rcpt:att-") or lowered.startswith("local:"):
            return "local_non_verifiable"
        return "transport_verifiable"

    @staticmethod
    def _provider_ref_transport_meaningful(provider_ref: str | None) -> bool:
        return DispatchCallbacks._classify_send_evidence_ref(provider_ref) == "transport_verifiable"

    def _delivered_evidence_ok(self, result) -> bool:
        if result.reason_code != ReasonCode.DELIVERED_SUCCESS.value:
            return False
        if not result.delivery_confidence:
            return False
        if not result.provider_status_code:
            return False
        if result.result_at_utc is None:
            return False
        if not self._provider_ref_transport_meaningful(result.provider_receipt_ref):
            return False
        return True

    def _persist_non_terminal_failure(
        self,
        reminder: Reminder,
        reason_code: str,
        error_text: str,
        now: datetime,
        *,
        attempt_id: str | None = None,
    ) -> bool:
        reminder.status = "failed"
        self.store.update_reminder(reminder)
        effective_attempt_id = attempt_id or f"att-{reminder.reminder_id}-{max(reminder.attempts, 1)}"
        self.store.append_delivery_attempt(
            attempt_id=effective_attempt_id,
            reminder_id=reminder.reminder_id,
            attempt_index=max(reminder.attempts, 1),
            attempted_at_utc=now,
            status="failed",
            reason_code=reason_code,
            provider_ref=None,
            provider_status_code=None,
            provider_error_text=error_text,
            provider_accept_only=False,
            delivery_confidence="none",
            result_at_utc=now,
            trace_id="daemon_runner",
            causation_id=reminder.reminder_id,
            source_adapter_attempt_id=None,
        )
        return False

    def _fail_token_consequence(self, fail_token: str, reminder: Reminder, path_id: str, now: datetime) -> bool:
        attempt_id = f"att-{reminder.reminder_id}-{max(reminder.attempts, 1)}"
        mapped_reason_code = FAIL_TOKEN_REASON_CODE_MAP.get(fail_token)
        if mapped_reason_code is None:
            raise RunnerExit("ADAPTER_ALIGNMENT_SEAM_GAP", f"missing fail-token mapping: {fail_token}")

        self._persist_non_terminal_failure(
            reminder,
            mapped_reason_code,
            fail_token,
            now,
            attempt_id=attempt_id,
        )
        self._append_delivery_audit(
            reminder.reminder_id,
            ReasonCode(mapped_reason_code),
            f"attempt_id={attempt_id};reminder_id={reminder.reminder_id};path_id={path_id};fail_token={fail_token};terminal_decision=BLOCK",
        )
        self.emit(
            {
                "event": "dispatch_fail_token",
                "attempt_id": attempt_id,
                "fail_token": fail_token,
                "mapped_reason_code": mapped_reason_code,
                "reminder_id": reminder.reminder_id,
                "path_id": path_id,
                "terminal_decision": "BLOCK",
            }
        )
        return False

    def _append_delivery_audit(self, reminder_id: str, reason_code: ReasonCode, payload: str) -> None:
        index = len(self.store.list_audit()) + 1
        self.store.append_audit(
            AuditRecord(
                index=index,
                correlation_id="delivery",
                message_id=reminder_id,
                stage="delivery",
                reason_code=reason_code,
                payload=payload,
            )
        )


def ensure_dispatch_path_wired(callbacks: DispatchCallbacks | None) -> None:
    if callbacks is None:
        raise RunnerExit("DISPATCH_PATH_WIRING_INCOMPLETE", "callbacks missing")
    if callbacks.list_candidates.__func__ is DispatchCallbacks.list_candidates:
        return
    raise RunnerExit("DISPATCH_PATH_NOOP_WIRING_DETECTED", "dispatch callbacks not store-backed")


def run() -> int:
    pid = os.getpid()
    hostname = socket.gethostname()
    owner_id = f"{hostname}:{pid}:{int(time.time())}"
    trace_id = f"runner-{pid}-{int(time.time()*1000)}"
    last_cycle_id = None
    fail_token = None
    shutting_down = False

    def _handle_shutdown(_sig: int, _frame: Any) -> None:
        nonlocal shutting_down
        shutting_down = True

    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    guard: SingletonGuard | None = None
    consecutive_fatals = 0
    runtime = None
    cfg = None

    try:
        # 1) load external config/env
        cfg = load_runner_config()
        _emit({"event": "startup_step", "step": 1, "pid": pid, "hostname": hostname, "owner_id": owner_id})

        # 2) validate required config presence/shape
        daemon_cfg = validate_daemon_config(
            {
                "runtime_mode": "normal",
                "daemon_tick_ms": cfg.tick_ms,
                "reconcile_tick_ms": max(5000, cfg.tick_ms * 5),
                "max_due_batch_size": 100,
                "max_reconcile_batch_size": 100,
                "max_reconcile_batches_per_tick": 1,
                "max_tick_deferral_for_oldest_due": 3,
                "max_health_age_ms": max(1000, cfg.tick_ms * 2),
                "health_fail_mode": "non_strict",
                "health_emit_interval_ms": cfg.tick_ms,
                "idempotency_window_hours": 24,
                "max_retry_attempts": 3,
                "shutdown_grace_ms": cfg.shutdown_grace_ms,
                "db_reconnect_strategy": "fixed",
                "db_reconnect_backoff_ms": 100,
                "db_reconnect_max_attempts": 3,
                "max_consecutive_fatal_cycles": cfg.max_consecutive_fatal_cycles,
                "transaction_scope_mode": "per_row",
            }
        )
        _emit({"event": "startup_step", "step": 2, "pid": pid, "hostname": hostname, "owner_id": owner_id})

        # 3) validate contract version bindings
        validate_version_bindings(cfg)
        _emit({"event": "startup_step", "step": 3, "pid": pid, "hostname": hostname, "owner_id": owner_id})

        # 4) resolve effective DB path
        db_path = resolve_db_path(cfg)
        _emit({"event": "startup_step", "step": 4, "pid": pid, "hostname": hostname, "owner_id": owner_id, "db_path": db_path})

        # 5) initialize singleton guard machinery
        guard = SingletonGuard(cfg, owner_id, pid, hostname)
        _emit({"event": "startup_step", "step": 5, "pid": pid, "hostname": hostname, "owner_id": owner_id})

        # 6) acquire singleton lock and verify ownership
        takeover = guard.acquire_and_verify()
        if takeover:
            append_takeover_event(cfg, takeover)
            _emit({**takeover, "pid": pid, "hostname": hostname, "owner_id": owner_id})
        _emit({"event": "startup_step", "step": 6, "pid": pid, "hostname": hostname, "owner_id": owner_id})

        # 7) initialize store/adapter/runtime bindings
        store = SqliteStateStore.from_path(db_path)
        oc_adapter = build_oc_adapter_binding()
        adapter_bound = bool(oc_adapter is not None and hasattr(oc_adapter, "send") and callable(getattr(oc_adapter, "send", None)))
        if not adapter_bound:
            _emit(
                {
                    "event": "startup_step",
                    "step": 7,
                    "pid": pid,
                    "hostname": hostname,
                    "owner_id": owner_id,
                    "dispatch_path_backed": True,
                    "whatsapp_adapter_bound": False,
                }
            )
            raise RunnerExit("DISPATCH_ADAPTER_BINDING_INVALID", "oc adapter binding missing or non-callable")
        callbacks = DispatchCallbacks(
            store,
            _emit,
            oc_adapter=oc_adapter,
            allow_fallback=os.environ.get("KINFLOW_ALLOW_WHATSAPP_FALLBACK") == "1",
            force_bypass=os.environ.get("KINFLOW_FORCE_WHATSAPP_BYPASS") == "1",
        )
        ensure_dispatch_path_wired(callbacks)
        runtime = DaemonRuntime(
            daemon_cfg,
            read_runtime_mode=store.get_runtime_mode,
            list_candidates=callbacks.list_candidates,
            process_candidate=callbacks.process_candidate,
            run_reconcile=callbacks.run_reconcile,
            emit_event=_emit,
        )
        _emit({"event": "startup_step", "step": 7, "pid": pid, "hostname": hostname, "owner_id": owner_id, "dispatch_path_backed": True, "whatsapp_adapter_bound": True})

        # 8) initialize health surface
        write_health(
            cfg,
            state="starting",
            is_ready=False,
            last_successful_cycle_id=None,
            last_failure_reason_code=None,
        )
        _emit({"event": "startup_step", "step": 8, "pid": pid, "hostname": hostname, "owner_id": owner_id})

        # 9) initialize state stamp (dispatch_mode=daemon)
        write_state_stamp(cfg)
        _emit({"event": "startup_step", "step": 9, "pid": pid, "hostname": hostname, "owner_id": owner_id})

        # 10) enter main loop
        _emit({"event": "startup_step", "step": 10, "pid": pid, "hostname": hostname, "owner_id": owner_id})
        next_tick = time.monotonic()
        has_success = False
        while not shutting_down:
            scheduled = datetime.now(UTC)
            actual = datetime.now(UTC)
            try:
                summary = runtime.run_cycle(scheduled, actual)
                last_cycle_id = summary.get("cycle_id")
                if summary.get("cycle_success"):
                    consecutive_fatals = 0
                    has_success = True
                    write_health(
                        cfg,
                        state="ready",
                        is_ready=has_success,
                        last_successful_cycle_id=last_cycle_id,
                        last_failure_reason_code=None,
                    )
                else:
                    write_health(
                        cfg,
                        state="degraded",
                        is_ready=has_success,
                        last_successful_cycle_id=last_cycle_id if has_success else None,
                        last_failure_reason_code="RUNTIME_CYCLE_FATAL",
                    )
                guard.refresh_heartbeat()
            except RunnerExit:
                raise
            except Exception as exc:
                consecutive_fatals += 1
                _emit(
                    {
                        "event": "cycle_failure",
                        "fail_token": "RUNTIME_CYCLE_FATAL",
                        "error": str(exc),
                        "consecutive_fatals": consecutive_fatals,
                        "trace_id": trace_id,
                        "pid": pid,
                        "hostname": hostname,
                        "owner_id": owner_id,
                    }
                )
                try:
                    write_health(
                        cfg,
                        state="degraded",
                        is_ready=has_success,
                        last_successful_cycle_id=last_cycle_id,
                        last_failure_reason_code="RUNTIME_CYCLE_FATAL",
                    )
                except RunnerExit:
                    pass
                if consecutive_fatals >= cfg.max_consecutive_fatal_cycles:
                    raise RunnerExit("FATAL_THRESHOLD_EXCEEDED", "fatal threshold exceeded") from exc

            next_tick += cfg.tick_ms / 1000
            now_mono = time.monotonic()
            sleep_s = next_tick - now_mono
            if sleep_s > 0:
                time.sleep(sleep_s)
            else:
                # overrun => skip sleep, no burst catch-up loop
                next_tick = now_mono

        # graceful shutdown path
        write_health(
            cfg,
            state="stopping",
            is_ready=False,
            last_successful_cycle_id=last_cycle_id,
            last_failure_reason_code=None,
        )
        return 0

    except RunnerExit as exc:
        fail_token = exc.fail_token
        _emit(
            {
                "event": "runner_fail_stop",
                "fail_token": fail_token,
                "error": exc.detail,
                "trace_id": trace_id,
                "pid": pid,
                "hostname": hostname,
                "owner_id": owner_id,
            }
        )
        if cfg is not None:
            try:
                write_health(
                    cfg,
                    state="failed",
                    is_ready=False,
                    last_successful_cycle_id=last_cycle_id,
                    last_failure_reason_code=fail_token,
                )
            except Exception:
                pass
        return 1
    finally:
        if guard is not None:
            start = time.monotonic()
            while True:
                try:
                    guard.release()
                    break
                except Exception:
                    if cfg is None or (time.monotonic() - start) * 1000 > cfg.shutdown_grace_ms:
                        fail_token = fail_token or "GRACEFUL_SHUTDOWN_TIMEOUT"
                        break
                    time.sleep(0.05)
        _emit(
            {
                "event": "terminal",
                "final_status": "OK" if fail_token is None else "FAILED",
                "fail_token": fail_token,
                "trace_id": trace_id,
                "last_cycle_id": last_cycle_id,
                "pid": pid,
                "hostname": hostname,
                "owner_id": owner_id,
                "spec_version_bound": SPEC_VERSION_BOUND,
            }
        )


if __name__ == "__main__":
    raise SystemExit(run())
