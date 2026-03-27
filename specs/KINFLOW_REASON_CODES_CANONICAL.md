---
source_message_id: 1485956217548570624
installed_by_instruction_id: KINFLOW-R1-REASONCODE-AUDIT-CLOSURE-20260324-001
run_code: 4353
installed_utc: 2026-03-24T23:00:00Z
status: canonical
version: v1.0.3
---

KINFLOW_REASON_CODES_CANONICAL.md (Master Cut v1.0.3)
# KINFLOW_REASON_CODES_CANONICAL.md

version: v1.0.3
status: canonical
owner: kinflow
last_updated_utc: 2026-03-24T23:00:00Z

## Purpose
Canonical reason-code registry for Kinflow runtime, adapter, persistence, and audit surfaces.

All `reason_code` fields MUST use values from this file.
No free-text reason codes are permitted.
Dependent specs that bind this artifact MUST pin:
- version
- sha256 hash

---

## Naming Convention
- UPPER_SNAKE_CASE
- stable identifiers
- explicit deprecation; no silent renames

---

## Classification Precedence Rule
If both policy-driven and runtime-driven classification are available for the same event:
1) policy override classification wins
2) runtime/provider mapping applies only when no policy override match exists

---

## Canonical Reason Codes (machine-readable defaults)

Each code includes:
- class
- retry_eligible_default
- terminal_default
- resumable (boolean)
- resumable_via (short note)

### Success

- DELIVERED_SUCCESS
- class: success
- retry_eligible_default: false
- terminal_default: true
- resumable: false
- resumable_via: none
- notes: valid only when `delivery_confidence in {provider_confirmed, provider_accepted}`.

### Lifecycle Stage Success (non-delivery audit stages)

- INTAKE_RECEIVED
- class: mutation
- retry_eligible_default: false
- terminal_default: false
- resumable: false
- resumable_via: none

- CONFIRMATION_ACCEPTED
- class: mutation
- retry_eligible_default: false
- terminal_default: false
- resumable: false
- resumable_via: none

- SCHEDULE_QUEUED
- class: mutation
- retry_eligible_default: false
- terminal_default: false
- resumable: false
- resumable_via: none

### Resolver

- RESOLVER_EXPLICIT
- class: mutation
- retry_eligible_default: false
- terminal_default: false
- resumable: false
- resumable_via: none

- RESOLVER_MATCHED
- class: mutation
- retry_eligible_default: false
- terminal_default: false
- resumable: false
- resumable_via: none

- RESOLVER_AMBIGUOUS
- class: blocked
- retry_eligible_default: false
- terminal_default: false
- resumable: true
- resumable_via: explicit disambiguation/regeneration only

- RESOLVER_NO_MATCH
- class: mutation
- retry_eligible_default: false
- terminal_default: false
- resumable: false
- resumable_via: none

### Time / Timezone

- TZ_EXPLICIT
- class: mutation
- retry_eligible_default: false
- terminal_default: false
- resumable: false
- resumable_via: none

- TZ_HOUSEHOLD_DEFAULT
- class: mutation
- retry_eligible_default: false
- terminal_default: false
- resumable: false
- resumable_via: none

- TZ_FALLBACK_USED
- class: runtime
- retry_eligible_default: false
- terminal_default: false
- resumable: false
- resumable_via: none

- TZ_MISSING
- class: blocked
- retry_eligible_default: false
- terminal_default: false
- resumable: true
- resumable_via: explicit regeneration/retry trigger after config repair

### Delivery / Transport

- FAILED_PROVIDER_TRANSIENT
- class: transient
- retry_eligible_default: true
- terminal_default: false
- resumable: true
- resumable_via: explicit retry trigger / scheduler retry path

- FAILED_PROVIDER_PERMANENT
- class: permanent
- retry_eligible_default: false
- terminal_default: true
- resumable: false
- resumable_via: none

- FAILED_CONFIG_INVALID_TARGET
- class: blocked
- retry_eligible_default: false
- terminal_default: false
- resumable: true
- resumable_via: explicit regeneration/retry trigger after target fix

- FAILED_CAPABILITY_UNSUPPORTED
- class: blocked
- retry_eligible_default: false
- terminal_default: false
- resumable: true
- resumable_via: explicit regeneration/retry trigger after capability change

