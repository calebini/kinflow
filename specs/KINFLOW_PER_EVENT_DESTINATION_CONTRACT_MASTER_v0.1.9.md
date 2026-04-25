title: KINFLOW Per-Event Destination Contract Master
version: v0.1.9
status: MASTER_CANDIDATE
date_utc: 2026-04-23
initiative: CTX-002
supersedes: KINFLOW_PER_EVENT_DESTINATION_CONTRACT_MASTER_v0.1.8
scope_source: KINFLOW_PER_EVENT_DESTINATION_SCOPE_MASTER_v1.1
rubric_source: /home/agent/ontology-core/governance/convergence-rubric/CONVERGENCE_RUBRIC_MASTER_v6.md

KINFLOW_PER_EVENT_DESTINATION_CONTRACT_MASTER_v0.1.9
0) Convergence Declaration
Review Phase: mid
Convergence Target: final
Tier 5 Entry Mode: strict
Status Flag (non-rubric): MASTER_CANDIDATE
Lane Scope: CTX-002 per-event destination resolution and dispatch snapshot semantics.

Compatibility Anchors:
/home/agent/projects/apps/kinflow/specs/KINFLOW_PER_EVENT_DESTINATION_SCOPE_MASTER_v1.1.md
/home/agent/projects/apps/kinflow/specs/KINFLOW_COMMS_ADAPTER_CONTRACT_MASTER_v0.1.8.md
/home/agent/projects/apps/kinflow/specs/KINFLOW_OC_ADAPTER_IMPLEMENTATION_SPEC_MASTER_v0.2.4.md
/home/agent/projects/apps/kinflow/specs/KINFLOW_DURABLE_PERSISTENCE_SPEC_MASTER_v0.2.6.md
/home/agent/projects/apps/kinflow/specs/KINFLOW_REASON_CODES_CANONICAL.md (v1.0.6)

Declared Couplings:
Terminology ↔ Data Contracts
State Model ↔ Lifecycle
Decision Rules ↔ Failure Handling
Time Semantics ↔ Ordering
Idempotency ↔ Replay
destination_precedence ↔ audit_provenance
operating_agent_boundary ↔ fallback_determinism
adapter_validation_boundary ↔ canonical_reason_binding
dispatch_snapshot_authority ↔ idempotency_replay_stability
error_taxonomy ↔ engine_disposition
migration_contract ↔ rollback_integrity

Tier 3 Critical Dimensions:
destination schema enforceability
precedence determinism
dual-phase validation determinism
dispatch snapshot authority
replay/idempotency stability
reason-binding structural integrity
retry/exhaustion semantic consistency
CI/version governance enforceability

Phase precondition note:
Declared phase mid is rubric-valid.
Final-phase promotion remains contingent on independent scoring/gate satisfaction.

---

1) Purpose
Define deterministic and enforceable per-event reminder destination routing for Kinflow with strict schema, strict source precedence, dual-phase validation, authoritative dispatch snapshots, replay/idempotency integrity, explicit reason-code binding compatibility, and CI-governed versioning/migration gates.

2) Scope Boundary
In-scope:
per-event destination override
channel-agnostic destination contract
strict source precedence
dual-phase validation (write-time + dispatch-time)
authoritative dispatch snapshot persistence
scoped destination-tuple replay checks for this feature lane
adapter validation output contract
deterministic engine disposition mapping by adapter error class
additive migration + rollback checks
CI/governance gates

Out-of-scope:
recurrence/series logic
audience/privacy controls
per-offset destination overrides
multi-recipient routing matrix
cross-channel fanout
redefinition of global replay identity model

Execution-lane note:
Schema/contract are channel-agnostic.
This slice MUST NOT introduce bypass behavior that violates existing OC adapter seam and delivery evidence invariants.

3) Normative Terms
MUST / MUST NOT = mandatory
SHOULD / SHOULD NOT = recommended
MAY = optional only when explicitly constrained

4) Strict Destination Schema
4.1 Channel Enum (Machine-Checkable)
Channel MUST be one of:
discord
signal
telegram
whatsapp
openclaw_auto
Enum expansion requires explicit contract version bump and CI enum-conformance updates.

4.2 Destination Source Enum
destination_source MUST be one of:
event_override
request_context_default
recipient_default
none

4.3 Destination Resolution Status Enum
destination_resolution_status MUST be one of:
ok
invalid
missing

4.4 Canonical Resolved Fields
resolved_channel: Channel|null
resolved_target_ref: string|null

Nullability:
status != ok => both MUST be null
status == ok => both MUST be non-null and adapter-canonical

