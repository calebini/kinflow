source_message_id: 1484906957486817381
installed_by_instruction_id: KINFLOW-SPEC-INSTALL-COMMS-ADAPTER-V017-20260321-001
run_code: 4321
installed_utc: 2026-03-21T16:37:02Z
status: canonical

Kinflow Comms Adapter Contract (Master Copy v0.1.8)
0) Convergence Declaration
Phase: MID
Tier Target: T5-STRICT
Tier-3 Critical Dimensions (declared):
1) Schema enforceability
2) Reason-code determinism
3) Retry determinism + attempt traceability
4) Replay/idempotency determinism
5) Capability conformance integrity
6) Correlation propagation integrity
Declared Couplings (mandatory):
1) Failure taxonomy ↔ reason_code enum
2) Retry policy ↔ attempt traceability
3) Runtime mode ↔ execution side effects
4) Delivery status ↔ delivery confidence
5) Idempotency ↔ replay semantics
6) Correlation IDs ↔ end-to-end propagation
7) Health state ↔ freshness/TTL rules
8) Capability flags ↔ conformance evidence

---

1) Purpose
Define a deterministic, transport-agnostic delivery contract for Kinflow so transport implementations are replaceable without changing scheduler/policy core behavior.

---

2) Normative Language
Control-path requirements use:
MUST
MUST NOT
MAY (non-critical optional surfaces only)
Undefined behavior is prohibited.

---

3) Authoritative ReasonCode Binding (Delegated Completeness)
Adapter runtime MUST bind to:
reason_code_spec_path: specs/KINFLOW_REASON_CODES_CANONICAL.md
reason_code_spec_version
reason_code_spec_hash (SHA-256, LF-normalized UTF-8 bytes)

Completeness model:
This contract intentionally delegates reason-code value listing to the canonical artifact above.
reason_code_spec_hash is the frozen-set validation mechanism.
Startup MUST fail on hash/version mismatch.

---
4) Interface
MUST implement:
1) send(outbound: OutboundMessage) -> DeliveryResult
2) health() -> AdapterHealth
3) capabilities() -> AdapterCapabilities

Optional:
4) resolve_target(target_ref: str) -> ResolvedTarget
If absent, supports_target_resolution=false.

---

5) Type System and Format Rules
Scalar formats
*_id: regex ^[a-zA-Z0-9._:-]{1,128}$
UTC timestamps: RFC3339 UTC (Z or +00:00)
enums: closed sets only

JSON definition
Top-level MUST be JSON object (UTF-8).
Nested arrays/scalars are allowed only per field schema.
JSON fields are versioned with paired *_schema_version.

---

6) Request Contract (OutboundMessage)
Required:
delivery_id: id
attempt_id: id
attempt_index: int >= 1
trace_id: id
causation_id: id
channel_hint: ChannelHint
target_ref: string(1..256)
subject_type: SubjectType
body_text: string(1..4000)
dedupe_key: string(1..256)
priority: enum {normal,high}
created_at_utc: utc-timestamp

Optional:
payload_json: json|null
payload_schema_version: int|null
metadata_json: json|null
metadata_schema_version: int|null

Null/version coupling:
JSON non-null => schema version non-null
JSON null => schema version null


Payload field-name alignment rule:
- Canonical outbound payload field names are payload_json/payload_schema_version.
- Producers still emitting structured_payload_json/structured_payload_schema_version MUST map deterministically:
  structured_payload_json -> payload_json
  structured_payload_schema_version -> payload_schema_version
- Dual-write with divergent values is prohibited.

---

7) Response Contract (DeliveryResult)
Required:
status: DeliveryStatus
reason_code: ReasonCode
retry_eligible: bool
provider_receipt_ref: string|null
provider_status_code: string|null
provider_error_text: string|null (sanitized)
provider_accept_only: bool
delivery_confidence: DeliveryConfidence
result_at_utc: utc-timestamp
error_object: ErrorObject|null
replay_indicator: bool
replay_source: enum {attempt_id_hit,dedupe_key_window_hit,none}
delivery_id: id
attempt_id: id
trace_id: id
causation_id: id

Status/confidence coupling
status=DELIVERED:
delivery_confidence in {provider_confirmed, provider_accepted}
provider_accept_only=true iff delivery_confidence=provider_accepted
status!=DELIVERED:
delivery_confidence=none
provider_accept_only=false

---

8) Error Contract (ErrorObject)
Required when status in {FAILED_TRANSIENT,FAILED_PERMANENT,SUPPRESSED,BLOCKED}:
error_class: enum {transient,permanent,policy,config,unknown}
normalized_code: ReasonCode
provider_code: string|null
retry_classification_source: enum {policy_override,provider_map,fallback_default}
message_sanitized: string
details_json: json|null
details_schema_version: int|null

Null/version coupling:
details_json non-null => version non-null
details_json null => version null

Equality constraint:
if error_object present:
error_object.normalized_code MUST equal DeliveryResult.reason_code
Bidirectional presence closure:
if status=DELIVERED, error_object MUST be null

---

9) Closed Enums
ChannelHint
discord
signal
telegram
whatsapp
openclaw_auto

SubjectType
event_reminder
daily_overview
DeliveryStatus
DELIVERED
FAILED_TRANSIENT
FAILED_PERMANENT
SUPPRESSED
BLOCKED

DeliveryConfidence
provider_confirmed
provider_accepted
none

Enum expansion requires version bump.

---

10) Capability Allowlist Authority
supports_channel_hints[] is authoritative.

Any channel_hint outside allowlist MUST be deterministically blocked:
status=BLOCKED
reason_code=FAILED_CAPABILITY_UNSUPPORTED
retry_eligible=false

Behavior outside declared capabilities MUST be rejected deterministically.

---