- FAILED_RETRY_EXHAUSTED
- class: permanent
- retry_eligible_default: false
- terminal_default: true
- resumable: false
- resumable_via: none

- SUPPRESSED_QUIET_HOURS
- class: suppressed
- retry_eligible_default: false
- terminal_default: true
- resumable: false
- resumable_via: none

- CAPTURE_ONLY_BLOCKED
- class: blocked
- retry_eligible_default: false
- terminal_default: false
- resumable: true
- resumable_via: explicit regeneration/retry trigger after mode change

### Lifecycle / Mutation

- UPDATED_REGENERATED
- class: mutation
- retry_eligible_default: false
- terminal_default: false
- resumable: false
- resumable_via: none

- CANCEL_INVALIDATED
- class: mutation
- retry_eligible_default: false
- terminal_default: false
- resumable: false
- resumable_via: none

- BLOCKED_CONFIRMATION_REQUIRED
- class: blocked
- retry_eligible_default: false
- terminal_default: false
- resumable: true
- resumable_via: explicit confirmation + regeneration trigger

- VERSION_CONFLICT_RETRY
- class: transient
- retry_eligible_default: true
- terminal_default: false
- resumable: true
- resumable_via: explicit retry trigger

### Recovery / Runtime

- RECOVERY_RECONCILED
- class: runtime
- retry_eligible_default: false
- terminal_default: false
- resumable: false
- resumable_via: none

- FAIRNESS_BOUND_EXCEEDED
- class: runtime
- retry_eligible_default: false
- terminal_default: false
- resumable: false
- resumable_via: none

- DB_RECONNECT_EXHAUSTED
- class: runtime
- retry_eligible_default: false
- terminal_default: true
- resumable: true
- resumable_via: explicit restart/recovery trigger

- STARTUP_VALIDATION_FAILED
- class: runtime
- retry_eligible_default: false
- terminal_default: true
- resumable: true
- resumable_via: explicit config fix + restart trigger

- SHUTDOWN_GRACE_EXCEEDED
- class: runtime
- retry_eligible_default: false
- terminal_default: true
- resumable: true
- resumable_via: explicit restart trigger

---

## Classification Source Registry (annotation-only; not reason_code outcomes)

These are not outcome reason codes.
Use in metadata fields such as `retry_classification_source`.

- POLICY_OVERRIDE_APPLIED
- PROVIDER_MAP_APPLIED
- FALLBACK_DEFAULT_APPLIED

---

## Delivery Success Semantics
For `reason_code=DELIVERED_SUCCESS`:
1) `delivery_confidence MUST be provider_confirmed or provider_accepted`
2) if `delivery_confidence=provider_accepted`, then `provider_accept_only MUST be true`
3) if `delivery_confidence=provider_confirmed`, then `provider_accept_only MUST be false`

---

## Mandatory Usage Surface
`reason_code` is mandatory on:
1) adapter results
2) delivery attempts
3) lifecycle/audit events
4) recovery mutations

Any nullable exception must be explicitly declared in the owning contract/spec.

---

## Appendix A Parity Rule (Normative)
The prose canonical list and Appendix A YAML list MUST remain parity-aligned.
The number of reason-code entries in prose MUST equal the number of entries in Appendix A.

---

## Change Control
Any update requires:
1) version bump in this file
2) changelog note in Kinflow docs
3) downstream spec hash/version rebinding
4) conformance test updates

---

## Deprecation Policy
Deprecated codes remain valid for historical records.
New writes MUST use declared replacement codes after effective cutover.

# deprecated:
# - OLD_CODE -> NEW_CODE (effective_utc: ...)

---

## Appendix A — Compact machine-readable registry (YAML)

