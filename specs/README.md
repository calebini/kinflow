# Kinflow Specs Index

Canonical specs for the repository.

## Versioning Standard

Kinflow uses the Cortext1 one-way contract pinning model:

```text
Versions communicate compatibility.
Hashes prove exact reviewed artifacts.
Tests prove behavior.
The freeze manifest is one-way authoritative.
```

Runtime code declares implemented spec/contract versions in `src/ctx002_v0/contract_versions.py`.
Release-critical artifacts are pinned in `KINFLOW_CONTRACT_FREEZE_MANIFEST_PHASE0_5.md`.
Run `python3 scripts/verify_contract_pins.py` after changing specs, contracts, runtime declarations, or pinned artifacts.

- `KINFLOW_DAEMON_RUNTIME_CONTRACT_MASTER_v0.1.4.md`
- `KINFLOW_DAEMON_DEPLOYMENT_CONTRACT_MASTER_v0.1.4.md`
- `KINFLOW_DAEMON_RUNNER_IMPLEMENTATION_SPEC_MASTER_v0.1.3.md`

Daemon implementation note:
Kinflow consumes the external Cortext `tickerd` component (`../tickerd`) for reusable daemon-kernel semantics. Kinflow-owned domain behavior remains in Kinflow and is exposed to `tickerd` through the service-specific adapter in `src/ctx002_v0/tickerd_runtime.py`.
- `KINFLOW_COMMS_ADAPTER_CONTRACT_MASTER_v0.1.8.md`
- `KINFLOW_DISPATCHER_OC_ADAPTER_INTEGRATION_ADDENDUM_v0.1.7.md`
- `KINFLOW_DISPATCHER_OC_ADAPTER_INTEGRATION_ADDENDUM_v0.1.7b.md`
- `KINFLOW_OC_ADAPTER_IMPLEMENTATION_SPEC_MASTER_v0.2.4.md`
- `KINFLOW_DURABLE_PERSISTENCE_SPEC_MASTER_v0.2.6.md`
- `KINFLOW_REASON_CODES_CANONICAL.md`
- `KINFLOW_NOTIFICATION_RENDERING_MIN_SPEC_v0.5.3.md`
- `KINFLOW_PRODUCTION_PLAN_CHECKLIST_MASTER.md`
- `KINFLOW_CONTRACT_FREEZE_MANIFEST_PHASE0_5.md`
