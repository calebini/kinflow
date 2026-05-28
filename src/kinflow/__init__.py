from .daemon import (
    DaemonConfig,
    DaemonRuntime,
    FairnessTracker,
    ReconnectState,
    validate_daemon_config,
)
from .engine import FamilySchedulerV0
from .models import DeliveryTarget
from .oc_adapter import OpenClawGatewayAdapter
from .reason_codes import ReasonCode

_TICKERD_EXPORTS = {
    "KinflowModeReader",
    "KinflowReconciler",
    "KinflowWorkItemProcessor",
    "KinflowWorkItemSource",
}

__all__ = [
    "FamilySchedulerV0",
    "DeliveryTarget",
    "ReasonCode",
    "OpenClawGatewayAdapter",
    "DaemonConfig",
    "DaemonRuntime",
    "FairnessTracker",
    "ReconnectState",
    "validate_daemon_config",
    "KinflowModeReader",
    "KinflowReconciler",
    "KinflowWorkItemProcessor",
    "KinflowWorkItemSource",
]


def __getattr__(name: str) -> object:
    if name in _TICKERD_EXPORTS:
        from . import tickerd_runtime

        return getattr(tickerd_runtime, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
