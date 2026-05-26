# Kinflow Specs

Normative Kinflow design and compatibility promises live here.

## Versioning Standard

Kinflow uses the Cortext1 one-way contract pinning model:

```text
Versions communicate compatibility.
Hashes prove exact reviewed artifacts.
Tests prove behavior.
The freeze manifest is one-way authoritative.
```

Runtime declarations live in `src/kinflow/contract_versions.py`.

Release-critical artifacts are pinned in `KINFLOW_CONTRACT_FREEZE_MANIFEST_PHASE0_5.md`.

After changing specs, contracts, runtime declarations, migrations, or public behavior, run:

```bash
python3 scripts/verify_contract_pins.py
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v
```

## Canonical Artifacts

- `KINFLOW_CONTRACT_FREEZE_MANIFEST_PHASE0_5.md`
- `KINFLOW_PRODUCTION_PLAN_CHECKLIST_MASTER.md`
- `KINFLOW_DURABLE_PERSISTENCE_SPEC_MASTER_v0.2.6.md`
- `KINFLOW_COMMS_ADAPTER_CONTRACT_MASTER_v0.1.7.md`
- `KINFLOW_OC_ADAPTER_IMPLEMENTATION_SPEC_MASTER_v0.2.4.md`
- `KINFLOW_DAEMON_RUNTIME_CONTRACT_MASTER_v0.1.4.md`
- `KINFLOW_DAEMON_DEPLOYMENT_CONTRACT_MASTER_v0.1.4.md`
- `KINFLOW_DAEMON_RUNNER_IMPLEMENTATION_SPEC_MASTER_v0.1.3.md`
- `KINFLOW_DISPATCHER_OC_ADAPTER_INTEGRATION_ADDENDUM_v0.1.7.md`
- `KINFLOW_DISPATCHER_OC_ADAPTER_INTEGRATION_ADDENDUM_v0.1.7b.md`
- `KINFLOW_NOTIFICATION_RENDERING_MIN_SPEC_v0.5.3.md`
- `KINFLOW_REASON_CODES_CANONICAL.md`
- `KINFLOW_PER_EVENT_DESTINATION_SCOPE_MASTER_v1.1.md`
- `KINFLOW_PER_EVENT_DESTINATION_CONTRACT_MASTER_v0.1.6.md`
- `KINFLOW_PER_EVENT_DESTINATION_CONTRACT_MASTER_v0.1.9.md`

## Daemon Boundary

Kinflow consumes the external Cortext `tickerd` component for reusable daemon-kernel semantics. Kinflow-owned domain behavior remains here and is exposed to `tickerd` through `src/kinflow/tickerd_runtime.py`.
