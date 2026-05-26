# Adapter Results Vs Delivery Attempts

decision_id: ADR-KINFLOW-ISSUE3-2026-03-24-001
status: accepted

## Decision

`delivery_attempts` is the canonical persisted adapter-result ledger.

`adapter_results` is a logical alias only and must not exist as a separate persistent store.

All adapter outcome fields must deterministically map into `delivery_attempts` before commit.

Any future durable dual-write model for adapter outcomes requires a superseding ADR, migration plan, contract update, and freeze-manifest rebind.

## Rationale

A single persisted ledger keeps retry, replay, idempotency, audit, and recovery semantics aligned. A separate durable adapter-results store would introduce divergence risk and make failure reconstruction harder.

## Consequences

- Adapter-local convenience fields are non-durable unless mapped into `delivery_attempts`.
- Replay and recovery logic reads one canonical ledger.
- Schema migrations stay smaller and easier to validate.
- Future proposals for dual persistence are rejected unless this decision is formally superseded.
