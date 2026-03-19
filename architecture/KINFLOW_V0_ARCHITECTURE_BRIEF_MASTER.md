source_message_id: 1483850977546207435
source_channel_id: 1483760080766898297
installed_by_instruction_id: CTX-002-INSTALL-ARCH-20260318-001
installed_utc: 2026-03-18T16:54:46Z

CTX-002 v0 Architecture Brief (Master Copy — Unified, Refined)

5) Create vs Update Resolution Model (Updated)

Resolution Precedence (Canonical)
	1.	Explicit event reference (event_id or thread-bound reference)
	2.	Deterministic similarity match (title/time/participants with fixed threshold)
	3.	Ambiguity → user disambiguation required
	4.	No match → create

Guarantees
	•	No duplicate precedence paths
	•	Ambiguity never auto-resolves
	•	Same input + state → same outcome

⸻

6) Timezone Resolution and Temporal Semantics (Hardened)

Authority Model (Explicit Split)
	•	Event timezone = event semantic time (what time the event occurs)
	•	Recipient timezone = delivery timing + quiet-hours enforcement

Hard Rule
	•	Quiet-hours MUST be evaluated using recipient timezone only, never event timezone

Resolution Order

Event timezone
	1.	Explicit event timezone
	2.	User/session context
	3.	Household default
	4.	System fallback (normalization only, logged)

Recipient timezone
	1.	DeliveryTarget.timezone
	2.	Household default
	3.	Missing → BLOCK delivery (TZ_MISSING)

Guardrail
	•	System fallback timezone is never allowed for delivery scheduling

⸻

8) Policy Layer (Addition)

Reason Codes (Canonicalized ENUM)

All reason codes MUST be defined as fixed enum identifiers (no free text):
	•	RESOLVER_EXPLICIT
	•	RESOLVER_MATCHED
	•	RESOLVER_AMBIGUOUS
	•	RESOLVER_NO_MATCH
	•	TZ_EXPLICIT
	•	TZ_HOUSEHOLD_DEFAULT
	•	TZ_FALLBACK_USED
	•	TZ_MISSING
	•	DELIVERED
	•	FAILED_PROVIDER
	•	FAILED_RETRY_EXHAUSTED
	•	SUPPRESSED_QUIET_HOURS
	•	UPDATED_REGENERATED
	•	CANCEL_INVALIDATED
	•	BLOCKED_CONFIRMATION_REQUIRED

⸻

11) Determinism Proof Contract (Extended)

Replay Fixture Scope (Explicit)

Validation scenarios MUST include:
	•	DST boundary transitions
	•	Cross-timezone event creation + delivery
	•	Concurrent update collisions (same event, overlapping edits)
	•	Retry/replay after partial failure
	•	Duplicate message ingestion

⸻

12) Failure Model (Capture-Only Clarified)

Capture-Only Degradation Mode

Allowed
	•	Intake
	•	Follow-up
	•	Confirmation
	•	Persist event mutation

Blocked
	•	Scheduling
	•	Trigger generation
	•	Outbound delivery

Requirements
	•	System MUST emit explicit degraded-mode reason code
	•	User/operator MUST have visibility into degraded state
	•	Recovery MUST resume deterministic scheduling from persisted state

⸻

15) Acceptance (Architecture-Level) — Hardened

System is acceptable if it demonstrates:
	•	Deterministic create/update/cancel behavior
	•	Stable, non-drifting reminder regeneration
	•	Timezone-consistent scheduling and rendering
	•	Deterministic failure handling across all defined cases
	•	End-to-end immutable traceability

Measurable Gates
	•	0 duplicate user-visible deliveries across replay test suite
	•	0 resolver ambiguity auto-resolutions
	•	0 reminder drift mismatches across regeneration tests
	•	100% deterministic replay consistency across validation scenarios