reason_codes:
  - code: DELIVERED_SUCCESS
    class: success
    retry_eligible_default: false
    terminal_default: true
    resumable: false
    resumable_via: none

  - code: INTAKE_RECEIVED
    class: mutation
    retry_eligible_default: false
    terminal_default: false
    resumable: false
    resumable_via: none

  - code: CONFIRMATION_ACCEPTED
    class: mutation
    retry_eligible_default: false
    terminal_default: false
    resumable: false
    resumable_via: none

  - code: SCHEDULE_QUEUED
    class: mutation
    retry_eligible_default: false
    terminal_default: false
    resumable: false
    resumable_via: none

  - code: RESOLVER_EXPLICIT
    class: mutation
    retry_eligible_default: false
    terminal_default: false
    resumable: false
    resumable_via: none

  - code: RESOLVER_MATCHED
    class: mutation
    retry_eligible_default: false
    terminal_default: false
    resumable: false
    resumable_via: none

  - code: RESOLVER_AMBIGUOUS
    class: blocked
    retry_eligible_default: false
    terminal_default: false
    resumable: true
    resumable_via: explicit disambiguation/regeneration only

  - code: RESOLVER_NO_MATCH
    class: mutation
    retry_eligible_default: false
    terminal_default: false
    resumable: false
    resumable_via: none

  - code: TZ_EXPLICIT
    class: mutation
    retry_eligible_default: false
    terminal_default: false
    resumable: false
    resumable_via: none

  - code: TZ_HOUSEHOLD_DEFAULT
    class: mutation
    retry_eligible_default: false
    terminal_default: false
    resumable: false
    resumable_via: none

  - code: TZ_FALLBACK_USED
    class: runtime
    retry_eligible_default: false
    terminal_default: false
    resumable: false
    resumable_via: none

  - code: TZ_MISSING
    class: blocked
    retry_eligible_default: false
    terminal_default: false
    resumable: true
    resumable_via: explicit regeneration/retry trigger after config repair

  - code: FAILED_PROVIDER_TRANSIENT
    class: transient
    retry_eligible_default: true
    terminal_default: false
    resumable: true
    resumable_via: explicit retry trigger / scheduler retry path

  - code: FAILED_PROVIDER_PERMANENT
    class: permanent
    retry_eligible_default: false
    terminal_default: true
    resumable: false
    resumable_via: none

  - code: FAILED_CONFIG_INVALID_TARGET
    class: blocked
    retry_eligible_default: false
    terminal_default: false
    resumable: true
    resumable_via: explicit regeneration/retry trigger after target fix

  - code: FAILED_CAPABILITY_UNSUPPORTED
    class: blocked
    retry_eligible_default: false
    terminal_default: false
    resumable: true
    resumable_via: explicit regeneration/retry trigger after capability change

  - code: FAILED_RETRY_EXHAUSTED
    class: permanent
    retry_eligible_default: false
    terminal_default: true
    resumable: false
    resumable_via: none

  - code: SUPPRESSED_QUIET_HOURS
    class: suppressed
    retry_eligible_default: false
    terminal_default: true
    resumable: false
    resumable_via: none

  - code: CAPTURE_ONLY_BLOCKED
    class: blocked
    retry_eligible_default: false
    terminal_default: false
    resumable: true
    resumable_via: explicit regeneration/retry trigger after mode change

  - code: UPDATED_REGENERATED
    class: mutation
    retry_eligible_default: false
    terminal_default: false
    resumable: false
    resumable_via: none

  - code: CANCEL_INVALIDATED
    class: mutation
    retry_eligible_default: false
    terminal_default: false
    resumable: false
    resumable_via: none

  - code: BLOCKED_CONFIRMATION_REQUIRED
    class: blocked
    retry_eligible_default: false
    terminal_default: false
    resumable: true
    resumable_via: explicit confirmation + regeneration trigger

  - code: VERSION_CONFLICT_RETRY
    class: transient
    retry_eligible_default: true
    terminal_default: false
    resumable: true
    resumable_via: explicit retry trigger

  - code: RECOVERY_RECONCILED
    class: runtime
    retry_eligible_default: false
    terminal_default: false
    resumable: false
    resumable_via: none

  - code: FAIRNESS_BOUND_EXCEEDED
    class: runtime
    retry_eligible_default: false
    terminal_default: false
    resumable: false
    resumable_via: none

  - code: DB_RECONNECT_EXHAUSTED
    class: runtime
    retry_eligible_default: false
    terminal_default: true
    resumable: true
    resumable_via: explicit restart/recovery trigger

  - code: STARTUP_VALIDATION_FAILED
    class: runtime
    retry_eligible_default: false
    terminal_default: true
    resumable: true
    resumable_via: explicit config fix + restart trigger

  - code: SHUTDOWN_GRACE_EXCEEDED
    class: runtime
    retry_eligible_default: false
    terminal_default: true
    resumable: true
    resumable_via: explicit restart trigger