4.5 target_ref Contract (Width-Aligned)
Input target_ref MUST satisfy:
non-empty trimmed string
max length 256 (aligned with current adapter contract)
no control characters

Resolved/canonical target_ref:
MUST equal adapter canonical_target_ref output
MUST be deterministic for same input + adapter config
persisted canonical format is adapter-defined, but MUST be deterministic and audit-recoverable
4.6 meta Envelope Contract
meta MAY be present with constraints:
JSON object only
max serialized size 4096 bytes
values limited to valid JSON types
MUST NOT contain executable directives
MAY include meta_schema_id for adapter-owned schema checks

5) Destination Source Precedence (Immutable)
Resolution order MUST be:
1) event_override
2) request_context_default
3) recipient_default

No implementation MAY reorder this precedence.

6) Operating Agent vs Engine Boundary
Operating agent MUST derive and persist request_context_default in event mutation payloads.
Engine MUST consume persisted routing inputs deterministically.
Engine MUST NOT infer ingress/session routing context heuristically at dispatch-time.

7) Validation Timing (Dual-Phase Required)
Validation MUST run at:
1) write-time (event mutation path)
2) dispatch-time (pre-send)

Dispatch-time is authoritative on disagreement.
No send path MAY bypass dispatch-time validation.

8) Snapshot Authority and Optionality Constraints
Dispatch-time destination snapshot is authoritative.
Authoritative snapshot MUST be persisted with each delivery attempt.
Generation-time/advisory snapshot MAY be stored for diagnostics only.
Advisory snapshot MUST NOT participate in execution, precedence, replay, or idempotency decisions.
9) Missing Destination Terminal Behavior
If all destination sources are missing/unresolvable:
MUST fail with reason_code=FAILED_CONFIG_INVALID_TARGET
MUST persist:
destination_source=none
destination_resolution_status=missing
resolved_channel=null
resolved_target_ref=null
MUST persist attempt status as failed
MUST NOT emit delivered-success state
MUST emit deterministic audit event

10) Invalid Override Terminal Behavior
If override exists but is invalid:
MUST fail with reason_code=FAILED_CONFIG_INVALID_TARGET
MUST persist:
destination_source=event_override
destination_resolution_status=invalid
resolved_channel=null
resolved_target_ref=null
attempted_channel / attempted_target_ref MAY be emitted diagnostically
canonical resolved fields MUST remain null
MUST NOT emit delivered-success state

11) Replay + Idempotency Contract (Scoped)
11.1 Authoritative Destination Tuple (Feature-Scoped)
For this feature lane, destination-context equivalence MUST bind to:
destination_source
destination_resolution_status
resolved_channel
resolved_target_ref

11.2 Time-Independent Equivalence
Destination-context equivalence is tuple-only.
Clock/timestamp deltas MUST NOT establish equivalence when tuple differs.

11.3 Retry Equivalence Rule
Across retries (T1, T2, ...):
same tuple => equivalent destination context
changed tuple => non-equivalent destination context

11.4 Scope Guard
This tuple contract MUST NOT redefine global replay identity outside this feature slice.
Existing global replay/idempotency semantics remain canonical unless changed by separate contract slice.

12) Adapter Validation Boundary Contract (Strict)
12.1 Required Output Shape
Adapter destination validation output MUST be:
valid: bool
canonical_channel: Channel|null
canonical_target_ref: string|null
error_class: ErrorClass|null
error_code: ErrorCode|null

12.2 ErrorClass Enum
ErrorClass MUST be one of:
config
policy
transient
permanent
unknown

12.3 ErrorCode Contract
ErrorCode MUST satisfy:
lowercase namespaced form: <adapter>.<domain>.<code>
regex: ^[a-z0-9]+(\.[a-z0-9_]+){2,}$
max length 128

12.4 Shape Closure Rules
valid=true => canonical fields non-null; error fields null
valid=false => canonical fields null; error_class non-null; error_code SHOULD be non-null when available

13) Engine Disposition by ErrorClass (Deterministic)
Given adapter validation output at dispatch-time:

config:
terminal failure
no retry
canonical reason: FAILED_CONFIG_INVALID_TARGET (destination-invalid lane)

policy:
terminal policy/capability failure
no blind retry
canonical reason from policy map (default FAILED_CAPABILITY_UNSUPPORTED)

transient:
retry-eligible
canonical reason: FAILED_PROVIDER_TRANSIENT

permanent:
terminal failure
no retry
canonical reason: FAILED_PROVIDER_PERMANENT

unknown:
retry-eligible until max_retry_attempts exhaustion (deterministic default)
on exhaustion, terminal reason MUST be FAILED_RETRY_EXHAUSTED (canonical exhaustion semantics)

