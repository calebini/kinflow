# KINFLOW Contract Freeze Manifest — Phase 0.5

status: canonical
freeze_phase: 0.5
freeze_timestamp_utc: 2026-03-21T18:17:47Z
installed_by_instruction_id: KINFLOW-FREEZE-MANIFEST-INSTALL-20260321-001
run_code: 4323

## 1) Pinned canonical artifacts (version + absolute path + sha256)

| Artifact | Version | Absolute Path | sha256 |
|---|---|---|---|
| Requirements master | v0 | `/home/agent/projects/apps/kinflow/requirements/KINFLOW_MASTER_REQUIREMENTS_UNIFIED_V0.md` | `e2567d2d15269716808a72908133e289664f4c7ba4606f1add61e30b18de9933` |
| Architecture master | v0 | `/home/agent/projects/apps/kinflow/architecture/KINFLOW_V0_ARCHITECTURE_BRIEF_MASTER.md` | `d4a5835efe0f50a1b8c5b26a8934f0331377f95d19bf6ebc4319025214ad34ae` |
| Persistence spec master | v0.2.6 | `/home/agent/projects/apps/kinflow/specs/KINFLOW_DURABLE_PERSISTENCE_SPEC_MASTER_v0.2.6.md` | `13442151b609748c59d820ee4e37d91ca9ca18a4732caf7ba241c3675a537e36` |
| Comms adapter contract master | v0.1.7 | `/home/agent/projects/apps/kinflow/specs/KINFLOW_COMMS_ADAPTER_CONTRACT_MASTER_v0.1.7.md` | `fdf01560699d1ca6c9e12b4b0e83a9d221e28a3d2ae1f423b366e40308325cd0` |
| Production plan checklist master | master-unversioned | `/home/agent/projects/apps/kinflow/specs/KINFLOW_PRODUCTION_PLAN_CHECKLIST_MASTER.md` | `c9911f9029b148986795c01fc5acc90764962ef866b864a9ee1039f76188167c` |

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

## 4) Freeze violation handling

### 4.1 Deterministic block condition

Implementation progression is BLOCKED when any of these are true:
- any pinned artifact is missing
- any pinned artifact sha256 differs from this manifest
- any pinned artifact version differs from this manifest
- Tier-3 critical dimensions diverge from this manifest

### 4.2 Required evidence for override

Override requires all of:
1. Explicit instruction packet with execute cue.
2. Diff + hash evidence for all changed pinned artifacts.
3. Updated freeze manifest proposal with new timestamp/version/hash table.
4. Named approvers and approval acknowledgment.
5. Rollback instructions to last known good freeze state.

Without this evidence, block remains in force.
