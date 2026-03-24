---
source_message_id: 1485963257511677964
installed_by_instruction_id: KINFLOW-SPEC-INSTALL-OC-ADAPTER-V024-20260324-001
run_code: 4343
installed_utc: 2026-03-24T11:29:55Z
status: canonical
---

Kinflow OpenClaw Adapter Implementation Spec (Master Copy v0.2.4)
0) Convergence Declaration
Review Phase: final
Tier Entry Mode: T5-STRICT
Activation Status: validation_required (evidence artifacts pending)

Tier-3 Critical Dimensions
1) Provider mapping determinism
2) Replay/dedupe determinism
3) Correlation propagation integrity
4) Status/delivery_confidence consistency
5) Capture-only side-effect isolation
6) Capability conformance determinism

Declared Couplings
1) OpenClaw response classes ↔ mapping precedence
2) Delivery status ↔ delivery_confidence matrix
3) Idempotency keys ↔ replay semantics
4) Runtime mode ↔ side-effect gating
5) Capability flags ↔ enforcement behavior
6) Execution Envelope correlation IDs ↔ adapter result + audit linkage

---

0.5) Glossary
Canonical Result: Immutable adapter result used for replay.
Visible Send: Provider-side outbound attempt that could reach recipient.
Provider Accepted: Provider accepted request without stronger delivery proof.
Provider Confirmed: Provider returned stronger delivery confirmation proof.
Capture-Only Mode: Runtime mode that forbids outbound side effects.
Policy Override Map: Highest-precedence deterministic classification map.
Provider Map: Second-precedence deterministic classification map over normalized provider outcome classes.
Normalized Provider Response: Internal typed response shape used for deterministic mapping.
Dedupe Window: Time interval where duplicate dedupe keys must not produce second visible send.

---

1) Purpose
Define concrete, deterministic behavior for OpenClawGatewayAdapter so Kinflow delivery via OpenClaw conforms to canonical comms contract and rollout governance.

---

2) Scope
In scope:
typed request/result/error schemas
deterministic mapping precedence and schemas
replay/dedupe behavior
capability enforcement behavior
capture-only gating
health + audit output contracts
WhatsApp target normalization/resolution rules

Out of scope:
scheduler internals
non-OpenClaw adapters
multi-provider orchestration

---

3) Formal Type System (Authoritative)
3.1 Primitive types
IdString: ^[a-zA-Z0-9._:-]{1,128}$
UtcTimestamp: RFC3339 UTC (Z or +00:00)
JsonObject: UTF-8 JSON object (top-level object required)
ShortString: length 1..256
LongText: length 1..4000
3.2 Enum registry (single source)
DeliveryStatus = {DELIVERED, FAILED_TRANSIENT, FAILED_PERMANENT, SUPPRESSED, BLOCKED}
DeliveryConfidence = {provider_confirmed, provider_accepted, none}
ErrorClass = {transient, permanent, policy, config, unknown}
RetryClassificationSource = {policy_override, provider_map, fallback_default}
HealthState = {UP, DEGRADED, DOWN}
HealthFailMode = {strict, non_strict}
RuntimeMode = {normal, capture_only}
ChannelHint = {discord, signal, telegram, whatsapp, openclaw_auto}
SubjectType = {event_reminder, daily_overview}
AuditEventType = {send_attempt, send_result, dedupe_hit, capability_blocked, capture_only_blocked, health_snapshot, replay_returned}
Priority = {normal, high}
ReplaySource = {attempt_id_hit, dedupe_key_window_hit, none}
NormalizedOutcomeClass = {success, transient, permanent, blocked, suppressed, unknown}
ProviderConfirmationStrength = {accepted, confirmed, none}

ReasonCode is externally bound via §4.
No inline enums outside this registry.

---

4) Authoritative ReasonCode Binding
Adapter runtime MUST bind:
reason_code_spec_path
reason_code_spec_version
reason_code_spec_hash (SHA-256, LF-normalized UTF-8)

Startup MUST fail on mismatch.

---

5) Typed Contracts
5.1 OutboundMessage
delivery_id: IdString
attempt_id: IdString
attempt_index: int >= 1
trace_id: IdString
causation_id: IdString
channel_hint: ChannelHint
target_ref: ShortString
subject_type: SubjectType
priority: Priority
body_text: LongText
dedupe_key: ShortString
created_at_utc: UtcTimestamp
payload_json: JsonObject|null
payload_schema_version: int|null
compat_structured_payload_json: JsonObject|null (ingress alias only; maps to payload_json before validation)
compat_structured_payload_schema_version: int|null (ingress alias only; maps to payload_schema_version before validation)
metadata_json: JsonObject|null
metadata_schema_version: int|null
Null/version rules:
payload_json non-null => payload_schema_version non-null
payload_json null => payload_schema_version null
same for metadata pair

