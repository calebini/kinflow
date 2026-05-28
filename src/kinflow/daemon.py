from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import floor
from typing import Callable, Literal
from uuid import uuid4

HealthState = Literal["DOWN", "DEGRADED", "UP"]
RuntimeMode = Literal["normal", "capture_only"]
HealthFailMode = Literal["strict", "non_strict"]
ReconnectStrategy = Literal["fixed", "linear", "exponential_capped"]

ALLOWED_BLOCKING_REASONS = {
    "CAPTURE_ONLY_BLOCKED",
    "TZ_MISSING",
    "FAILED_CONFIG_INVALID_TARGET",
    "SUPPRESSED_QUIET_HOURS",
    "FAILED_PROVIDER_PERMANENT",
    "ACCEPTED_UNVERIFIED_OPEN_WINDOW",
}


class ConfigValidationError(ValueError):
    pass


class DaemonContractNonConformant(RuntimeError):
    pass


@dataclass(frozen=True)
class DaemonConfig:
    runtime_mode: RuntimeMode
    daemon_tick_ms: int
    reconcile_tick_ms: int
    max_due_batch_size: int
    max_reconcile_batch_size: int
    max_reconcile_batches_per_tick: int
    max_tick_deferral_for_oldest_due: int
    max_health_age_ms: int
    health_fail_mode: HealthFailMode
    health_emit_interval_ms: int
    idempotency_window_hours: int
    max_retry_attempts: int
    shutdown_grace_ms: int
    db_reconnect_strategy: ReconnectStrategy
    db_reconnect_backoff_ms: int
    db_reconnect_max_attempts: int
    db_reconnect_max_backoff_ms: int | None
    max_consecutive_fatal_cycles: int
    transaction_scope_mode: Literal["per_row", "per_batch"]


def validate_daemon_config(raw: dict) -> DaemonConfig:
    required = {
        "runtime_mode",
        "daemon_tick_ms",
        "reconcile_tick_ms",
        "max_due_batch_size",
        "max_reconcile_batch_size",
        "max_reconcile_batches_per_tick",
        "max_tick_deferral_for_oldest_due",
        "max_health_age_ms",
        "health_fail_mode",
        "health_emit_interval_ms",
        "idempotency_window_hours",
        "max_retry_attempts",
        "shutdown_grace_ms",
        "db_reconnect_strategy",
        "db_reconnect_backoff_ms",
        "db_reconnect_max_attempts",
        "max_consecutive_fatal_cycles",
        "transaction_scope_mode",
    }
    missing = sorted(required - set(raw.keys()))
    if missing:
        raise ConfigValidationError(f"missing required keys: {', '.join(missing)}")

    def _must_int(name: str, minimum: int, *, gt: bool = False) -> int:
        value = raw.get(name)
        if not isinstance(value, int):
            raise ConfigValidationError(f"{name} must be int")
        if value <= minimum if gt else value < minimum:
            op = ">" if gt else ">="
            raise ConfigValidationError(f"{name} must be {op} {minimum}")
        return value

    runtime_mode = raw["runtime_mode"]
    if runtime_mode not in {"normal", "capture_only"}:
        raise ConfigValidationError("runtime_mode must be normal|capture_only")

    health_fail_mode = raw["health_fail_mode"]
    if health_fail_mode not in {"strict", "non_strict"}:
        raise ConfigValidationError("health_fail_mode must be strict|non_strict")

    strategy = raw["db_reconnect_strategy"]
    if strategy not in {"fixed", "linear", "exponential_capped"}:
        raise ConfigValidationError("db_reconnect_strategy must be fixed|linear|exponential_capped")

    tx_mode = raw["transaction_scope_mode"]
    if tx_mode not in {"per_row", "per_batch"}:
        raise ConfigValidationError("transaction_scope_mode must be per_row|per_batch")

    db_reconnect_max_backoff_ms = raw.get("db_reconnect_max_backoff_ms")
    if strategy == "exponential_capped":
        if not isinstance(db_reconnect_max_backoff_ms, int) or db_reconnect_max_backoff_ms <= 0:
            raise ConfigValidationError("db_reconnect_max_backoff_ms must be > 0 for exponential_capped")

    return DaemonConfig(
        runtime_mode=runtime_mode,
        daemon_tick_ms=_must_int("daemon_tick_ms", 1000),
        reconcile_tick_ms=_must_int("reconcile_tick_ms", 5000),
        max_due_batch_size=_must_int("max_due_batch_size", 1),
        max_reconcile_batch_size=_must_int("max_reconcile_batch_size", 1),
        max_reconcile_batches_per_tick=_must_int("max_reconcile_batches_per_tick", 1),
        max_tick_deferral_for_oldest_due=_must_int("max_tick_deferral_for_oldest_due", 1),
        max_health_age_ms=_must_int("max_health_age_ms", 0, gt=True),
        health_fail_mode=health_fail_mode,
        health_emit_interval_ms=_must_int("health_emit_interval_ms", 0, gt=True),
        idempotency_window_hours=_must_int("idempotency_window_hours", 0),
        max_retry_attempts=_must_int("max_retry_attempts", 0),
        shutdown_grace_ms=_must_int("shutdown_grace_ms", 0, gt=True),
        db_reconnect_strategy=strategy,
        db_reconnect_backoff_ms=_must_int("db_reconnect_backoff_ms", 0, gt=True),
        db_reconnect_max_attempts=_must_int("db_reconnect_max_attempts", 0, gt=True),
        db_reconnect_max_backoff_ms=db_reconnect_max_backoff_ms,
        max_consecutive_fatal_cycles=_must_int("max_consecutive_fatal_cycles", 0, gt=True),
        transaction_scope_mode=tx_mode,
    )


