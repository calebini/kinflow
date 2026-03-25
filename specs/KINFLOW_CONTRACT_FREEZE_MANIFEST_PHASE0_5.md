# KINFLOW Contract Freeze Manifest — Phase 0.5

status: canonical
freeze_phase: 0.5
freeze_timestamp_utc: 2026-03-25T13:25:00Z
installed_by_instruction_id: KINFLOW-R5-RECIPROCAL-PIN-MODEL-CORRECTION-20260325-001
run_code: 4359

## 1) Pinned canonical artifacts (authoritative one-way source: version + absolute path + sha256)

| Hash ID | Artifact | Version | Absolute Path | sha256 |
|---|---|---|---|---|
| `FRZ-REQ-V0` | Requirements master | v0 | `/home/agent/projects/apps/kinflow/requirements/KINFLOW_MASTER_REQUIREMENTS_UNIFIED_V0.md` | `e2567d2d15269716808a72908133e289664f4c7ba4606f1add61e30b18de9933` |
| `FRZ-ARCH-V0` | Architecture master | v0 | `/home/agent/projects/apps/kinflow/architecture/KINFLOW_V0_ARCHITECTURE_BRIEF_MASTER.md` | `d4a5835efe0f50a1b8c5b26a8934f0331377f95d19bf6ebc4319025214ad34ae` |
| `FRZ-PERSIST-V028` | Persistence spec master | v0.2.8 | `/home/agent/projects/apps/kinflow/specs/KINFLOW_DURABLE_PERSISTENCE_SPEC_MASTER_v0.2.6.md` | `469542273fe49203f6df85f38cf2153e6bcabf8d48ff5e87758858ebe75df6ec` |
| `FRZ-COMMS-V018` | Comms adapter contract master | v0.1.8 | `/home/agent/projects/apps/kinflow/specs/KINFLOW_COMMS_ADAPTER_CONTRACT_MASTER_v0.1.7.md` | `82833506d7d65e2528c027e95b9ed650f50b593d2e7ecbba94b8425be827f01f` |
| `FRZ-DAEMON-V014` | Daemon runtime contract master | v0.1.4 | `/home/agent/projects/apps/kinflow/specs/KINFLOW_DAEMON_RUNTIME_CONTRACT_MASTER_v0.1.4.md` | `50111cf0173b2023ad92a0c7b08ceae0e85163d3fc117234dc8d400ac8beaded` |
| `FRZ-OCADAPTER-V025` | OC adapter implementation spec master | v0.2.5 | `/home/agent/projects/apps/kinflow/specs/KINFLOW_OC_ADAPTER_IMPLEMENTATION_SPEC_MASTER_v0.2.4.md` | `23b99efcb3bfc8b547a2a8e2a67e58fa226c7f02ce689da64d365f5b7adabd4d` |
| `FRZ-REASON-V103` | Reason-code canonical registry | v1.0.3 | `/home/agent/projects/apps/kinflow/specs/KINFLOW_REASON_CODES_CANONICAL.md` | `7aa08628acf0633480c5f496fc632f24226cdfabad8aa8b9c34ab68e37d04742` |
| `FRZ-CHECKLIST-MASTER` | Production plan checklist master | master-unversioned | `/home/agent/projects/apps/kinflow/specs/KINFLOW_PRODUCTION_PLAN_CHECKLIST_MASTER.md` | `cfdff1107bebdef63ccd6ea07d97ad68f59a85117a1bfff811f4aa1c39e396f9` |


## 1.1) Authority model and checklist binding semantics

- This freeze manifest is the sole authoritative source of canonical artifact hash pins used by gate-critical validation.
- Downstream checklists and reports MUST reference freeze entries by stable pointer (`artifact_path` and/or `Hash ID`).
- Any hash displayed outside this manifest is informational/non-gating unless explicitly copied from this manifest during the same validation run.

## 2) Declared Tier-3 critical dimensions (copied from active contracts)

Copied from:
`/home/agent/projects/apps/kinflow/specs/KINFLOW_COMMS_ADAPTER_CONTRACT_MASTER_v0.1.7.md`

1. Schema enforceability
2. Reason-code determinism
3. Retry determinism + attempt traceability
4. Replay/idempotency determinism
5. Capability conformance integrity
6. Correlation propagation integrity

## 3) Phase-1 implementation change-control rules (under freeze)

### 3.1 Allowed without re-freeze

The following MAY change without re-freeze if all pinned artifact hashes remain unchanged:
- additive implementation files (code/tests/docs/runbooks) under `/home/agent/projects/apps/kinflow/**`
- evidence documents, verification outputs, and operator-facing usage docs
- backlog execution notes that do not alter pinned canonical artifact semantics

### 3.2 Mandatory re-freeze triggers

Any of the following MUST trigger a new freeze manifest revision before continued implementation:
1. Any pinned artifact hash change.
2. Any version bump of pinned canonical artifacts.
3. Any change to Tier-3 critical dimensions.
4. Any change to declared couplings or deterministic gate behavior in pinned contracts.
5. Any scope expansion that alters Phase 0.5 contract boundaries.

### 3.3 Exception approval roles

Default rule: no exceptions.

If exception path is requested, required approvers:
- Product owner: Caleb (requester)
- Spec authority: Tert (architecture/policy)
- Build authority: Vitruvius (implementation integrator)

Exception record MUST include:
- explicit reason
- approved scope delta
- affected artifact paths
- temporary validity window
- required follow-up re-freeze instruction

## 4) Architecture decision discoverability pins

Issue #3 architecture decision (authoritative):
- `/home/agent/projects/apps/kinflow/docs/KINFLOW_ARCH_DECISION_ISSUE3_ADAPTER_RESULTS_VS_DELIVERY_ATTEMPTS_2026-03-24.md`

Post-Issue #3 spec re-baseline declaration:
- `/home/agent/projects/apps/kinflow/docs/KINFLOW_SPEC_BASELINE_DECLARATION_POST_ISSUE3_2026-03-24.md`

## 5) Freeze violation handling

### 5.1 Deterministic block condition

Implementation progression is BLOCKED when any of these are true:
- any pinned artifact is missing
- any pinned artifact sha256 differs from this manifest
- any pinned artifact version differs from this manifest
- Tier-3 critical dimensions diverge from this manifest

Validation rule (gate-critical): hash/version checks MUST read authoritative pins from §1 of this freeze manifest only.

Validation rule (non-gating): reciprocal mismatch in checklist/report informational hash displays MUST NOT hard-fail gates when freeze-authoritative pins validate.

### 5.2 Required evidence for override

Override requires all of:
1. Explicit instruction packet with execute cue.
2. Diff + hash evidence for all changed pinned artifacts.
3. Updated freeze manifest proposal with new timestamp/version/hash table.
4. Named approvers and approval acknowledgment.
5. Rollback instructions to last known good freeze state.

Without this evidence, block remains in force.