5.2 ErrorObject
Required:
normalized_code: ReasonCode
retry_classification_source: RetryClassificationSource
error_class: ErrorClass
message_sanitized: string
Optional:
provider_code: string|null
details_json: JsonObject|null
details_schema_version: int|null

5.3 DeliveryResult
status: DeliveryStatus
reason_code: ReasonCode
retry_eligible: bool
provider_receipt_ref: string|null
provider_status_code: string|null
provider_error_text: string|null
provider_accept_only: bool
delivery_confidence: DeliveryConfidence
result_at_utc: UtcTimestamp
error_object: ErrorObject|null
replay_indicator: bool
replay_source: ReplaySource
delivery_id: IdString
attempt_id: IdString
trace_id: IdString
causation_id: IdString
Constraints:
status=DELIVERED => reason_code MUST be DELIVERED_SUCCESS
status=DELIVERED => error_object MUST be null
status in {FAILED_TRANSIENT, FAILED_PERMANENT, SUPPRESSED, BLOCKED} => error_object MUST be non-null
if error_object exists: error_object.normalized_code == reason_code

---

6) Canonical Persistence Handoff Schema (Fully Enumerated)
Logical transient view: adapter_results (non-authoritative)

Fields:
attempt_id (PK)
delivery_id
dedupe_key
trace_id
causation_id
status
reason_code
delivery_confidence
retry_eligible
provider_receipt_ref
provider_status_code
provider_error_text
provider_accept_only
error_object_json
replay_indicator
replay_source
result_at_utc
created_at_utc
updated_at_utc

Indexes:
(dedupe_key, result_at_utc)
(delivery_id)

Canonical durability decision:
Persistent system-of-record is persistence.delivery_attempts (see Durable Persistence Spec §6.5).
adapter_results is an in-adapter transient canonicalization surface and MUST be committed via deterministic 1:1 field mapping into delivery_attempts.

---

7) OpenClaw Invocation + Normalized Provider Response Contract
Adapter MUST use OpenClaw messaging send surface only.

7.1 External dependency declaration
Raw provider response envelope is external dependency.
Adapter MUST normalize raw provider response into typed internal shape before classification.

7.2 Normalized provider response schema (fully typed)
OpenClawSendResponseNormalized:
normalized_outcome_class: NormalizedOutcomeClass
provider_status_code: string|null
provider_receipt_ref: string|null
provider_error_class_hint: ErrorClass|null
provider_error_message_sanitized: string|null
provider_confirmation_strength: ProviderConfirmationStrength
raw_observed_at_utc: UtcTimestamp (ephemeral normalization timestamp; MUST NOT be persisted to delivery_attempts/adapter_audit)

---

8) Mapping Precedence + Map Schemas (Closed)
Precedence:
1) Policy Override Map
2) Provider Map
3) Unknown-response fallback

8.1 Policy Override Map schema
key source: provider_status_code from normalized provider response
key type: string (exact match, case-sensitive)
if provider_status_code is null -> skip Policy Override Map
value:
status: DeliveryStatus
reason_code: ReasonCode
retry_eligible: bool
delivery_confidence: DeliveryConfidence

8.2 Provider Map schema
key source: normalized_outcome_class
key type: NormalizedOutcomeClass
value:
status: DeliveryStatus
reason_code: ReasonCode
error_class: ErrorClass
retry_eligible: bool

8.3 Mechanical BLOCKED vs FAILED_PERMANENT rule
pre-send/precondition failure => BLOCKED
post-send permanent provider rejection => FAILED_PERMANENT

8.4 Unknown fallback
If no map match:
status=FAILED_TRANSIENT
reason_code=FAILED_PROVIDER_TRANSIENT
retry_classification_source=fallback_default

---

9) DeliveryConfidence Derivation + Status Matrix
9.1 Derivation rule (apply before matrix validation)
Map provider confirmation strength:
accepted -> provider_accepted
confirmed -> provider_confirmed
none -> none

9.2 Allowed (status, delivery_confidence) pairs
(DELIVERED, provider_accepted)
(DELIVERED, provider_confirmed)
(FAILED_TRANSIENT, none)
(FAILED_PERMANENT, none)
(SUPPRESSED, none)
(BLOCKED, none)

