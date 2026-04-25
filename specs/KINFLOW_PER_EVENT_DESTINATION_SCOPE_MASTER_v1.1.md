---
title: KINFLOW Per-Event Destination Scope Master
version: v1.1
status: approved-for-spec-derivation
date_utc: 2026-04-22
initiative: CTX-002
---

CTX-002 Scope Doc — Per-Event Target Channel/Group (Master Cut v1.1)
1) Objective
Enable each event to define its own reminder delivery destination (channel/group/DM target), instead of relying only on recipient default target resolution.

2) Problem Statement
Current CTX-002 reminder routing is recipient-target based.
This prevents first-class support for:
Event A reminders to Group X
Event B reminders to Group Y
for the same user/recipient identity.

3) In-Scope (v1.1)
Add per-event destination override field(s) in event model/persistence.
Destination model must be channel-agnostic (not WhatsApp-specific in schema/contract design).
Reminder generation and dispatch must prefer event-level destination when present.
Maintain existing behavior when event-level destination is absent (backward-compatible fallback).
Validation of destination shape at write time (channel-specific via adapter validation hook).
Deterministic audit evidence showing destination source used:
event_override
request_context_default
recipient_default

4) Out-of-Scope (v1.1)
Audience privacy model (private/subset visibility).
Recurrence/series expansion.
Per-offset destination overrides.
Multi-recipient per-event custom routing matrix.
Cross-channel fanout per single event.
5) Functional Requirements
Event can store optional destination override:
channel
target_ref (canonical channel-specific form)
optional channel metadata envelope (future-safe)
If override exists and is valid:
dispatch uses override destination.
If override missing:
dispatch uses fallback precedence:
1) request_context_default (set by operating agent contract)
2) recipient_default
If override invalid at send time:
fail deterministically with canonical reason code (no silent fallback unless policy explicitly enables fallback).
Audit trail includes:
selected destination
source of destination selection
failure reason if rejected.
6) Channel-Agnostic Addressing Model
Core engine/persistence owns a generic destination contract:
channel: str
target_ref: str
Channel adapters own validation/canonicalization rules.
v1 execution may ship WhatsApp-first validation, but contract must be adapter-neutral so additional channels can be added without schema redesign.

7) Operating Agent vs Engine Boundary (Routing Defaults)
Operating agent contract is responsible for deriving/storing request_context_default from source interaction context.
Engine consumes resolved routing inputs deterministically and must not infer chat/session context heuristically.
This boundary is mandatory to keep engine deterministic and channel-portable.

8) Data/Model Impact (high-level)
Event schema: add optional destination override fields (additive).
No breaking change for existing events (null/default allowed).
Reminder row should carry resolved destination snapshot at dispatch time (or generation if chosen; must be deterministic and documented).
Add destination source marker in attempt/audit evidence.
9) Delivery Semantics
Preserve existing delivery success criteria:
provider evidence gates unchanged
seam classifier behavior unchanged
Only destination selection logic changes in this slice.

10) Compatibility + Migration
Migration must be additive and reversible.
Existing events continue to route via fallback chain unless override explicitly set.
No mandatory backfill for legacy rows.

11) Observability / Audit
Minimum new evidence fields:
destination_source: event_override|request_context_default|recipient_default
resolved_channel
resolved_target_ref
destination_resolution_status: ok|invalid|missing
existing attempt reason/status fields remain canonical.

12) Risks
Wrong-destination regression if fallback precedence is ambiguous.
Silent fallback masking invalid override configuration.
Drift between request context default and recipient default expectations.
Adapter inconsistency across channels if canonicalization is not centralized per channel.

13) Guardrails
Explicit precedence rule is fixed and tested.
Fail-closed on malformed override by default.
Add tests for:
override success path
request-context-default fallback path
recipient-default fallback path
invalid override failure path
audit/source correctness.
14) Versioning Requirements (Mandatory)
Introduce/maintain explicit version constants:
ENGINE_VERSION
SCHEMA_VERSION
CONTRACT_SET_VERSION
PRs touching governed paths must declare change class:
no-version-bump
behavior-patch
contract-boundary-change
schema-change
Bump rules:
schema migration required → bump SCHEMA_VERSION
contract shape/semantics change → bump CONTRACT_SET_VERSION
engine behavior change (no schema/contract change) → bump ENGINE_VERSION
Runtime observability:
emit version tuple at startup + health/state surfaces.
CI consistency gate:
fail when required bumps/artifacts are missing or inconsistent.

15) Acceptance Criteria
Event with override routes reminders to override destination.
Event without override uses fallback precedence exactly:
request-context-default, else recipient-default.
Invalid override yields deterministic canonical failure (no false delivered).
Audit/attempt records explicitly show destination source and resolved target.
Existing CTX-002 golden checks still pass (or are updated with explicit rationale limited to destination-source additions).
Version tuple and bump policy checks are satisfied in CI for this slice.

16) Done Definition
Migration + model + dispatch logic implemented.
Adapter-neutral destination contract installed.
WhatsApp-first validation path implemented (with neutral extension seams for other channels).
Test coverage for precedence/fallback/failure/audit + version gates.
No regressions in existing delivery evidence semantics.
Runbook update for setting per-event destination.
CI green.