@dataclass
class HealthSnapshot:
    state: HealthState
    is_ready: bool
    snapshot_ts_utc: datetime
    max_health_age_ms: int
    health_fail_mode: HealthFailMode
    last_successful_cycle_id: str | None
    last_failure_reason_code: str | None


def compute_health_freshness(snapshot: HealthSnapshot, now: datetime) -> tuple[int, HealthState]:
    age_ms = int((now - snapshot.snapshot_ts_utc).total_seconds() * 1000)
    if age_ms <= snapshot.max_health_age_ms:
        return age_ms, snapshot.state
    if snapshot.health_fail_mode == "strict":
        return age_ms, "DOWN"
    return age_ms, "DEGRADED"


def reconcile_boundary_ms(now_ms: int, reconcile_tick_ms: int) -> int:
    return floor(now_ms / reconcile_tick_ms) * reconcile_tick_ms


def reconcile_due(now_ms: int, reconcile_tick_ms: int, last_reconcile_boundary_ms: int) -> tuple[bool, int]:
    boundary = reconcile_boundary_ms(now_ms, reconcile_tick_ms)
    return boundary > last_reconcile_boundary_ms, boundary


def next_tick_boundary_ms(now_ms: int, daemon_tick_ms: int) -> int:
    return floor(now_ms / daemon_tick_ms) * daemon_tick_ms + daemon_tick_ms


def compute_reconnect_delay_ms(
    strategy: ReconnectStrategy,
    base_backoff_ms: int,
    attempt_index: int,
    max_backoff_ms: int | None = None,
) -> int:
    if strategy == "fixed":
        return base_backoff_ms
    if strategy == "linear":
        return base_backoff_ms * attempt_index
    if strategy == "exponential_capped":
        if max_backoff_ms is None:
            raise DaemonContractNonConformant("missing max backoff for exponential strategy")
        return min(base_backoff_ms * (2 ** (attempt_index - 1)), max_backoff_ms)
    raise DaemonContractNonConformant(f"unknown reconnect strategy: {strategy}")


@dataclass
class ReconnectState:
    attempts: int = 0
    exhausted: bool = False
    reset_pending_cycle_success: bool = False

    def register_failure(self, config: DaemonConfig) -> int:
        if self.exhausted:
            raise DaemonContractNonConformant("reconnect already exhausted")
        self.attempts += 1
        if self.attempts > config.db_reconnect_max_attempts:
            self.exhausted = True
            raise DaemonContractNonConformant("reconnect exhausted")
        return compute_reconnect_delay_ms(
            config.db_reconnect_strategy,
            config.db_reconnect_backoff_ms,
            self.attempts,
            config.db_reconnect_max_backoff_ms,
        )

    def register_reconnect_success(self) -> None:
        self.reset_pending_cycle_success = True

    def register_cycle_success(self) -> None:
        if self.reset_pending_cycle_success:
            self.attempts = 0
            self.reset_pending_cycle_success = False


class FairnessTracker:
    def __init__(self) -> None:
        self._deferral_by_row: dict[str, int] = {}

    def record_loop(
        self, eligible_ids: list[str], processed_ids: list[str], blocked_reason_by_id: dict[str, str]
    ) -> None:
        processed = set(processed_ids)
        for rid in eligible_ids:
            reason = blocked_reason_by_id.get(rid)
            if rid in processed:
                self._deferral_by_row[rid] = 0
            elif reason in ALLOWED_BLOCKING_REASONS:
                continue
            else:
                self._deferral_by_row[rid] = self._deferral_by_row.get(rid, 0) + 1

    def deferral_tick_count(self, reminder_id: str) -> int:
        return self._deferral_by_row.get(reminder_id, 0)


