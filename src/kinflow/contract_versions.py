from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContractDeclaration:
    name: str
    version: str
    artifact_path: str


IMPLEMENTED_CONTRACTS: tuple[ContractDeclaration, ...] = (
    ContractDeclaration(
        name="daemon_runtime",
        version="v0.1.4",
        artifact_path="specs/KINFLOW_DAEMON_RUNTIME_CONTRACT_MASTER_v0.1.4.md",
    ),
    ContractDeclaration(
        name="daemon_deployment",
        version="v0.1.4",
        artifact_path="specs/KINFLOW_DAEMON_DEPLOYMENT_CONTRACT_MASTER_v0.1.4.md",
    ),
    ContractDeclaration(
        name="daemon_runner",
        version="v0.1.3",
        artifact_path="specs/KINFLOW_DAEMON_RUNNER_IMPLEMENTATION_SPEC_MASTER_v0.1.3.md",
    ),
    ContractDeclaration(
        name="durable_persistence",
        version="v0.2.8",
        artifact_path="specs/KINFLOW_DURABLE_PERSISTENCE_SPEC_MASTER_v0.2.6.md",
    ),
    ContractDeclaration(
        name="comms_adapter",
        version="v0.1.8",
        artifact_path="specs/KINFLOW_COMMS_ADAPTER_CONTRACT_MASTER_v0.1.7.md",
    ),
    ContractDeclaration(
        name="oc_adapter",
        version="v0.2.5",
        artifact_path="specs/KINFLOW_OC_ADAPTER_IMPLEMENTATION_SPEC_MASTER_v0.2.4.md",
    ),
    ContractDeclaration(
        name="reason_codes",
        version="v1.0.6",
        artifact_path="specs/KINFLOW_REASON_CODES_CANONICAL.md",
    ),
    ContractDeclaration(
        name="notification_rendering",
        version="v0.5.3",
        artifact_path="specs/KINFLOW_NOTIFICATION_RENDERING_MIN_SPEC_v0.5.3.md",
    ),
)


IMPLEMENTED_CONTRACT_BY_NAME = {contract.name: contract for contract in IMPLEMENTED_CONTRACTS}
