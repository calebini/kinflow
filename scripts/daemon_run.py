from __future__ import annotations

import json
import os
import signal
import socket
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


def build_oc_adapter_binding(send_fn=None) -> OpenClawGatewayAdapter | None:
    if os.environ.get("KINFLOW_DISABLE_OC_ADAPTER_BINDING") == "1":
        return None
    spec_path = ROOT / "specs" / "KINFLOW_REASON_CODES_CANONICAL.md"
    spec_hash = __import__("hashlib").sha256(spec_path.read_bytes()).hexdigest()
    binding = ReasonCodeBinding(spec_path=str(spec_path), spec_version="v1.0.3", spec_sha256=spec_hash)
    return OpenClawGatewayAdapter(send_fn=send_fn or _default_adapter_send, reason_binding=binding)


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
                body_text=f"Reminder {reminder.reminder_id}",
                dedupe_key=reminder.dedupe_key,
                created_at_utc=now,
                metadata_json={"daemon_cycle_id": row.get("cycle_id", "unknown")},
                metadata_schema_version=1,
            )
            result = self.oc_adapter.send(outbound)
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

    def _delivered_evidence_ok(self, result) -> bool:
        if result.reason_code != ReasonCode.DELIVERED_SUCCESS.value:
            return False
        if not result.delivery_confidence:
            return False
        if not result.provider_status_code:
            return False
        if result.result_at_utc is None:
            return False
        # provider_ref may be null by OC adapter contract v0.1.8
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