Additional explicit rule:
delivery_confidence=provider_confirmed => provider_accept_only MUST be false
provider_accept_only=true iff (status=DELIVERED and delivery_confidence=provider_accepted)

Forbidden pairs are contract violations.

---
10) Idempotency and Replay Contract
Idempotent on attempt_id then dedupe_key.

Config:
adapter_dedupe_window_ms default 86400000

Rules:
1) duplicate attempt_id => return stored canonical result
2) new attempt_id + same dedupe_key in window => return prior canonical result, no second visible send
3) outside window => normal path

Replay immutability:
unchanged: status, reason_code, delivery_confidence, retry_eligible, error_object, correlation IDs, result_at_utc
replay fields: replay_indicator, replay_source

---
11) Capture-Only Activation
Activation source:
runtime_mode: RuntimeMode

If capture_only:
block side effects pre-send
output:
status=BLOCKED
reason_code=CAPTURE_ONLY_BLOCKED
retry_eligible=false

---

12) Capability Contract + Alias Resolution Interaction
Capabilities:
supports_channel_hints: ChannelHint[]
supports_media: bool
supports_priority: bool
supports_delivery_receipts: bool
supports_target_resolution: bool

Rules:
§13 target validation always runs.
supports_target_resolution controls whether active alias resolution may be attempted.
if resolution is unsupported or resolution attempt fails => deterministic BLOCKED with reason_code=FAILED_CAPABILITY_UNSUPPORTED.
unsupported operation outside capabilities => deterministic BLOCKED with reason_code=FAILED_CAPABILITY_UNSUPPORTED.

---

13) WhatsApp Target Contract (Probe-Validated)
Accepted canonical target regex:
^(?:whatsapp:)?(?:\+?[1-9]\d{6,14}|\d{10,30}@g\.us)$
Normalization: strip optional whatsapp: prefix before provider invocation.

Alias forms (e.g. whatsapp:g-caleb-loop) are non-canonical for send and MUST be pre-resolved.

Behavior:
unresolved alias => BLOCKED (no send attempt)
adapter MUST normalize accepted target format before invocation

---

14) Health Snapshot Contract
Authoritative source:
last successful adapter health probe snapshot.

Fields:
state: HealthState
snapshot_ts_utc: UtcTimestamp
max_health_age_ms: int > 0
health_fail_mode: HealthFailMode
details_json: JsonObject|null
details_schema_version: int|null
event_ts_utc: UtcTimestamp

Null rule:
details_json null => details_schema_version null
details_json non-null => details_schema_version non-null

Initial:
DOWN until first valid snapshot

Staleness:
strict -> DOWN
non_strict -> DEGRADED
---

15) Retry Bounds (Adapter Internal)
Config:
adapter_max_internal_retries: int >= 0
adapter_retry_backoff_ms: int >= 0
adapter_internal_retry_window_ms: int >= 0

Strict defaults: both zero.
No hidden retries beyond configured bounds.

---

16) Audit Record Schema (Typed, Separated Event Type)
Logical table: adapter_audit

Fields:
event_ts_utc: UtcTimestamp
audit_event_type: AuditEventType
subject_type: SubjectType
delivery_id: IdString
attempt_id: IdString
trace_id: IdString
causation_id: IdString
dedupe_key: ShortString
status: DeliveryStatus
reason_code: ReasonCode
delivery_confidence: DeliveryConfidence
provider_status_code: string|null
provider_receipt_ref: string|null
replay_indicator: bool
replay_source: ReplaySource
result_at_utc: UtcTimestamp

Must link to canonical result via attempt_id.
---

17) P2-B Scope Definition
P2-B means:
implement OpenClaw adapter per this spec
run conformance suite
produce evidence artifacts
land with traceable receipts and rollback references

---

18) Evidence Gates (Validation Required)
Required artifacts:
1) mapping matrix tests
2) policy override map tests
3) provider map tests
4) unknown fallback tests
5) delivery_status/delivery_confidence matrix tests
6) replay/idempotency tests
7) replay immutability tests
8) capture_only block tests
9) capability reject tests
10) WhatsApp target-shape tests
11) health snapshot/stale tests
12) retry bounds tests
13) correlation + audit schema tests

Activation remains validation_required until all are attached and passing.

---

19) Safety Rules
sanitize provider errors
no secret leakage
no side effects in capture_only
no silent channel substitution outside declared policy
no free-text reason-code drift