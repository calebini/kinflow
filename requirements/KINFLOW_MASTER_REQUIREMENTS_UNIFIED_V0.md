source_message_id: 1483765985654739005
source_channel_id: 1483760080766898297
installed_by_instruction_id: CTX-002-INSTALL-REQS-20260318-001
installed_utc: 2026-03-18T14:17:54Z

CTX-002 Requirements (Unified v0 Baseline — Slugged)

0) Purpose

Chat-first family scheduling coordinator with deterministic behavior, auditability, and clean extensibility.

⸻

1) Core Product Outcomes

CTX-002-REQ-1.1 Required Outcomes
	•	Reliable event create / update / cancel via chat
	•	Deterministic normalization and persistence
	•	Reliable daily morning overview
	•	Reliable pre-event reminders (≥1 offset)
	•	Correct update/cancel propagation
	•	End-to-end traceability

CTX-002-REQ-1.2 Post-v0 Direction
	•	Calendar ingest and publish (design guardrail only)

⸻

2) Functional Requirements

CTX-002-FR-2.1 Chat Event Intake
	•	Create / update / cancel supported
	•	Natural language input
	•	Deterministic parsing + classification
	•	Conditional follow-up (missing required fields only)

CTX-002-FR-2.1.1 Required Fields
	•	Date/time or all-day
	•	Audience/participants
	•	Reminder preference

CTX-002-FR-2.1.2 Guardrails
	•	No over-collection
	•	No silent assumptions

⸻

CTX-002-FR-2.2 Confirmation Gate (HARD)
	•	Show normalized summary
	•	Explicit yes/no save

Rules
	•	No persistence without confirmation
	•	No silent edits post-confirmation

⸻

CTX-002-FR-2.3 Event Lifecycle
	•	Create / update / cancel (complete optional)

Behavior
	•	Updates mutate existing event
	•	Cancel invalidates future reminders
	•	Edits trigger deterministic regeneration

⸻

CTX-002-FR-2.4 Create vs Update Resolver (HARD)

CTX-002-FR-2.4.1 Explicit Reference
	•	event_id or unambiguous reference → UPDATE

CTX-002-FR-2.4.2 High-Confidence Match
	•	title + time + participants above threshold → UPDATE

CTX-002-FR-2.4.3 Ambiguous Match
	•	Multiple/low confidence → REQUIRE CONFIRMATION

CTX-002-FR-2.4.4 No Match
	•	→ CREATE

Guardrails
	•	No silent resolution
	•	Resolver decision logged in audit

⸻

CTX-002-FR-2.5 Timezone Authority (HARD)
	•	Each event has canonical timezone

Resolution Order
	1.	Explicit timezone
	2.	Event context (e.g., travel)
	3.	Session/device timezone
	4.	Household default

Rules
	•	Scheduling uses event timezone only
	•	Rendering must not reinterpret timezone

⸻

CTX-002-FR-2.6 Daily Morning Brief
	•	Cron at configured local time

Structure
	•	Today
	•	Upcoming
	•	Conflicts
	•	Action items

Routing
	•	Default: family group
	•	Personal events: individual delivery

⸻

CTX-002-FR-2.7 Reminder Engine

Core
	•	Single offset required (v0)
	•	Multi-offset supported structurally

Lifecycle
	•	scheduled → attempted → delivered | failed

CTX-002-FR-2.7.1 Requirements
	•	Deterministic scheduling
	•	Dedupe (event + offset + time)
	•	Bounded retries
	•	Quiet-hours enforcement (configurable)

CTX-002-FR-2.7.2 Mutation
	•	Update → regenerate reminders
	•	Cancel → invalidate reminders

⸻

CTX-002-FR-2.8 Delivery & Routing
	•	Targets: group / individual

Lifecycle States
	•	scheduled
	•	attempted
	•	delivered
	•	failed

Requirements
	•	Quiet-hours enforced
	•	Retry caps
	•	Delivery logging

⸻

CTX-002-FR-2.9 Audit & Traceability (HARD)

Trace must include:
	•	Source message
	•	Parsed intent
	•	Resolver decision
	•	Event mutation
	•	Scheduled triggers
	•	Delivery outcomes

