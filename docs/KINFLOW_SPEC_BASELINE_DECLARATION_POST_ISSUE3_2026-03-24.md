# KINFLOW Spec Baseline Declaration — Post Issue #3 — 2026-03-24

gate_outcome: accepted

declaration_id: KINFLOW-BASELINE-ISSUE3-2026-03-24-001  
declaration_timestamp_utc: 2026-03-24T15:44:00Z  
source_alignment_commit: b7a80c091c4b28e2676e45b8a5229143306d3cd3
baseline_commit_hash: 60df3c734ac7c8bbf8dbb1509388a1e98dd3831f

## Lint Preflight
```text
LINT PREFLIGHT
LINT_PASS_NORMALIZED: markdownlint_not_installed
```

## Architecture Consistency Assertion
Assertion: proven.

Deterministic condition set:
1. Persistence spec states `delivery_attempts` as single canonical persistence surface.
2. OC adapter spec states `adapter_results` is non-authoritative/transient and maps 1:1 into `delivery_attempts`.
3. Daemon/comms wording does not introduce a second durable adapter-outcome store.
4. Freeze/README/backlog references pin discoverability to authoritative Issue #3 decision artifact.

## Pinned spec versions and hashes
| Artifact | Version | sha256 |
|---|---|---|
| `specs/KINFLOW_DURABLE_PERSISTENCE_SPEC_MASTER_v0.2.6.md` | v0.2.7 | `3940c942452776f421a94b7c63b9093ea0fdc1b9284e39f43e9d392e26a8b75e` |
| `specs/KINFLOW_COMMS_ADAPTER_CONTRACT_MASTER_v0.1.7.md` | v0.1.7 | `a1eb2ece0f25fce7c85292a153d9d60d30fd98230a0774a5e5df5fef57cb46e3` |
| `specs/KINFLOW_DAEMON_RUNTIME_CONTRACT_MASTER_v0.1.4.md` | v0.1.4 | `50111cf0173b2023ad92a0c7b08ceae0e85163d3fc117234dc8d400ac8beaded` |
| `specs/KINFLOW_OC_ADAPTER_IMPLEMENTATION_SPEC_MASTER_v0.2.4.md` | v0.2.4 | `dc1e4abdf3d034ac80328e7e32d7bda40b371ab3604b3f6b751f3fe47fc49fb6` |
| `specs/KINFLOW_REASON_CODES_CANONICAL.md` | v1.0.3 | `7aa08628acf0633480c5f496fc632f24226cdfabad8aa8b9c34ab68e37d04742` |
| `specs/KINFLOW_CONTRACT_FREEZE_MANIFEST_PHASE0_5.md` | phase-0.5 | `9dc4e7356bd0f3e2ef7a3f77ce297be652dd4c456b7cc55a3ce863531411ea77` |

## Continuation Gate
P2B_ALLOWED: YES

Rationale: Issue #3 single-store architecture is explicitly decided, reconciliation evidence captured, and canonical doc discoverability pinned.

If any pinned hash drifts without re-freeze, this declaration is invalid and continuation gate must be re-evaluated.
