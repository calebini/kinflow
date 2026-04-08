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
    accept_mode_verification_window_sec: int
    accept_mode_open_gauge_alert_threshold: int
    accept_mode_open_gauge_alert_cycles: int


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
            accept_mode_verification_window_sec=int(env.get("KINFLOW_ACCEPT_MODE_VERIFICATION_WINDOW_SEC", "120")),
            accept_mode_open_gauge_alert_threshold=int(env.get("KINFLOW_ACCEPT_MODE_OPEN_GAUGE_ALERT_THRESHOLD", "25")),
            accept_mode_open_gauge_alert_cycles=int(env.get("KINFLOW_ACCEPT_MODE_OPEN_GAUGE_ALERT_CYCLES", "5")),
        )
    except ValueError as exc:
        raise RunnerExit("STARTUP_CONFIG_INVALID", f"invalid numeric env: {exc}") from exc

    if cfg.tick_ms <= 0 or cfg.max_consecutive_fatal_cycles <= 0:
        raise RunnerExit("STARTUP_CONFIG_INVALID", "tick/fatal threshold must be >0")
    if (
        cfg.accept_mode_verification_window_sec <= 0
        or cfg.accept_mode_open_gauge_alert_threshold <= 0
        or cfg.accept_mode_open_gauge_alert_cycles <= 0
    ):
        raise RunnerExit("STARTUP_CONFIG_INVALID", "accept-mode config values must be positive integers")
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


def ensure_reason_codes_compatibility(store: SqliteStateStore) -> None:
    upserts = [
        (ReasonCode.ACCEPTED_UNVERIFIED.value, "blocked"),
        (ReasonCode.FAILED_ACCEPTED_UNVERIFIED_TIMEOUT.value, "permanent"),
    ]
    for code, klass in upserts:
        store.conn.execute(
            "INSERT OR REPLACE INTO enum_reason_codes(code, class, active, version_tag) VALUES (?, ?, 1, ?)",
            (code, klass, "v0.2.6"),
        )
    store.conn.commit()

    for code, _ in upserts:
        row = store.conn.execute("SELECT 1 FROM enum_reason_codes WHERE code=? LIMIT 1", (code,)).fetchone()
        if row is None:
            raise RunnerExit("STARTUP_CONFIG_INVALID", f"reason code compatibility missing: {code}")


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


NON_VERIFIABLE_RECEIPT_LITERALS = {"none", "null", "n/a", "na", "placeholder", "synthetic"}
NON_VERIFIABLE_RECEIPT_PREFIXES = ("att-", "rcpt:att-", "local:")


def _classify_provider_ref_evidence(provider_ref: str | None) -> str:
    if provider_ref is None:
        return "local_non_verifiable"
    token = provider_ref.strip()
    if not token:
        return "local_non_verifiable"
    lowered = token.lower()
    if lowered in NON_VERIFIABLE_RECEIPT_LITERALS:
        return "local_non_verifiable"
    if lowered.startswith(NON_VERIFIABLE_RECEIPT_PREFIXES):
        return "local_non_verifiable"
    return "transport_verifiable"


def _provider_ref_transport_meaningful(provider_ref: str | None) -> bool:
    return _classify_provider_ref_evidence(provider_ref) == "transport_verifiable"