11) Mapping Precedence (Deterministic)
Failure mapping order:
1) policy override map
2) explicit provider code map
3) fallback default transient (FAILED_PROVIDER_TRANSIENT)
No alternate order allowed.

---

12) Retry Semantics (Deterministic, Bounded, Observable)
Policy source (authoritative runtime config):
adapter_max_internal_retries
adapter_retry_backoff_ms
adapter_internal_retry_window_ms

Defaults:
zero (no internal retries)

Rules:
internal retries remain within same attempt_id
adapter MUST NOT emit intermediate lifecycle states externally
only final consolidated DeliveryResult is externally observable per attempt
adapter MUST NOT create new attempt identities internally
hidden retries beyond config are prohibited

Exhaustion determinism:
if canonical includes FAILED_RETRY_EXHAUSTED: MUST use it
if absent: MUST map to FAILED_PROVIDER_PERMANENT and set:
error_object.retry_classification_source='fallback_default'
error_object.details_json.exhaustion_fallback_applied=true

---

13) Delivery Lifecycle Transition Rules
Allowed externally observable transitions over retries:
FAILED_TRANSIENT -> DELIVERED
FAILED_TRANSIENT -> FAILED_PERMANENT
exhaustion path per section 12

Undefined transitions are prohibited.

---

14) Replay and Dedupe Semantics
Ownership:
user-visible dedupe: dedupe_key
attempt identity: attempt_id

Policy source (authoritative runtime config):
adapter_dedupe_window_ms (default: 86400000)

Rules:
1) duplicate attempt_id:
return prior canonical result
no side effect
replay_indicator=true, replay_source=attempt_id_hit
2) new attempt_id + same dedupe_key within dedupe window:
no second visible send
return prior canonical result
replay_indicator=true, replay_source=dedupe_key_window_hit
3) outside dedupe window:
normal send path
replay_indicator=false, replay_source=none

Replay immutability:
replay MUST return prior canonical result unchanged for:
status
reason_code
delivery_confidence
retry_eligible
error_object
correlation IDs

Only replay fields may change:
replay_indicator
replay_source
result_at_utc MUST remain unchanged on replay (no silent narrowing/broadening policy)

Replay/lifecycle interaction:
replay MUST NOT create lifecycle transitions or advancement.

Clock source:
system UTC evaluation time only.

Window precedence with daemon idempotency:
adapter_dedupe_window_ms governs provider-side duplicate suppression.
Daemon idempotency_window_hours governs scheduler replay identity.
When both apply, adapter suppression MUST prevent second visible send.

---

15) Health Contract (AdapterHealth)
Required:
state: {UP,DEGRADED,DOWN}
snapshot_ts_utc: utc-timestamp
max_health_age_ms: int > 0
details_json (json object)
details_schema_version: int
health_fail_mode: {strict,non_strict}

Validity:
health_fail_mode MUST be present and valid
missing/invalid => startup failure

Initial state:
before first valid health snapshot, health().state MUST be DOWN

TTL rule:
stale if now_utc - snapshot_ts_utc > max_health_age_ms
strict => DOWN
non_strict => DEGRADED
stale UP prohibited

Extension-field rule (deterministic):
Adapters MAY emit adapter-specific health extension fields, but extensions MUST NOT redefine or conflict with required AdapterHealth fields.
`snapshot_ts_utc` remains the sole freshness/TTL authority for this contract.

---

16) Capability Contract (AdapterCapabilities)
Required:
supports_channel_hints: ChannelHint[]
supports_media: bool
supports_priority: bool
supports_delivery_receipts: bool
supports_target_resolution: bool

Conformance artifact (required):
docs/conformance/adapter-capabilities-<adapter>-<version>.json
each true capability MUST map to passing test IDs
negative cases MUST verify blocked behavior for false capabilities

---

17) Correlation Propagation Contract
delivery_id, attempt_id, trace_id, causation_id MUST:
be preserved from request through response
be present directly in DeliveryResult
be present in linked audit envelope if audit pipeline is separate

Omission/mutation is non-conformant.

Daemon→Adapter correlation handoff (Execution Envelope):
- Execution Envelope.trace_id MUST be copied to OutboundMessage.trace_id unchanged.
- Execution Envelope.causation_id MUST be copied to OutboundMessage.causation_id unchanged.
- Execution Envelope.cycle_id MUST be included in OutboundMessage.metadata_json.daemon_cycle_id (string) with metadata_schema_version non-null.
- Adapter DeliveryResult MUST echo trace_id/causation_id unchanged and include daemon_cycle_id in linked audit payload.


---

18) Runtime Mode Coupling
If Kinflow runtime mode is capture_only:
adapter MUST NOT send outbound messages
adapter MUST return:
status=BLOCKED
reason_code=CAPTURE_ONLY_BLOCKED
retry_eligible=false

---

19) OpenClaw Gateway Adapter (Default v1)
OpenClawGatewayAdapter is default and MUST satisfy this contract fully.

---

20) Required Evidence Gates
1) request/result/error schema validation
2) mapping precedence matrix
3) unsupported channel deterministic block
4) retry-bound determinism + exhaustion fallback behavior
5) replay behavior (attempt_id, dedupe_key, window binding)
6) status/confidence coupling
7) replay immutability + no-lifecycle-advance proof
8) health TTL + fail_mode validity + initial-state proof
9) capability truth + conformance artifact linkage (positive + negative cases)
10) capture_only no-side-effect proof
11) reason-code binding version/hash proof
12) correlation propagation end-to-end proof

---

21) Prohibited Behaviors
free-text reason codes
open-ended runtime enums
uncontrolled hidden retries
duplicate visible send inside dedupe window
status/confidence inconsistency
replay mutation of canonical outcome fields
stale health reported as UP
missing correlation IDs in DeliveryResult