Disposition mapping MUST be explicitly test-covered.
14) Canonical Reason-Code Structural Binding
Binding targets:
/home/agent/projects/apps/kinflow/specs/KINFLOW_REASON_CODES_CANONICAL.md
runtime DB enum_reason_codes table

14.1 Required Structural Compatibility
The system MUST validate:
markdown registry: canonical code/class compatibility
persistence registry (enum_reason_codes): active/version_tag compatibility expectations

14.2 Binding Metadata Requirements
Binding metadata MUST include:
spec_version
spec_sha256

Hash algorithm handling:
algorithm is fixed to sha256 by contract
optional hash_algorithm field MAY be present; if present, MUST equal "sha256"

14.3 Compatibility Rule
Binding mismatch is non-conformant.
Startup and CI MUST fail on:
missing/mismatched binding metadata
unresolved reason references
structural incompatibility between canonical registry and persisted enum rows

15) Time Semantics (Authoritative Clocks)
Write-time: write-path authoritative clock
Dispatch-time: dispatch-path authoritative clock
Retry-time: scheduler/dispatch authoritative clock, while preserving tuple-equivalence semantics independent of timestamps

16) Backward Compatibility + Migration Contract
Additive/reversible changes only
Legacy events without override remain valid
No destructive backfill
Migration spec MUST include rollback steps and post-rollback invariants

17) Minimum Test Obligations (Strict)
MUST include:
override success path
request-context fallback path
recipient-default fallback path
all-sources-missing failure path
invalid-override failure path
write-time vs dispatch-time disagreement path
advisory snapshot non-participation path
feature-scoped destination tuple stability path
retry-ordering equivalence path (same tuple equivalent, changed tuple non-equivalent)
adapter output-shape conformance
ErrorClass -> engine disposition mapping
explicit exhaustion semantic check (FAILED_RETRY_EXHAUSTED)
reason-binding mismatch hard-fail path
migration forward check
rollback reverse check
post-rollback invariants check
non-regression checks for existing delivery evidence/seam semantics
non-regression check confirming global replay identity unchanged by this slice

18) Migration + Rollback Concrete Check Set
Migration forward check MUST verify:
new optional destination fields present (event override + request_context_default + attempt snapshot fields)
legacy rows remain readable without override values
deterministic legacy routing unchanged when no override/context default is provided
field width alignment (target_ref <= 256) enforced consistently

Rollback reverse check MUST verify:
schema rollback applies cleanly
pre-existing core functionality preserved
no orphaned required references

Post-rollback invariants MUST verify:
deterministic due-reminder processing preserved
canonical reason-code linkage remains valid
no false delivered semantics introduced

19) Versioning Requirements (Mandatory)
Implementation MUST maintain:
ENGINE_VERSION
SCHEMA_VERSION
CONTRACT_SET_VERSION

Bump policy:
schema-impacting => SCHEMA_VERSION
contract semantic/shape => CONTRACT_SET_VERSION
behavior-only engine => ENGINE_VERSION

Runtime MUST emit version tuple on startup and health/state surfaces.

20) CI Enforcement Requirements (Mandatory)
For governed paths, CI MUST fail on:
missing/incorrect version bump
declared change-class mismatch
missing required conformance artifacts
reason-binding mismatch
schema/enum contract mismatch
required test regression
missing migration/rollback evidence for schema-classified changes
width alignment violations (target_ref contract vs adapter contract)

If pinned canonical artifacts are altered, freeze-manifest process/gates remain mandatory.
21) PR Change Classification (Mandatory)
Each PR touching this lane MUST declare one:
no-version-bump
behavior-patch
contract-boundary-change
schema-change

22) Delivery Invariants
This contract MUST NOT alter:
delivery evidence gates
seam classifier core semantics
canonical delivered-success semantics

Only destination resolution behavior changes.

23) Security/Safety Constraints
Validation MUST be explicit and deterministic.
Unvalidated targets MUST NOT be used for send.
Ambiguous destination state MUST fail closed.
Failure provenance MUST be audit-visible.

24) Hard Out-of-Scope Guard
This contract MUST NOT introduce:
recurrence
audience/privacy controls
per-offset destination semantics
multi-recipient routing matrix
cross-channel fanout

25) Final Strictness Acceptance Gate
Promotion readiness requires:
all Section 17 tests pass
Section 18 migration/rollback checks pass
audit field conformance passes
CI enforcement gates pass
version tuple emission verified
reason-binding structural compatibility verified
no regressions in existing delivery evidence/seam invariants
independent non-author scoring confirmation for rubric gate advancement
