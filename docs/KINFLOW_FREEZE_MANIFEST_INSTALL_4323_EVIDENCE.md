# KINFLOW Freeze Manifest Install Evidence (run_code 4323)

## Lint preflight

```bash
cd /home/agent/projects/apps/kinflow
python3 -m compileall -q src scripts tests && echo LINT_PASS_NORMALIZED
```

Observed output:
- `LINT_PASS_NORMALIZED`

## Path integrity check (all pinned artifacts)

```text
requirements_master	v0	/home/agent/projects/apps/kinflow/requirements/KINFLOW_MASTER_REQUIREMENTS_UNIFIED_V0.md	e2567d2d15269716808a72908133e289664f4c7ba4606f1add61e30b18de9933
architecture_master	v0	/home/agent/projects/apps/kinflow/architecture/KINFLOW_V0_ARCHITECTURE_BRIEF_MASTER.md	d4a5835efe0f50a1b8c5b26a8934f0331377f95d19bf6ebc4319025214ad34ae
persistence_spec_master	v0.2.6	/home/agent/projects/apps/kinflow/specs/KINFLOW_DURABLE_PERSISTENCE_SPEC_MASTER_v0.2.6.md	13442151b609748c59d820ee4e37d91ca9ca18a4732caf7ba241c3675a537e36
comms_adapter_contract_master	v0.1.7	/home/agent/projects/apps/kinflow/specs/KINFLOW_COMMS_ADAPTER_CONTRACT_MASTER_v0.1.7.md	fdf01560699d1ca6c9e12b4b0e83a9d221e28a3d2ae1f423b366e40308325cd0
production_plan_checklist_master	master-unversioned	/home/agent/projects/apps/kinflow/specs/KINFLOW_PRODUCTION_PLAN_CHECKLIST_MASTER.md	c9911f9029b148986795c01fc5acc90764962ef866b864a9ee1039f76188167c
```

Observed result:
- `PATH_INTEGRITY_CHECK:PASS`
- no missing paths

## Installed freeze manifest

- Path: `/home/agent/projects/apps/kinflow/specs/KINFLOW_CONTRACT_FREEZE_MANIFEST_PHASE0_5.md`
- sha256: `fe9acbbff8f49d6c56098fc766f38b54b7531b90a2022daa98671e0e9afb6c24`

## README pointer evidence

### Before snippet (captured pre-edit)
```md
- `docs/KINFLOW_V0_KNUTH_LANDING_HANDOFF.md` — landing handoff
- `docs/PROJECT_RENAME_CTX002_TO_KINFLOW.md` — rename/migration note
```

### After snippet
```md
- `docs/KINFLOW_V0_KNUTH_LANDING_HANDOFF.md` — landing handoff
- `docs/PROJECT_RENAME_CTX002_TO_KINFLOW.md` — rename/migration note
- `specs/KINFLOW_CONTRACT_FREEZE_MANIFEST_PHASE0_5.md` — Phase 0.5 canonical freeze manifest (pinned versions + hashes + change-control)
```

## Backlog board pointer evidence

### Before snippet (captured pre-edit)
```md
- [CTX-002] Family scheduling system (Caleb+wife) w reminders — owner: Caleb — priority(P0) — due(none) — project(kinflow) (foreman_preferred: yes)
  - Direction draft: `/home/agent/projects/apps/kinflow/requirements/KINFLOW_MASTER_REQUIREMENTS_UNIFIED_V0.md`
  - Comms adapter spec: `/home/agent/projects/apps/kinflow/specs/KINFLOW_COMMS_ADAPTER_CONTRACT_MASTER_v0.1.7.md`
  - Production checklist: `/home/agent/projects/apps/kinflow/specs/KINFLOW_PRODUCTION_PLAN_CHECKLIST_MASTER.md`
```

### After snippet
```md
- [CTX-002] Family scheduling system (Caleb+wife) w reminders — owner: Caleb — priority(P0) — due(none) — project(kinflow) (foreman_preferred: yes)
  - Direction draft: `/home/agent/projects/apps/kinflow/requirements/KINFLOW_MASTER_REQUIREMENTS_UNIFIED_V0.md`
  - Comms adapter spec: `/home/agent/projects/apps/kinflow/specs/KINFLOW_COMMS_ADAPTER_CONTRACT_MASTER_v0.1.7.md`
  - Production checklist: `/home/agent/projects/apps/kinflow/specs/KINFLOW_PRODUCTION_PLAN_CHECKLIST_MASTER.md`
  - Phase 0.5 freeze manifest: `/home/agent/projects/apps/kinflow/specs/KINFLOW_CONTRACT_FREEZE_MANIFEST_PHASE0_5.md`
```
