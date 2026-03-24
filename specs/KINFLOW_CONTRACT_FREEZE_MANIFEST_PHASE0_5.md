# KINFLOW Contract Freeze Manifest — Phase 0.5

status: canonical
freeze_phase: 0.5
freeze_timestamp_utc: 2026-03-24T13:28:00Z
installed_by_instruction_id: KINFLOW-SPEC-FAMILY-ALIGNMENT-20260324-001
run_code: 4346

## 1) Pinned canonical artifacts (version + absolute path + sha256)

| Artifact | Version | Absolute Path | sha256 |
|---|---|---|---|
| Requirements master | v0 | `/home/agent/projects/apps/kinflow/requirements/KINFLOW_MASTER_REQUIREMENTS_UNIFIED_V0.md` | `e2567d2d15269716808a72908133e289664f4c7ba4606f1add61e30b18de9933` |
| Architecture master | v0 | `/home/agent/projects/apps/kinflow/architecture/KINFLOW_V0_ARCHITECTURE_BRIEF_MASTER.md` | `d4a5835efe0f50a1b8c5b26a8934f0331377f95d19bf6ebc4319025214ad34ae` |
| Persistence spec master | v0.2.6 | `/home/agent/projects/apps/kinflow/specs/KINFLOW_DURABLE_PERSISTENCE_SPEC_MASTER_v0.2.6.md` | `eca3bfae23de10a1019c367f09918a1740b45bb85652397ff872e0307c463d36` |
| Comms adapter contract master | v0.1.7 | `/home/agent/projects/apps/kinflow/specs/KINFLOW_COMMS_ADAPTER_CONTRACT_MASTER_v0.1.7.md` | `a1eb2ece0f25fce7c85292a153d9d60d30fd98230a0774a5e5df5fef57cb46e3` |
| Daemon runtime contract master | v0.1.4 | `/home/agent/projects/apps/kinflow/specs/KINFLOW_DAEMON_RUNTIME_CONTRACT_MASTER_v0.1.4.md` | `50111cf0173b2023ad92a0c7b08ceae0e85163d3fc117234dc8d400ac8beaded` |
| OC adapter implementation spec master | v0.2.4 | `/home/agent/projects/apps/kinflow/specs/KINFLOW_OC_ADAPTER_IMPLEMENTATION_SPEC_MASTER_v0.2.4.md` | `dc1e4abdf3d034ac80328e7e32d7bda40b371ab3604b3f6b751f3fe47fc49fb6` |
| Reason-code canonical registry | v1.0.2 | `/home/agent/projects/apps/kinflow/specs/KINFLOW_REASON_CODES_CANONICAL.md` | `7259c9f12101060ec39d12835101400e6ad6ed7c101ca05901512ba06db41d1c` |
| Production plan checklist master | master-unversioned | `/home/agent/projects/apps/kinflow/specs/KINFLOW_PRODUCTION_PLAN_CHECKLIST_MASTER.md` | `d9a630f28c56ca24cfa8ec24f08787f8f009c7d6433e352606de8aa002efb6a1` |

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