def _normalize_gateway_send_response(payload: dict[str, Any]) -> OpenClawSendResponseNormalized:
    # successful gateway send/no transport error -> success
    if not isinstance(payload, dict):
        raise BoundaryFailStopError("BOUNDARY_RESPONSE_UNMAPPABLE", "gateway payload not an object")

    provider_receipt_ref = None
    for key in ("messageId", "id", "receipt", "ref"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            candidate = value.strip()
            provider_receipt_ref = candidate if _provider_ref_transport_meaningful(candidate) else None
            break

    provider_confirmation_strength = "confirmed" if _provider_ref_transport_meaningful(provider_receipt_ref) else "accepted"

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
    binding = ReasonCodeBinding(spec_path=str(spec_path), spec_version="v1.0.6", spec_sha256=spec_hash)
    return OpenClawGatewayAdapter(send_fn=resolved_send_fn, reason_binding=binding)


SEAM_CLASSIFICATION_VERSION = "adapter-seam-v9"
TOKEN_ORIGIN_STAGES = {"PRE_SEND", "ADAPTER_EXECUTION", "POST_ADAPTER", "UNKNOWN"}
POST_SEND_ORIGIN_STAGES = {"ADAPTER_EXECUTION", "POST_ADAPTER", "UNKNOWN"}
ACCEPT_MODE_STATE_OPEN = "OPEN_UNVERIFIED"
ACCEPT_MODE_STATE_CLOSED_TIMEOUT = "CLOSED_TIMEOUT"
BLOCK_SUBTYPE_ACCEPT_SUCCESS_ONLY = "ACCEPT_SUCCESS_ONLY"
TRANSITION_PROMOTE = "PROMOTE_DELIVERED"
TRANSITION_DEMOTE = "DEMOTE_TIMEOUT"
POST_SEND_SEAM_TOKENS = {
    "DELIVERED_WITHOUT_ADAPTER_RESULT",
    "FALLBACK_PATH_USED_WITHOUT_FLAG",
    "DISPATCH_ADAPTER_BYPASS_DETECTED",
}
MAPPING_REQUIRED_FIELDS = (
    "normalized_outcome_class",
    "provider_confirmation_strength",
    "provider_status_code",
    "provider_receipt_ref",
    "raw_reason_code",
)
ALLOWED_NORMALIZED_OUTCOMES = {"success", "transient", "permanent", "blocked", "suppressed", "unknown"}
ALLOWED_CONFIRMATION_STRENGTHS = {"confirmed", "accepted", "none"}
SEAM_REASON_BY_BRANCH = {
    "A": ReasonCode.FAILED_ADAPTER_RESULT_MISSING.value,
    "B": ReasonCode.FAILED_ADAPTER_RESULT_INVALID.value,
    "C": ReasonCode.FAILED_ADAPTER_RESULT_UNMAPPABLE.value,
}


@dataclass(frozen=True)
class SeamClassification:
    seam_reason_code: str | None
    adapter_result_present: bool
    adapter_result_valid: bool
    evidence_ok: bool
    seam_branch: str
    token_origin_stage: str


class DispatchCallbacks:
    def __init__(
        self,
        store: SqliteStateStore,
        emit_fn,
        *,
        oc_adapter: OpenClawGatewayAdapter,
        cfg: RunnerConfig,
        allow_fallback: bool = False,
        force_bypass: bool = False,
    ) -> None:
        self.store = store
        self.emit = emit_fn
        self.oc_adapter = oc_adapter
        self.cfg = cfg
        self.allow_fallback = allow_fallback
        self.force_bypass = force_bypass
        self.contract_integrity_fail_total = 0
        self.accepted_unverified_total = 0
        self.accepted_unverified_promoted_total = 0
        self.accepted_unverified_demoted_total = 0
        self.accepted_unverified_open_gauge = 0
        self.accepted_unverified_open_gauge_consecutive = 0

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
                return self._route_post_send_failure(
                    reminder=reminder,
                    now=now,
                    path_id="whatsapp-daemon",
                    fail_token="DISPATCH_ADAPTER_BYPASS_DETECTED",
                    token_origin_stage="POST_ADAPTER",
                    adapter_result=None,
                    adapter_exception=None,
                )
            if self.oc_adapter is None:
                if not self.allow_fallback:
                    return self._route_post_send_failure(
                        reminder=reminder,
                        now=now,
                        path_id="whatsapp-daemon",
                        fail_token="FALLBACK_PATH_USED_WITHOUT_FLAG",
                        token_origin_stage="POST_ADAPTER",
                        adapter_result=None,
                        adapter_exception=None,
                    )
                return self._persist_non_terminal_failure(
                    reminder,
                    ReasonCode.FAILED_CONFIG_INVALID_TARGET.value,
                    "fallback send disabled",
                    now,
                )

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
            adapter_result = None
            adapter_exception: Exception | None = None
            fail_token = None
            token_origin_stage = "ADAPTER_EXECUTION"
            try:
                adapter_result = self.oc_adapter.send(outbound)
            except Exception as exc:
                adapter_exception = exc
                if isinstance(exc, BoundaryFailStopError):
                    fail_token = exc.code
                else:
                    fail_token = "DELIVERED_WITHOUT_ADAPTER_RESULT"
            if adapter_result is not None and not self._delivered_evidence_ok(adapter_result):
                fail_token = "DELIVERED_WITHOUT_ADAPTER_RESULT"

            classification = self._classify_post_send_seam(
                adapter_result=adapter_result,
                adapter_exception=adapter_exception,
                fail_token=fail_token,
                token_origin_stage=token_origin_stage,
            )
            self._validate_v12_weak_evidence_invariants(
                adapter_result=adapter_result,
                classification=classification,
                reminder_id=reminder.reminder_id,
            )
            if classification.seam_branch in {"A", "B", "C"}:
                return self._route_post_send_failure(
                    reminder=reminder,
                    now=now,
                    path_id="whatsapp-daemon",
                    fail_token=fail_token,
                    token_origin_stage=token_origin_stage,
                    adapter_result=adapter_result,
                    adapter_exception=adapter_exception,
                    attempt_id=outbound.attempt_id,
                )

            if adapter_result is not None and self._is_accept_mode_candidate(adapter_result):
                return self._assign_accept_mode_unverified(
                    reminder=reminder,
                    now=now,
                    attempt_id=outbound.attempt_id,
                    fail_token=fail_token,
                )

            if adapter_result is None:
                return self._route_post_send_failure(
                    reminder=reminder,
                    now=now,
                    path_id="whatsapp-daemon",
                    fail_token="DELIVERED_WITHOUT_ADAPTER_RESULT",
                    token_origin_stage=token_origin_stage,
                    adapter_result=None,
                    adapter_exception=None,
                    attempt_id=outbound.attempt_id,
                )

            reminder.status = "delivered"
            self.store.update_reminder(reminder)
            self.store.append_delivery_attempt(
                attempt_id=outbound.attempt_id,
                reminder_id=reminder.reminder_id,
                attempt_index=reminder.attempts,
                attempted_at_utc=now,
                status="delivered",
                reason_code=adapter_result.reason_code,
                provider_ref=adapter_result.provider_receipt_ref,
                provider_status_code=adapter_result.provider_status_code,
                provider_error_text=adapter_result.provider_error_text,
                provider_accept_only=adapter_result.provider_accept_only,
                delivery_confidence=adapter_result.delivery_confidence,
                result_at_utc=adapter_result.result_at_utc,
                trace_id=adapter_result.trace_id,
                causation_id=adapter_result.causation_id,
                source_adapter_attempt_id=adapter_result.attempt_id,
            )
            self._append_delivery_audit(
                reminder.reminder_id,
                ReasonCode.DELIVERED_SUCCESS,
                f"adapter_result={adapter_result.status};terminal_decision=ALLOW;reason_code={adapter_result.reason_code}",
            )
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

        open_rows = self.store.conn.execute(
            """
            SELECT attempt_id, reminder_id, attempted_at_utc, provider_ref, provider_status_code
            FROM delivery_attempts
            WHERE status='failed' AND reason_code=?
            ORDER BY attempted_at_utc ASC
            """,
            (ReasonCode.ACCEPTED_UNVERIFIED.value,),
        ).fetchall()
        open_count = 0
        for row in open_rows:
            attempt_id = row["attempt_id"]
            reminder_id = row["reminder_id"]
            accepted_at = datetime.fromisoformat(row["attempted_at_utc"])
            reminder = next((r for r in self.store.list_reminders() if r.reminder_id == reminder_id), None)
            if reminder is None:
                continue
            if self._transition_already_recorded(attempt_id=attempt_id, transition_type=TRANSITION_PROMOTE) or self._transition_already_recorded(
                attempt_id=attempt_id, transition_type=TRANSITION_DEMOTE
            ):
                continue

            provider_ref = row["provider_ref"]
            provider_status_code = row["provider_status_code"]
            if self._provider_ref_transport_meaningful(provider_ref):
                self._mutate_attempt_row(
                    attempt_id=attempt_id,
                    status="delivered",
                    reason_code=ReasonCode.DELIVERED_SUCCESS.value,
                    provider_ref=provider_ref,
                    provider_status_code=provider_status_code or "ok",
                    provider_error_text=None,
                    provider_accept_only=False,
                    delivery_confidence="provider_confirmed",
                    result_at_utc=now,
                )
                reminder.status = "delivered"
                self.store.update_reminder(reminder)
                self.accepted_unverified_promoted_total += 1
                self.emit(
                    {
                        "event": "accepted_unverified_promoted",
                        "attempt_id": attempt_id,
                        "reminder_id": reminder_id,
                        "transition_type": TRANSITION_PROMOTE,
                        "accepted_unverified_promoted_total": self.accepted_unverified_promoted_total,
                    }
                )
                self._record_transition_event(
                    reminder_id=reminder_id,
                    attempt_id=attempt_id,
                    transition_type=TRANSITION_PROMOTE,
                    reason_code=ReasonCode.DELIVERED_SUCCESS,
                    payload_suffix="accept_mode_state=CLOSED_PROMOTED;terminal_decision=BLOCK",
                )
                processed += 1
                continue

            timeout_at = accepted_at + timedelta(seconds=self.cfg.accept_mode_verification_window_sec)
            if now >= timeout_at:
                self._mutate_attempt_row(
                    attempt_id=attempt_id,
                    status="failed",
                    reason_code=ReasonCode.FAILED_ACCEPTED_UNVERIFIED_TIMEOUT.value,
                    provider_ref=None,
                    provider_status_code=None,
                    provider_error_text="verification window expired",
                    provider_accept_only=False,
                    delivery_confidence="none",
                    result_at_utc=now,
                )
                reminder.status = "failed"
                self.store.update_reminder(reminder)
                self.accepted_unverified_demoted_total += 1
                self.emit(
                    {
                        "event": "accepted_unverified_demoted",
                        "attempt_id": attempt_id,
                        "reminder_id": reminder_id,
                        "transition_type": TRANSITION_DEMOTE,
                        "accepted_unverified_demoted_total": self.accepted_unverified_demoted_total,
                    }
                )
                self._record_transition_event(
                    reminder_id=reminder_id,
                    attempt_id=attempt_id,
                    transition_type=TRANSITION_DEMOTE,
                    reason_code=ReasonCode.FAILED_ACCEPTED_UNVERIFIED_TIMEOUT,
                    payload_suffix="accept_mode_state=CLOSED_TIMEOUT;terminal_decision=BLOCK",
                )
                processed += 1
            else:
                open_count += 1
                self._append_delivery_audit(
                    reminder_id,
                    ReasonCode.ACCEPTED_UNVERIFIED,
                    "accept_mode_state=OPEN_UNVERIFIED;allowed_blocking_reason=ACCEPTED_UNVERIFIED_OPEN_WINDOW;terminal_decision=BLOCK",
                )

        self.accepted_unverified_open_gauge = open_count
        if open_count > self.cfg.accept_mode_open_gauge_alert_threshold:
            self.accepted_unverified_open_gauge_consecutive += 1
        else:
            self.accepted_unverified_open_gauge_consecutive = 0

        if self.accepted_unverified_open_gauge_consecutive >= self.cfg.accept_mode_open_gauge_alert_cycles:
            self.emit(
                {
                    "event": "accepted_unverified_open_gauge_alert",
                    "level": "ALERT",
                    "open_gauge": open_count,
                    "threshold": self.cfg.accept_mode_open_gauge_alert_threshold,
                    "cycles": self.accepted_unverified_open_gauge_consecutive,
                }
            )

        self.emit(
            {
                "event": "reconcile_summary",
                "processed": processed,
                "at_utc": now.isoformat(),
                "accepted_unverified_open_gauge": open_count,
                "accepted_unverified_total": self.accepted_unverified_total,
                "accepted_unverified_promoted_total": self.accepted_unverified_promoted_total,
                "accepted_unverified_demoted_total": self.accepted_unverified_demoted_total,
            }
        )
        return True

    @staticmethod
    def _classify_send_evidence_ref(provider_ref: str | None) -> str:
        return _classify_provider_ref_evidence(provider_ref)

    @staticmethod
    def _provider_ref_transport_meaningful(provider_ref: str | None) -> bool:
        return _provider_ref_transport_meaningful(provider_ref)

    def _delivered_evidence_ok(self, result) -> bool:
        if result.reason_code != ReasonCode.DELIVERED_SUCCESS.value:
            return False
        if result.delivery_confidence not in {"provider_confirmed", "provider_accepted"}:
            return False
        if not result.provider_status_code:
            return False
        if result.result_at_utc is None:
            return False
        if not self._provider_ref_transport_meaningful(result.provider_receipt_ref):
            return False
        return True

    @staticmethod
    def _is_weak_evidence_tuple_schema_valid(result: Any) -> bool:
        if result is None:
            return False
        if getattr(result, "status", None) != "DELIVERED":
            return False
        if getattr(result, "reason_code", None) != ReasonCode.DELIVERED_SUCCESS.value:
            return False
        if getattr(result, "delivery_confidence", None) != "provider_accepted":
            return False
        if getattr(result, "provider_accept_only", None) is not True:
            return False
        if not isinstance(getattr(result, "provider_status_code", None), (str, type(None))):
            return False
        if not isinstance(getattr(result, "provider_receipt_ref", None), (str, type(None))):
            return False
        return getattr(result, "result_at_utc", None) is not None

    def _is_accept_mode_candidate(self, result) -> bool:
        if not self._is_weak_evidence_tuple_schema_valid(result):
            return False
        return not self._provider_ref_transport_meaningful(result.provider_receipt_ref)

    def _record_transition_event(
        self,
        *,
        reminder_id: str,
        attempt_id: str,
        transition_type: str,
        reason_code: ReasonCode,
        payload_suffix: str,
    ) -> None:
        payload = (
            f"attempt_id={attempt_id};transition_type={transition_type};"
            f"transition_idempotency_key={attempt_id}:{transition_type};{payload_suffix}"
        )
        self._append_delivery_audit(reminder_id, reason_code, payload)

    def _transition_already_recorded(self, *, attempt_id: str, transition_type: str) -> bool:
        token = f"transition_idempotency_key={attempt_id}:{transition_type}"
        row = self.store.conn.execute(
            "SELECT 1 FROM audit_log WHERE payload_json LIKE ? LIMIT 1",
            (f"%{token}%",),
        ).fetchone()
        return row is not None

    def _mutate_attempt_row(
        self,
        *,
        attempt_id: str,
        status: str,
        reason_code: str,
        provider_ref: str | None,
        provider_status_code: str | None,
        provider_error_text: str | None,
        provider_accept_only: bool,
        delivery_confidence: str,
        result_at_utc: datetime,
    ) -> None:
        self.store.conn.execute(
            """
            UPDATE delivery_attempts
            SET status=?, reason_code=?, provider_ref=?, provider_status_code=?, provider_error_text=?,
                provider_accept_only=?, delivery_confidence=?, result_at_utc=?
            WHERE attempt_id=?
            """,
            (
                status,
                reason_code,
                provider_ref,
                provider_status_code,
                provider_error_text,
                int(provider_accept_only),
                delivery_confidence,
                result_at_utc.isoformat(),
                attempt_id,
            ),
        )
        self.store.conn.commit()

    def _assign_accept_mode_unverified(
        self,
        *,
        reminder: Reminder,
        now: datetime,
        attempt_id: str,
        fail_token: str | None,
    ) -> bool:
        reminder.status = "failed"
        self.store.update_reminder(reminder)
        self.store.append_delivery_attempt(
            attempt_id=attempt_id,
            reminder_id=reminder.reminder_id,
            attempt_index=max(reminder.attempts, 1),
            attempted_at_utc=now,
            status="failed",
            reason_code=ReasonCode.ACCEPTED_UNVERIFIED.value,
            provider_ref=None,
            provider_status_code=None,
            provider_error_text=None,
            provider_accept_only=False,
            delivery_confidence="none",
            result_at_utc=now,
            trace_id="daemon_runner",
            causation_id=reminder.reminder_id,
            source_adapter_attempt_id=attempt_id,
        )
        self.accepted_unverified_total += 1
        self.emit(
            {
                "event": "accepted_unverified_assigned",
                "attempt_id": attempt_id,
                "reminder_id": reminder.reminder_id,
                "reason_code": ReasonCode.ACCEPTED_UNVERIFIED.value,
                "accept_mode_state": ACCEPT_MODE_STATE_OPEN,
                "terminal_decision": "BLOCK",
                "block_subtype": BLOCK_SUBTYPE_ACCEPT_SUCCESS_ONLY,
                "fail_token": fail_token,
                "accepted_unverified_total": self.accepted_unverified_total,
            }
        )
        self._record_transition_event(
            reminder_id=reminder.reminder_id,
            attempt_id=attempt_id,
            transition_type="ASSIGN_OPEN",
            reason_code=ReasonCode.ACCEPTED_UNVERIFIED,
            payload_suffix=(
                f"accept_mode_state={ACCEPT_MODE_STATE_OPEN};terminal_decision=BLOCK;"
                f"block_subtype={BLOCK_SUBTYPE_ACCEPT_SUCCESS_ONLY};fail_token={fail_token}"
            ),
        )
        return False

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

    @staticmethod
    def _normalize_token_origin_stage(token_origin_stage: str | None) -> str:
        if isinstance(token_origin_stage, str):
            candidate = token_origin_stage.strip().upper()
            if candidate in TOKEN_ORIGIN_STAGES:
                return candidate
        return "ADAPTER_EXECUTION"

    @staticmethod
    def _result_to_mapping_fields(adapter_result: Any) -> dict[str, Any]:
        if adapter_result is None:
            return {}

        status_to_outcome = {
            "DELIVERED": "success",
            "FAILED_TRANSIENT": "transient",
            "FAILED_PERMANENT": "permanent",
            "BLOCKED": "blocked",
            "SUPPRESSED": "suppressed",
        }
        confidence_to_strength = {
            "provider_confirmed": "confirmed",
            "provider_accepted": "accepted",
            "none": "none",
        }
        return {
            "normalized_outcome_class": status_to_outcome.get(getattr(adapter_result, "status", None), "unknown"),
            "provider_confirmation_strength": confidence_to_strength.get(
                getattr(adapter_result, "delivery_confidence", None), "none"
            ),
            "provider_status_code": getattr(adapter_result, "provider_status_code", None),
            "provider_receipt_ref": getattr(adapter_result, "provider_receipt_ref", None),
            "raw_reason_code": getattr(adapter_result, "reason_code", None),
        }

    @staticmethod
    def _mapping_fields_valid(mapping_fields: dict[str, Any]) -> bool:
        if not mapping_fields:
            return False
        if mapping_fields.get("normalized_outcome_class") not in ALLOWED_NORMALIZED_OUTCOMES:
            return False
        if mapping_fields.get("provider_confirmation_strength") not in ALLOWED_CONFIRMATION_STRENGTHS:
            return False
        if not isinstance(mapping_fields.get("provider_status_code"), (str, type(None))):
            return False
        if not isinstance(mapping_fields.get("provider_receipt_ref"), (str, type(None))):
            return False
        if not isinstance(mapping_fields.get("raw_reason_code"), (str, type(None))):
            return False
        for field in MAPPING_REQUIRED_FIELDS:
            if field not in mapping_fields:
                return False
        return True

    def _classify_post_send_seam(
        self,
        *,
        adapter_result: Any,
        adapter_exception: Exception | None,
        fail_token: str | None,
        token_origin_stage: str | None,
    ) -> SeamClassification:
        normalized_origin = self._normalize_token_origin_stage(token_origin_stage)
        adapter_result_present = adapter_result is not None
        evidence_ok = bool(adapter_result_present and self._delivered_evidence_ok(adapter_result))

        if adapter_result_present and adapter_exception is None and self._is_accept_mode_candidate(adapter_result):
            return SeamClassification(
                seam_reason_code=None,
                adapter_result_present=True,
                adapter_result_valid=True,
                evidence_ok=False,
                seam_branch="NONE",
                token_origin_stage=normalized_origin,
            )

        seam_predicate = bool(adapter_exception is not None or fail_token is not None or not evidence_ok)
        if not seam_predicate:
            return SeamClassification(
                seam_reason_code=None,
                adapter_result_present=adapter_result_present,
                adapter_result_valid=adapter_result_present,
                evidence_ok=evidence_ok,
                seam_branch="NONE",
                token_origin_stage=normalized_origin,
            )

        if adapter_exception is not None or not adapter_result_present:
            return SeamClassification(
                seam_reason_code=SEAM_REASON_BY_BRANCH["A"],
                adapter_result_present=adapter_result_present,
                adapter_result_valid=False,
                evidence_ok=evidence_ok,
                seam_branch="A",
                token_origin_stage=normalized_origin,
            )

        mapping_fields = self._result_to_mapping_fields(adapter_result)
        mapping_valid = self._mapping_fields_valid(mapping_fields)
        if not mapping_valid:
            return SeamClassification(
                seam_reason_code=SEAM_REASON_BY_BRANCH["B"],
                adapter_result_present=True,
                adapter_result_valid=False,
                evidence_ok=evidence_ok,
                seam_branch="B",
                token_origin_stage=normalized_origin,
            )

        if fail_token and fail_token not in POST_SEND_SEAM_TOKENS:
            return SeamClassification(
                seam_reason_code=SEAM_REASON_BY_BRANCH["C"],
                adapter_result_present=True,
                adapter_result_valid=True,
                evidence_ok=evidence_ok,
                seam_branch="C",
                token_origin_stage=normalized_origin,
            )

        if not evidence_ok:
            return SeamClassification(
                seam_reason_code=SEAM_REASON_BY_BRANCH["B"],
                adapter_result_present=True,
                adapter_result_valid=False,
                evidence_ok=False,
                seam_branch="B",
                token_origin_stage=normalized_origin,
            )

        return SeamClassification(
            seam_reason_code=SEAM_REASON_BY_BRANCH["B"],
            adapter_result_present=True,
            adapter_result_valid=False,
            evidence_ok=evidence_ok,
            seam_branch="B",
            token_origin_stage=normalized_origin,
        )

    def _escalate_contract_integrity_fail(self, *, reason: str, payload: dict[str, Any]) -> None:
        self.contract_integrity_fail_total += 1
        self.emit(
            {
                "event": "CONTRACT_INTEGRITY_FAIL",
                "level": "ERROR",
                "reason": reason,
                "contract_integrity_fail_total": self.contract_integrity_fail_total,
                "payload": payload,
                "run_summary_visibility": True,
            }
        )

    def _validate_errata_invariants(self, classification: SeamClassification, *, reminder_id: str) -> None:
        violates_b = classification.seam_branch == "B" and classification.adapter_result_valid is not False
        violates_c = classification.seam_branch == "C" and classification.adapter_result_valid is not True
        if not (violates_b or violates_c):
            return
        payload = {
            "reminder_id": reminder_id,
            "seam_branch": classification.seam_branch,
            "adapter_result_valid": classification.adapter_result_valid,
            "token_origin_stage": classification.token_origin_stage,
            "classification_version": SEAM_CLASSIFICATION_VERSION,
        }
        self._escalate_contract_integrity_fail(reason="ERRATA_E1_INVARIANT_VIOLATION", payload=payload)
        raise RunnerExit("ADAPTER_ALIGNMENT_SEAM_GAP", "CONTRACT_INTEGRITY_FAIL")

    def _validate_v12_weak_evidence_invariants(
        self,
        *,
        adapter_result: Any,
        classification: SeamClassification,
        reminder_id: str,
    ) -> None:
        if adapter_result is None:
            return

        status = getattr(adapter_result, "status", None)
        confidence = getattr(adapter_result, "delivery_confidence", None)
        provider_accept_only = getattr(adapter_result, "provider_accept_only", None)

        if status == "DELIVERED" and confidence == "provider_accepted" and provider_accept_only is not True:
            self._escalate_contract_integrity_fail(
                reason="V12_WEAK_EVIDENCE_TUPLE_LOCK_VIOLATION",
                payload={
                    "reminder_id": reminder_id,
                    "status": status,
                    "delivery_confidence": confidence,
                    "provider_accept_only": provider_accept_only,
                    "seam_branch": classification.seam_branch,
                    "adapter_result_valid": classification.adapter_result_valid,
                },
            )
            raise RunnerExit("ADAPTER_ALIGNMENT_SEAM_GAP", "CONTRACT_INTEGRITY_FAIL")

        is_weak_evidence_tuple = self._is_weak_evidence_tuple_schema_valid(adapter_result)
        if is_weak_evidence_tuple and classification.seam_branch != "NONE":
            self._escalate_contract_integrity_fail(
                reason="V12_WEAK_EVIDENCE_SEAM_TIEBREAK_VIOLATION",
                payload={
                    "reminder_id": reminder_id,
                    "seam_branch": classification.seam_branch,
                    "adapter_result_valid": classification.adapter_result_valid,
                    "token_origin_stage": classification.token_origin_stage,
                    "classification_version": SEAM_CLASSIFICATION_VERSION,
                },
            )
            raise RunnerExit("ADAPTER_ALIGNMENT_SEAM_GAP", "CONTRACT_INTEGRITY_FAIL")

    @staticmethod
    def _discard_provider_fields_for_seam() -> dict[str, Any]:
        return {
            "provider_ref": None,
            "provider_status_code": None,
            "delivery_confidence": "none",
        }

    def _route_post_send_failure(
        self,
        *,
        reminder: Reminder,
        now: datetime,
        path_id: str,
        fail_token: str | None,
        token_origin_stage: str | None,
        adapter_result: Any,
        adapter_exception: Exception | None,
        attempt_id: str | None = None,
    ) -> bool:
        normalized_origin = self._normalize_token_origin_stage(token_origin_stage)
        if normalized_origin not in POST_SEND_ORIGIN_STAGES:
            raise RunnerExit(
                "ADAPTER_ALIGNMENT_SEAM_GAP",
                f"post-send route violation: token_origin_stage={normalized_origin}",
            )

        classification = self._classify_post_send_seam(
            adapter_result=adapter_result,
            adapter_exception=adapter_exception,
            fail_token=fail_token,
            token_origin_stage=normalized_origin,
        )
        self._validate_v12_weak_evidence_invariants(
            adapter_result=adapter_result,
            classification=classification,
            reminder_id=reminder.reminder_id,
        )
        self._validate_errata_invariants(classification, reminder_id=reminder.reminder_id)
        if classification.seam_branch == "NONE":
            self._escalate_contract_integrity_fail(
                reason="SEAM_BRANCH_NONE_IN_POST_SEND_FAILURE",
                payload={
                    "reminder_id": reminder.reminder_id,
                    "token_origin_stage": classification.token_origin_stage,
                    "classification_version": SEAM_CLASSIFICATION_VERSION,
                },
            )
            raise RunnerExit("ADAPTER_ALIGNMENT_SEAM_GAP", "CONTRACT_INTEGRITY_FAIL")

        # E2 ordering: discard provider fields -> assign seam consequence -> build output -> persist -> emit event.
        provider_discarded = self._discard_provider_fields_for_seam()
        seam_reason_code = classification.seam_reason_code or ReasonCode.FAILED_ADAPTER_RESULT_UNMAPPABLE.value
        seam_output = {
            "attempt_id": attempt_id or f"att-{reminder.reminder_id}-{max(reminder.attempts, 1)}",
            "reminder_id": reminder.reminder_id,
            "path_id": path_id,
            "fail_token": fail_token,
            "token_origin_stage": classification.token_origin_stage,
            "seam_branch": classification.seam_branch,
            "adapter_result_present": classification.adapter_result_present,
            "adapter_result_valid": classification.adapter_result_valid,
            "evidence_ok": classification.evidence_ok,
            "terminal_decision": "BLOCK",
            "reason_code": seam_reason_code,
            "unexpected_provider_fields_present": False,
            "classification_version": SEAM_CLASSIFICATION_VERSION,
            "provider_ref": provider_discarded["provider_ref"],
            "provider_status_code": provider_discarded["provider_status_code"],
            "delivery_confidence": provider_discarded["delivery_confidence"],
            "contract_integrity_fail_total": self.contract_integrity_fail_total,
        }

        self._persist_non_terminal_failure(
            reminder,
            seam_reason_code,
            str(fail_token or (adapter_exception and str(adapter_exception)) or seam_reason_code),
            now,
            attempt_id=seam_output["attempt_id"],
        )
        self._append_delivery_audit(
            reminder.reminder_id,
            ReasonCode(seam_reason_code),
            (
                f"attempt_id={seam_output['attempt_id']};reminder_id={reminder.reminder_id};path_id={path_id};"
                f"fail_token={fail_token};token_origin_stage={classification.token_origin_stage};"
                f"adapter_result_present={classification.adapter_result_present};"
                f"adapter_result_valid={classification.adapter_result_valid};evidence_ok={classification.evidence_ok};"
                f"seam_branch={classification.seam_branch};terminal_decision=BLOCK;reason_code={seam_reason_code};"
                f"provider_ref={seam_output['provider_ref']};provider_status_code={seam_output['provider_status_code']};"
                f"delivery_confidence={seam_output['delivery_confidence']}"
            ),
        )
        self.emit({"event": "adapter_seam_failure_classified", **seam_output})
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
        ensure_reason_codes_compatibility(store)
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
            cfg=cfg,
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
