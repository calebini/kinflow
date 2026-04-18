# KINFLOW Spec Install Note — Dispatcher↔OC Integration Addendum v0.1.7

- instruction_id: `KINFLOW-SPEC-INSTALL-DISPATCHER-OC-INTEGRATION-V017-20260331-001`
- run_code: `4410`
- installed_at_utc: `2026-03-31T22:11:47Z`
- canonical_path: `/home/agent/projects/apps/kinflow/specs/KINFLOW_DISPATCHER_OC_ADAPTER_INTEGRATION_ADDENDUM_v0.1.7.md`
- sha256: `fc3d8e70a2c9609a65b08582053b01576debb240e8912a76ee891c6b244faeae`

## Discoverability updates

- README updated with canonical pointer to:
  - `specs/KINFLOW_DISPATCHER_OC_ADAPTER_INTEGRATION_ADDENDUM_v0.1.7.md`
- Added specs index:
  - `specs/README.md`
- Added docs index:
  - `docs/README.md`

## Preflight compatibility review (explicit YES/NO)

PF-01: OC adapter contract reference path exists and is current (`...KINFLOW_COMMS_ADAPTER_CONTRACT_MASTER_v0.1.8.md`)
- YES
- Notes: file exists at `/home/agent/projects/apps/kinflow/specs/KINFLOW_COMMS_ADAPTER_CONTRACT_MASTER_v0.1.8.md`.

PF-02: adapter result fields map to dispatcher persistence fields
- YES
- Notes:
  - `provider_receipt_ref -> provider_ref` mapping exists in `src/ctx002_v0/oc_adapter.py` (`delivery_result_to_attempt_kwargs`).
  - `provider_status_code -> provider_status_code` mapping exists.
  - `delivery_confidence -> delivery_confidence` mapping exists.
  - `result_at_utc -> result_at_utc` mapping exists.

PF-03: nullability handling for provider_ref on success is explicitly compatible with addendum §6
- NO
- Notes: current seam permits `provider_receipt_ref` as optional (`str | None`) and no dispatcher-level explicit WhatsApp-terminal guard is installed yet to enforce §6 success evidence requirements.

PF-04: fail-token enforcement seams exist for:
`DISPATCH_ADAPTER_BYPASS_DETECTED`, `DELIVERED_WITHOUT_ADAPTER_RESULT`, `FALLBACK_PATH_USED_WITHOUT_FLAG`
- NO
- Notes: these fail tokens are not currently implemented in dispatcher/runtime code paths.

PF-05: daemon path can bind OC adapter at startup (binding existence + callable)
- NO
- Notes: daemon startup currently wires store-backed `DispatchCallbacks`; it does not yet bind/validate an OC adapter callable at startup.

PF-06: no known hard blocker preventing first implementation slice
- YES
- Notes: no architectural blocker detected. Required work is implementation-slice wiring + guard/token enforcement and tests.