Properties
	•	Immutable
	•	Human-readable
	•	Explicit failure states

⸻

CTX-002-FR-2.10 Audit Retention & Redaction

CTX-002-FR-2.10.1 Retention
	•	Minimum retention window required (30–90 days baseline)

CTX-002-FR-2.10.2 Redaction
	•	Sensitive fields may be masked post-threshold
	•	Must preserve structure and metadata

CTX-002-FR-2.10.3 Immutability
	•	Redaction is additive, not destructive

⸻

CTX-002-FR-2.11 Idempotency & Dedupe (HARD)
	•	Same intent ≠ duplicate event
	•	Deterministic create vs update
	•	Reminder dedupe enforced
	•	Retry does not duplicate user-visible messages

⸻

CTX-002-FR-2.12 Event-Type Foundation
	•	event_type supported (optional)
	•	Table-driven behavior (future)

⸻

CTX-002-FR-2.13 Advanced Constructs (Foundational)

EventProfile
	•	Generic reminder profile required

EventBundle
	•	Optional grouping
	•	Must not impact core flow

⸻

3) Data Contract

CTX-002-DC-3.1 Event
	•	event_id
	•	title
	•	start_at / end_at OR all_day
	•	timezone (canonical)
	•	participants
	•	audience
	•	reminder config
	•	status
	•	source_message_ref

Optional:
	•	event_type
	•	location
	•	notes

⸻

CTX-002-DC-3.2 ReminderRule
	•	event_id
	•	offset_minutes
	•	recipient_scope
	•	enabled

⸻

CTX-002-DC-3.3 DeliveryTarget
	•	person_id
	•	channel
	•	target_id
	•	quiet_hours

⸻

CTX-002-DC-3.4 DailyOverviewPolicy
	•	send_time_local
	•	recipient_scope
	•	include_completed

⸻

CTX-002-DC-3.5 Future Fields
	•	external_refs
	•	origin

⸻

4) Flow Contract

CTX-002-FL-4.1 Deterministic Flow (HARD)
	1.	Intake
	2.	Parse/classify
	3.	Follow-up
	4.	Resolve create vs update
	5.	Confirm
	6.	Persist
	7.	Execute triggers
	8.	Record outcomes

Rules
	•	No step skipping
	•	No implicit transitions

⸻

5) Non-Functional Requirements

CTX-002-NFR-5.1 No Silent Edits (HARD)
	•	No changes after confirmation without user action

CTX-002-NFR-5.2 Idempotency (HARD)
	•	Deterministic behavior across retries and inputs

CTX-002-NFR-5.3 Deterministic Regeneration (HARD)
	•	Edits produce consistent recomputation

CTX-002-NFR-5.4 Quiet Hours
	•	Enforced unless explicitly overridden

CTX-002-NFR-5.5 Bounded Retries
	•	No infinite retry loops

CTX-002-NFR-5.6 Audit Integrity (HARD)
	•	Immutable audit with redaction layer

CTX-002-NFR-5.7 Lifecycle Stability (HARD)
	•	Explicit, stable state transitions

⸻

6) Scope

CTX-002-SC-6.1 In Scope
	•	Chat intake + follow-ups
	•	Resolver logic
	•	Confirmation gate
	•	Event persistence
	•	Daily brief
	•	Reminder engine
	•	Update/cancel propagation
	•	Delivery tracking
	•	Audit + retention

CTX-002-SC-6.2 Out of Scope
	•	Calendar integrations
	•	External APIs
	•	Flight intelligence
	•	Advanced automation
	•	Heavy bundling

⸻

7) Governance

CTX-002-GOV-7.1 Migration Path
	•	Must support transition to Foreman-controlled execution

CTX-002-GOV-7.2 Migration Gates
	•	Audit completeness
	•	Determinism validation
	•	No reliability regression

⸻

8) Acceptance Criteria

CTX-002-AC-8.1 Core Acceptance
	•	Events reliably created/updated/cancelled
	•	Resolver behaves deterministically
	•	Confirmation enforced
	•	Morning brief consistent
	•	Reminders deduplicated and correct
	•	Edits/cancels propagate correctly
	•	Timezone behavior consistent
	•	Full audit trace available
