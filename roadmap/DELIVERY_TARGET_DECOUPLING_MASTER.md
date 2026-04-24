DELIVERY_TARGET_DECOUPLING_MASTER.md
status: proposed
priority: high
owner: kinflow
last_updated_utc: 2026-04-24T18:49:00Z

Title
Delivery Target Decoupling (Identity / Endpoint / Routing / Policy Separation)

Problem
Current delivery_target shape over-couples:
identity (person)
routing endpoint (channel + target_ref)
policy (timezone, quiet_hours)

This coupling increases migration risk and makes deterministic routing evolution harder.

Target Model (Next-Version)
RecipientProfile (person-level defaults/prefs)
DestinationEndpoint (channel + target_ref; many per recipient)
RoutingBinding (which endpoint to use for event/request context)
PolicyLayer (timezone/quiet-hours at person or endpoint scope, explicit precedence)

Deterministic Rules
Persist routing provenance (binding_source, endpoint_id, resolution status).
Keep dual-phase validation (write-time + dispatch-time; dispatch authoritative).
Fail closed on invalid/unresolved destination.
Preserve delivery truth semantics (no false delivered-success).
Non-Goals (This Slice)
recurrence redesign
global replay identity redesign
cross-channel fanout redesign
broad audience/privacy redesign

Migration Shape (Additive)
Phase 0: schema/contracts prep (add decoupled entities)
Phase 1: dual-write compatibility
Phase 2: read-path switch to decoupled model
Phase 3: bounded legacy deprecation after acceptance window

Acceptance Gates
precedence + routing-binding tests pass
policy-scope precedence tests pass
migration forward/rollback/post-rollback checks pass
no regressions in seam/evidence/delivered semantics
canary pass across override/context-default/recipient-default paths

Risks
precedence ambiguity between routing and policy scopes
target_ref canonicalization drift across adapters
dual-write parity drift

Required Mitigations
explicit precedence matrix in contract
shared endpoint canonicalization validator contract
parity monitoring during dual-write window