class DaemonRuntime:
    def __init__(
        self,
        config: DaemonConfig,
        *,
        read_runtime_mode: Callable[[], RuntimeMode],
        list_candidates: Callable[[], list[dict]],
        process_candidate: Callable[[dict], bool],
        run_reconcile: Callable[[], bool],
        emit_event: Callable[[dict], None],
    ) -> None:
        self.config = config
        self.read_runtime_mode = read_runtime_mode
        self.list_candidates = list_candidates
        self.process_candidate = process_candidate
        self.run_reconcile = run_reconcile
        self.emit_event = emit_event

        self.trace_id = str(uuid4())
        self.cycle_seq = 0
        self.last_reconcile_boundary_ms = 0
        self.is_ready = False
        self.health_state: HealthState = "DOWN"
        self.first_successful_cycle = False

    def startup(self, now: datetime) -> HealthSnapshot:
        # Ordered startup semantics represented by event log ordering.
        self.emit_event(
            {"stage": "startup", "causation_id": f"ROOT:STARTUP:{self.trace_id}", "step": "init_health_down"}
        )
        self.health_state = "DEGRADED"
        self.is_ready = True
        snap = HealthSnapshot(
            state=self.health_state,
            is_ready=self.is_ready,
            snapshot_ts_utc=now,
            max_health_age_ms=self.config.max_health_age_ms,
            health_fail_mode=self.config.health_fail_mode,
            last_successful_cycle_id=None,
            last_failure_reason_code=None,
        )
        self.emit_event({"stage": "startup", "causation_id": f"ROOT:STARTUP:{self.trace_id}", "step": "ready_true"})
        return snap

    def run_cycle(self, scheduled_tick_ts: datetime, actual_start_ts: datetime) -> dict:
        self.cycle_seq += 1
        cycle_id = f"{self.trace_id}:{self.cycle_seq}"
        causation_id = f"ROOT:{cycle_id}"
        tick_drift_ms = int((actual_start_ts - scheduled_tick_ts).total_seconds() * 1000)

        now_ms = int(actual_start_ts.timestamp() * 1000)
        do_reconcile, boundary = reconcile_due(now_ms, self.config.reconcile_tick_ms, self.last_reconcile_boundary_ms)

        runtime_mode = self.read_runtime_mode()
        candidates = self.list_candidates()
        rows_blocked = 0
        rows_processed = 0
        success_exec = True
        blocked_reason_by_id: dict[str, str] = {}
        processed_ids: list[str] = []

        for row in candidates:
            rid = row["id"]
            if runtime_mode == "capture_only":
                rows_blocked += 1
                blocked_reason_by_id[rid] = "CAPTURE_ONLY_BLOCKED"
                self.emit_event(
                    {
                        "event": "CAPTURE_ONLY_BLOCKED",
                        "row_id": rid,
                        "cycle_id": cycle_id,
                        "trace_id": self.trace_id,
                        "causation_id": causation_id,
                    }
                )
                continue
            if self.process_candidate(row):
                rows_processed += 1
                processed_ids.append(rid)
            else:
                success_exec = False

        success_reconcile = True
        if do_reconcile:
            success_reconcile = self.run_reconcile()
            if success_reconcile:
                self.last_reconcile_boundary_ms = boundary

        cycle_success = bool(runtime_mode and success_exec and success_reconcile)
        if cycle_success and not self.first_successful_cycle:
            self.health_state = "UP"
            self.first_successful_cycle = True

        summary = {
            "event": "cycle_summary",
            "cycle_id": cycle_id,
            "trace_id": self.trace_id,
            "causation_id": causation_id,
            "scheduled_tick_ts": scheduled_tick_ts.isoformat(),
            "actual_start_ts": actual_start_ts.isoformat(),
            "tick_drift_ms": tick_drift_ms,
            "rows_scanned": len(candidates),
            "rows_processed": rows_processed,
            "rows_blocked": rows_blocked,
            "rows_failed": 0 if success_exec else 1,
            "cycle_success": cycle_success,
        }
        self.emit_event(summary)
        return summary


__all__ = [
    "ALLOWED_BLOCKING_REASONS",
    "ConfigValidationError",
    "DaemonConfig",
    "DaemonContractNonConformant",
    "DaemonRuntime",
    "FairnessTracker",
    "HealthSnapshot",
    "ReconnectState",
    "compute_health_freshness",
    "compute_reconnect_delay_ms",
    "next_tick_boundary_ms",
    "reconcile_boundary_ms",
    "reconcile_due",
    "validate_daemon_config",
]
