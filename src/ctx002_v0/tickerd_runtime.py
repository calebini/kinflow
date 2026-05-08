from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


def ensure_tickerd_importable() -> None:
    """Prefer an installed tickerd package, falling back to the sibling component checkout."""

    try:
        import tickerd  # noqa: F401

        return
    except ModuleNotFoundError:
        pass

    root = Path(__file__).resolve().parents[2]
    sibling_src = root.parent / "tickerd" / "src"
    if sibling_src.exists() and str(sibling_src) not in sys.path:
        sys.path.insert(0, str(sibling_src))


ensure_tickerd_importable()

from tickerd.types import CycleEnvelope, ProcessResult, ReconcileResult, RuntimeMode, WorkItem  # noqa: E402


class KinflowModeReader:
    def __init__(self, read_mode: Callable[[], str]) -> None:
        self._read_mode = read_mode

    def read_mode(self) -> RuntimeMode:
        raw = (self._read_mode() or "").strip().lower()
        if raw in {"normal", "active", "production"}:
            return RuntimeMode.ACTIVE
        if raw in {"capture_only", "observe_only"}:
            return RuntimeMode.OBSERVE_ONLY
        if raw in {"suspended", "paused", "maintenance"}:
            return RuntimeMode.SUSPENDED
        return RuntimeMode.SUSPENDED


class KinflowWorkItemSource:
    def __init__(self, list_candidates: Callable[[], Sequence[Mapping[str, Any]]]) -> None:
        self._list_candidates = list_candidates

    def list_work_items(self, envelope: CycleEnvelope, limit: int) -> list[WorkItem]:
        items: list[WorkItem] = []
        for row in list(self._list_candidates())[:limit]:
            row_dict = dict(row)
            item_id = str(row_dict.get("id") or row_dict.get("reminder_id"))
            row_dict.update(
                {
                    "cycle_id": envelope.cycle_id,
                    "trace_id": envelope.trace_id,
                    "causation_id": envelope.causation_id,
                    "runtime_mode": envelope.runtime_mode.value,
                    "scheduled_tick_ts": envelope.scheduled_tick_ts,
                    "actual_start_ts": envelope.actual_start_ts,
                }
            )
            items.append(WorkItem(item_id=item_id, payload=row_dict))
        return items


class KinflowWorkItemProcessor:
    def __init__(
        self,
        process_candidate: Callable[[dict[str, Any]], bool],
        *,
        emit_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._process_candidate = process_candidate
        self._emit_event = emit_event
        self.observed_item_ids: list[str] = []

    def process_work_item(
        self,
        item: WorkItem,
        envelope: CycleEnvelope,
        *,
        side_effects_allowed: bool,
    ) -> ProcessResult:
        row = dict(item.payload)
        if not side_effects_allowed:
            self.observed_item_ids.append(item.item_id)
            if self._emit_event is not None:
                self._emit_event(
                    {
                        "event": "dispatch_observe_only_blocked",
                        "reason_code": "OBSERVE_ONLY_BLOCKED",
                        "item_id": item.item_id,
                        "cycle_id": envelope.cycle_id,
                        "trace_id": envelope.trace_id,
                        "causation_id": envelope.causation_id,
                    }
                )
            return ProcessResult.blocked("SIDE_EFFECTS_BLOCKED")

        if self._process_candidate(row):
            return ProcessResult.processed()
        return ProcessResult.failed("PROCESSING_FAILED")


class KinflowReconciler:
    def __init__(self, run_reconcile: Callable[[], bool]) -> None:
        self._run_reconcile = run_reconcile

    def reconcile(self, envelope: CycleEnvelope, *, max_batches: int) -> ReconcileResult:
        ok = True
        processed = 0
        for _ in range(max_batches):
            ok = self._run_reconcile()
            processed += 1
            if not ok:
                break
        return ReconcileResult(ok=ok, items_scanned=processed, items_repaired=processed if ok else 0)


class KinflowEventSink:
    def __init__(self, emit: Callable[[dict[str, Any]], None]) -> None:
        self._emit = emit

    def emit(self, record: dict[str, Any]) -> None:
        self._emit(record)


class KinflowHealthSink:
    def __init__(self, write_health: Callable[..., None], cfg: object) -> None:
        self._write_health = write_health
        self._cfg = cfg

    def write(self, snapshot: object) -> None:
        state = getattr(snapshot, "state").value
        last_success = getattr(snapshot, "last_successful_cycle_id")
        last_failure = getattr(snapshot, "last_failure_reason")
        if state == "UP":
            health_state = "ready"
            is_ready = True
        elif state == "DEGRADED":
            health_state = "degraded" if last_success else "starting"
            is_ready = bool(last_success)
        else:
            health_state = "failed" if last_failure not in {None, "requested", "max_cycles_reached"} else "stopping"
            is_ready = False

        self._write_health(
            self._cfg,
            state=health_state,
            is_ready=is_ready,
            last_successful_cycle_id=last_success,
            last_failure_reason_code=last_failure,
        )


def cycle_metadata_from_row(row: Mapping[str, Any] | None) -> dict[str, str | None]:
    row = row or {}
    return {
        "cycle_id": _string_or_none(row.get("cycle_id")),
        "trace_id": _string_or_none(row.get("trace_id")),
        "causation_id": _string_or_none(row.get("causation_id")),
    }


def utc_now() -> datetime:
    return datetime.now(UTC)


def _string_or_none(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


__all__ = [
    "KinflowEventSink",
    "KinflowHealthSink",
    "KinflowModeReader",
    "KinflowReconciler",
    "KinflowWorkItemProcessor",
    "KinflowWorkItemSource",
    "cycle_metadata_from_row",
    "ensure_tickerd_importable",
    "utc_now",
]
