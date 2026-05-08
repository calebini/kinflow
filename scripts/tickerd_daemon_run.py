from __future__ import annotations

import os
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ctx002_v0.tickerd_runtime import (  # noqa: E402
    KinflowEventSink,
    KinflowHealthSink,
    KinflowModeReader,
    KinflowReconciler,
    KinflowWorkItemProcessor,
    KinflowWorkItemSource,
    ensure_tickerd_importable,
)

ensure_tickerd_importable()

from tickerd.config import TickerdConfig  # noqa: E402
from tickerd.kernel import RuntimeKernel  # noqa: E402
from tickerd.locks import FileLockBackend, OwnershipError  # noqa: E402
from tickerd.runner import ForegroundRunner  # noqa: E402
from tickerd.types import HealthFailMode, ReconnectStrategy  # noqa: E402

from scripts.daemon_run import (  # noqa: E402
    DispatchCallbacks,
    RunnerExit,
    build_oc_adapter_binding,
    ensure_dispatch_path_wired,
    ensure_reason_codes_compatibility,
    load_runner_config,
    resolve_db_path,
    validate_version_bindings,
    write_health,
    write_state_stamp,
    _emit,
)
from ctx002_v0.persistence.store import SqliteStateStore  # noqa: E402


def build_tickerd_config(cfg: object, env: dict[str, str] | None = None) -> TickerdConfig:
    env = env or os.environ

    def int_env(name: str, default: int) -> int:
        raw = env.get(name)
        return int(raw) if raw not in {None, ""} else default

    return TickerdConfig(
        tick_interval_ms=int(getattr(cfg, "tick_ms")),
        reconcile_interval_ms=int_env("KINFLOW_RECONCILE_TICK_MS", max(5000, int(getattr(cfg, "tick_ms")) * 5)),
        max_work_items_per_tick=int_env("KINFLOW_MAX_DUE_BATCH_SIZE", 100),
        max_reconcile_batches_per_tick=int_env("KINFLOW_MAX_RECONCILE_BATCHES_PER_TICK", 1),
        max_health_age_ms=int_env("KINFLOW_MAX_HEALTH_AGE_MS", max(1000, int(getattr(cfg, "tick_ms")) * 2)),
        health_fail_mode=HealthFailMode.NON_STRICT,
        health_emit_interval_ms=int(getattr(cfg, "tick_ms")),
        shutdown_grace_ms=int(getattr(cfg, "shutdown_grace_ms")),
        lock_timeout_ms=int(getattr(cfg, "lock_timeout_ms")),
        owner_stale_after_ms=int(getattr(cfg, "stale_threshold_ms")),
        owner_heartbeat_interval_ms=int(getattr(cfg, "tick_ms")),
        reconnect_strategy=ReconnectStrategy.FIXED,
        reconnect_backoff_ms=int_env("KINFLOW_DB_RECONNECT_BACKOFF_MS", 100),
        reconnect_max_attempts=int_env("KINFLOW_DB_RECONNECT_MAX_ATTEMPTS", 3),
        max_consecutive_fatal_cycles=int(getattr(cfg, "max_consecutive_fatal_cycles")),
    )


def build_kernel(
    *,
    config: TickerdConfig,
    store: SqliteStateStore,
    callbacks: DispatchCallbacks,
    event_sink: KinflowEventSink,
) -> RuntimeKernel:
    return RuntimeKernel(
        config,
        mode_reader=KinflowModeReader(store.get_runtime_mode),
        work_source=KinflowWorkItemSource(callbacks.list_candidates),
        processor=KinflowWorkItemProcessor(callbacks.process_candidate, emit_event=event_sink.emit),
        reconciler=KinflowReconciler(callbacks.run_reconcile),
        event_sink=event_sink,
    )


def run(*, max_cycles: int | None = None, install_signal_handlers: bool = True) -> int:
    pid = os.getpid()
    hostname = socket.gethostname()
    owner_id = f"{hostname}:{pid}:{int(time.time())}"
    trace_id = f"tickerd-runner-{pid}-{int(time.time() * 1000)}"
    cfg = None
    store: SqliteStateStore | None = None
    try:
        cfg = load_runner_config()
        validate_version_bindings(cfg)
        db_path = resolve_db_path(cfg)
        event_sink = KinflowEventSink(_emit)

        store = SqliteStateStore.from_path(db_path)
        ensure_reason_codes_compatibility(store)
        oc_adapter = build_oc_adapter_binding()
        adapter_bound = bool(
            oc_adapter is not None
            and hasattr(oc_adapter, "send")
            and callable(getattr(oc_adapter, "send", None))
        )
        if not adapter_bound:
            raise RunnerExit("DISPATCH_ADAPTER_BINDING_INVALID", "oc adapter binding missing or non-callable")

        callbacks = DispatchCallbacks(
            store,
            event_sink.emit,
            oc_adapter=oc_adapter,
            cfg=cfg,
            allow_fallback=os.environ.get("KINFLOW_ALLOW_WHATSAPP_FALLBACK") == "1",
            force_bypass=os.environ.get("KINFLOW_FORCE_WHATSAPP_BYPASS") == "1",
        )
        ensure_dispatch_path_wired(callbacks)
        write_state_stamp(cfg)

        tickerd_config = build_tickerd_config(cfg)
        kernel = build_kernel(config=tickerd_config, store=store, callbacks=callbacks, event_sink=event_sink)
        runner = ForegroundRunner(
            tickerd_config,
            kernel=kernel,
            lock_backend=FileLockBackend(cfg.lock_path, cfg.owner_meta_path),
            health_sink=KinflowHealthSink(write_health, cfg),
            event_sink=event_sink,
            owner_id=owner_id,
            install_signal_handlers=install_signal_handlers,
        )
        result = runner.run(max_cycles=max_cycles)
        _emit(
            {
                "event": "terminal",
                "final_status": "OK" if result.exit_code == 0 else "FAILED",
                "reason": result.reason,
                "cycles_completed": result.cycles_completed,
                "trace_id": kernel.trace_id,
                "owner_id": owner_id,
            }
        )
        return result.exit_code
    except OwnershipError as exc:
        fail_token = "LOCK_ACQUIRE_FAILED"
        _emit(
            {
                "event": "runner_fail_stop",
                "fail_token": fail_token,
                "error": str(exc),
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
                    last_successful_cycle_id=None,
                    last_failure_reason_code=fail_token,
                )
            except Exception:
                pass
        return 1
    except RunnerExit as exc:
        _emit(
            {
                "event": "runner_fail_stop",
                "fail_token": exc.fail_token,
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
                    last_successful_cycle_id=None,
                    last_failure_reason_code=exc.fail_token,
                )
            except Exception:
                pass
        return 1
    finally:
        if store is not None:
            store.conn.close()


if __name__ == "__main__":
    raise SystemExit(run())
