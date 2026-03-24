# KINFLOW Architecture Decision — Issue #3 (adapter_results vs delivery_attempts)

gate_outcome: accepted

decision_id: ADR-KINFLOW-ISSUE3-2026-03-24-001  
decision_timestamp_utc: 2026-03-24T15:44:00Z  
issue_reference: #3
status: ACCEPTED (authoritative)

## Lint Preflight
```text
LINT PREFLIGHT
LINT_PASS_NORMALIZED: markdownlint_not_installed
```

## Decision Statement (normative)
1. `delivery_attempts` is the canonical persisted adapter-result ledger.
2. `adapter_results` is a logical alias only and MUST NOT exist as a separate persistent store.
3. All adapter outcome fields MUST deterministically map 1:1 into `delivery_attempts` before commit.
4. Any future proposal introducing durable dual writes for adapter outcomes is REJECTED unless this ADR is formally superseded.

## Chosen Architecture
- Canonical durable model: `delivery_attempts`.
- Alias model: `adapter_results` (logical/transient vocabulary surface for adapter shaping only).
- Durability boundary: one persisted ledger only (`delivery_attempts`).

## Rejected Alternative
**Rejected:** dual-store persistent model (`delivery_attempts` + separate persisted `adapter_results`).

**Rejection basis (deterministic):**
- introduces divergence risk between two durable ledgers,
- increases replay/recovery ambiguity,
- weakens deterministic idempotency evidence,
- increases migration and operational coupling cost.

## Consequences and Risk Tradeoffs
### Positive
- Single source of truth for retries, replay identity, and audit linkage.
- Deterministic reconciliation path across daemon/adapter/persistence surfaces.
- Lower schema and migration complexity than dual-store alternatives.

### Accepted Risks
- Adapter teams must preserve strict mapping discipline at the alias boundary.
- Any adapter-local convenience fields not mapped into canonical schema are non-durable by policy.

### Controls
- Cross-spec wording lock: persistence/adapter/daemon MUST use single-store semantics.
- Freeze/governance pinning includes this ADR path.
- Re-baseline declaration required before P2-B continuation.

## Rollback / Escape Path
If this decision becomes non-viable:
1. Freeze progression and mark `P2B_ALLOWED: NO` in a superseding baseline declaration.
2. Publish successor ADR that explicitly supersedes `ADR-KINFLOW-ISSUE3-2026-03-24-001`.
3. Define migration-safe cutover plan (data model, replay semantics, dual-write guardrails, verification).
4. Re-freeze contract manifest with updated pins/hashes and approval evidence.

No implicit rollback is permitted.

## Authority and Discoverability
- Canonical location: this file.
- Pinned from: `README.md`, `specs/KINFLOW_CONTRACT_FREEZE_MANIFEST_PHASE0_5.md`, and backlog board CTX-002 references.
