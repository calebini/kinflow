source_message_id: 1483765985654739005
source_channel_id: 1483760080766898297
installed_by_instruction_id: KINFLOW-INSTALL-REQS-20260318-001
installed_utc: 2026-03-18T14:17:54Z

KINFLOW Requirements (Unified v0 Baseline — Slugged)

0) Purpose

Chat-first family scheduling coordinator with deterministic behavior, auditability, and clean extensibility.

⸻

1) Core Product Outcomes

KINFLOW-REQ-1.1 Required Outcomes
	•	Reliable event create / update / cancel via chat
	•	Deterministic normalization and persistence
	•	Reliable daily morning overview
	•	Reliable pre-event reminders (≥1 offset)
	•	Correct update/cancel propagation
	•	End-to-end traceability

KINFLOW-REQ-1.2 Post-v0 Direction
	•	Calendar ingest and publish (design guardrail only)

⸻

2) Functional Requirements

KINFLOW-FR-2.1 Chat Event Intake
	•	Create / update / cancel supported
	•	Natural language input
	•	Deterministic parsing + classification
	•	Conditional follow-up (missing required fields only)

KINFLOW-FR-2.1.1 Required Fields
	•	Date/time or all-day
	•	Audience/participants
	•	Reminder preference

KINFLOW-FR-2.1.2 Guardrails
	•	No over-collection
	•	No silent assumptions

⸻

KINFLOW-FR-2.2 Confirmation Gate (HARD)
	•	Show normalized summary
	•	Explicit yes/no save

Rules
	•	No persistence without confirmation
	•	No silent edits post-confirmation

⸻

KINFLOW-FR-2.3 Event Lifecycle
	•	Create / update / cancel (complete optional)

Behavior
	•	Updates mutate existing event
	•	Cancel invalidates future reminders
	•	Edits trigger deterministic regeneration

⸻

KINFLOW-FR-2.4 Create vs Update Resolver (HARD)

KINFLOW-FR-2.4.1 Explicit Reference
	•	event_id or unambiguous reference → UPDATE

KINFLOW-FR-2.4.2 High-Confidence Match
	•	title + time + participants above threshold → UPDATE

KINFLOW-FR-2.4.3 Ambiguous Match
	•	Multiple/low confidence → REQUIRE CONFIRMATION

KINFLOW-FR-2.4.4 No Match
	•	→ CREATE

Guardrails
	•	No silent resolution
	•	Resolver decision logged in audit

⸻

KINFLOW-FR-2.5 Timezone Authority (HARD)
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

KINFLOW-FR-2.6 Daily Morning Brief
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

KINFLOW-FR-2.7 Reminder Engine

Core
	•	Single offset required (v0)
	•	Multi-offset supported structurally

Lifecycle
	•	scheduled → attempted → delivered | failed

KINFLOW-FR-2.7.1 Requirements
	•	Deterministic scheduling
	•	Dedupe (event + offset + time)
	•	Bounded retries
	•	Quiet-hours enforcement (configurable)

KINFLOW-FR-2.7.2 Mutation
	•	Update → regenerate reminders
	•	Cancel → invalidate reminders

⸻

KINFLOW-FR-2.8 Delivery & Routing
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

KINFLOW-FR-2.9 Audit & Traceability (HARD)

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

KINFLOW-FR-2.10 Audit Retention & Redaction

KINFLOW-FR-2.10.1 Retention
	•	Minimum retention window required (30–90 days baseline)

KINFLOW-FR-2.10.2 Redaction
	•	Sensitive fields may be masked post-threshold
	•	Must preserve structure and metadata

KINFLOW-FR-2.10.3 Immutability
	•	Redaction is additive, not destructive

⸻

KINFLOW-FR-2.11 Idempotency & Dedupe (HARD)
	•	Same intent ≠ duplicate event
	•	Deterministic create vs update
	•	Reminder dedupe enforced
	•	Retry does not duplicate user-visible messages

⸻

KINFLOW-FR-2.12 Event-Type Foundation
	•	event_type supported (optional)
	•	Table-driven behavior (future)

⸻

KINFLOW-FR-2.13 Advanced Constructs (Foundational)

EventProfile
	•	Generic reminder profile required

EventBundle
	•	Optional grouping
	•	Must not impact core flow

⸻

3) Data Contract

KINFLOW-DC-3.1 Event
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

KINFLOW-DC-3.2 ReminderRule
	•	event_id
	•	offset_minutes
	•	recipient_scope
	•	enabled

⸻

KINFLOW-DC-3.3 DeliveryTarget
	•	person_id
	•	channel
	•	target_id
	•	quiet_hours

⸻

KINFLOW-DC-3.4 DailyOverviewPolicy
	•	send_time_local
	•	recipient_scope
	•	include_completed

⸻

KINFLOW-DC-3.5 Future Fields
	•	external_refs
	•	origin

⸻

4) Flow Contract

KINFLOW-FL-4.1 Deterministic Flow (HARD)
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

KINFLOW-NFR-5.1 No Silent Edits (HARD)
	•	No changes after confirmation without user action

KINFLOW-NFR-5.2 Idempotency (HARD)
	•	Deterministic behavior across retries and inputs

KINFLOW-NFR-5.3 Deterministic Regeneration (HARD)
	•	Edits produce consistent recomputation

KINFLOW-NFR-5.4 Quiet Hours
	•	Enforced unless explicitly overridden

KINFLOW-NFR-5.5 Bounded Retries
	•	No infinite retry loops

KINFLOW-NFR-5.6 Audit Integrity (HARD)
	•	Immutable audit with redaction layer

KINFLOW-NFR-5.7 Lifecycle Stability (HARD)
	•	Explicit, stable state transitions

⸻

6) Scope

KINFLOW-SC-6.1 In Scope
	•	Chat intake + follow-ups
	•	Resolver logic
	•	Confirmation gate
	•	Event persistence
	•	Daily brief
	•	Reminder engine
	•	Update/cancel propagation
	•	Delivery tracking
	•	Audit + retention

KINFLOW-SC-6.2 Out of Scope
	•	Calendar integrations
	•	External APIs
	•	Flight intelligence
	•	Advanced automation
	•	Heavy bundling

⸻

7) Governance

KINFLOW-GOV-7.1 Migration Path
	•	Must support transition to Foreman-controlled execution

KINFLOW-GOV-7.2 Migration Gates
	•	Audit completeness
	•	Determinism validation
	•	No reliability regression

⸻

8) Acceptance Criteria

KINFLOW-AC-8.1 Core Acceptance
	•	Events reliably created/updated/cancelled
	•	Resolver behaves deterministically
	•	Confirmation enforced
	•	Morning brief consistent
	•	Reminders deduplicated and correct
	•	Edits/cancels propagate correctly
	•	Timezone behavior consistent
	•	Full audit trace available
