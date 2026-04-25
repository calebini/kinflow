KINFLOW_PER_EVENT_DESTINATION_CONTRACT_MASTER_v0.1.6
## 1) Purpose

Define deterministic and enforceable per-event reminder destination routing for Kinflow with strict schema, strict validation boundary, replay-stable behavior, reason-code binding integrity, and CI-governed version control.

## 2) Scope Boundary

In-scope:

- per-event destination override
- channel-agnostic destination contract
- strict destination source precedence
- dual-phase validation
- dispatch-time authoritative snapshot
- replay/idempotency equivalence contract
- adapter validation output contract
- engine disposition mapping from adapter error taxonomy
- canonical reason-code structural binding
- migration + rollback contract requirements
- versioning + CI enforcement
Out-of-scope:

recurrence/series logic
audience/privacy delineation
per-offset destination overrides
multi-recipient routing matrix
cross-channel fanout
3) Normative Terms
MUST / MUST NOT: mandatory
SHOULD / SHOULD NOT: recommended
MAY: optional only when explicitly constrained
4) Strict Destination Schema
4.1 Channel Enum (Machine-Checkable)
Channel MUST be one of:

whatsapp
telegram
discord
signal
imessage
openclaw_auto
If external registry is used, registry version and compatibility must be CI-validated.

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
Nullability contract:

If status != ok: both MUST be null
If status == ok: both MUST be non-null and canonicalized
4.5 target_ref Contract
target_ref MUST satisfy:

non-empty trimmed string
max length: 512
no control characters
canonical form: <channel>:<value> OR adapter-accepted form that is canonicalized to namespaced form prior to execution
4.6 meta Envelope Contract
meta MAY be present with constraints:

JSON object only
max serialized size: 4096 bytes
allowed value types: JSON primitives/objects/arrays
MUST NOT contain executable directives
MAY include meta_schema_id for adapter-owned schema checks
5) Destination Source Precedence (Immutable)
Resolution order MUST be:

event_override
request_context_default
recipient_default
No implementation may reorder this.

6) Operating Agent vs Engine Boundary
Operating agent MUST derive and persist request_context_default.
Engine MUST consume resolved routing inputs deterministically.
Engine MUST NOT infer ingress/session routing context heuristically at dispatch-time.
7) Validation Timing (Dual-Phase Required)
Validation MUST run at: 1) write-time (event mutation) 2) dispatch-time (pre-send) Dispatch-time decision is authoritative if disagreement occurs. No send path MAY bypass dispatch-time validation.

8) Snapshot Authority and Optionality Constraints
Dispatch-time destination snapshot is authoritative.
Generation-time advisory snapshot MAY be stored for diagnostics only.
Advisory snapshot MUST NOT participate in any execution, precedence, replay, or idempotency decision path.
9) Missing Destination Terminal Behavior
If all destination sources are missing/unresolvable:

MUST fail terminally with reason_code=FAILED_CONFIG_INVALID_TARGET
MUST set:
destination_source=none
destination_resolution_status=missing
resolved_channel=null
resolved_target_ref=null
MUST emit deterministic audit event.
10) Invalid Override Terminal Behavior
If override exists but is invalid:

MUST fail with reason_code=FAILED_CONFIG_INVALID_TARGET
MUST NOT emit delivered-success state
MUST set:
destination_source=event_override
destination_resolution_status=invalid
resolved_channel=null
resolved_target_ref=null
Diagnostic fields (attempted_channel, attempted_target_ref) MAY be emitted separately, but canonical resolved fields MUST remain null.

11) Replay + Idempotency Contract
11.1 Authoritative Replay Tuple
Replay equivalence MUST bind to:

destination_source
destination_resolution_status
resolved_channel
resolved_target_ref
11.2 Time-Independent Equivalence
Replay equivalence is time-independent and tuple-only. Clock/timestamp deltas MUST NOT establish equivalence when tuple differs.

11.3 Retry Equivalence Rule
Across retries (T1, T2, ...):

same tuple => equivalent destination context
changed tuple => non-equivalent context (fail closed on equivalence assumptions)
12) Adapter Validation Boundary Contract (Strict)
Adapter validation output MUST be:

valid: bool
canonical_channel: Channel|null
canonical_target_ref: string|null
error_class: ErrorClass|null
error_code: ErrorCode|null
12.1 ErrorClass Enum
ErrorClass MUST be one of:

config
policy
transient
permanent
unknown
12.2 ErrorCode Contract
ErrorCode MUST satisfy:

lowercase namespaced form <adapter>.<domain>.<code>
regex: ^[a-z0-9]+(\.[a-z0-9_]+){2,}$
max length: 128
13) Engine Disposition by ErrorClass (Deterministic)
Given adapter output at dispatch-time:

config:
terminal failure, no retry
canonical reason: FAILED_CONFIG_INVALID_TARGET when destination-invalid lane
policy:
terminal policy failure/suppression per policy map, no blind retry
transient:
retry-eligible per retry policy
permanent:
terminal failure, no retry
unknown:
fail-closed with bounded retry policy (implementation-defined bounded default), then terminal per retry policy
Disposition mapping MUST be explicitly test-covered.

14) Canonical Reason-Code Structural Binding
Binding target: KINFLOW_REASON_CODES_CANONICAL.md

14.1 Required Registry Shape (Minimum)
Reason registry entries MUST structurally provide:

code
class
active
version_tag (or equivalent version field)
14.2 Binding Metadata Requirements
Contract binding metadata MUST include:

spec_version
spec_sha256
hash_algorithm=sha256
14.3 Compatibility Rule
Reason binding version/hash mismatch is non-conformant. CI MUST fail on missing/mismatched binding metadata or unresolved reason references.

15) Time Semantics (Authoritative Clocks)
15.1 Write-Time
Write-time validation uses write-path authoritative clock.

15.2 Dispatch-Time
Dispatch decision and authoritative destination snapshot use dispatch-path authoritative clock.

15.3 Retry-Time
Retry scheduling uses scheduler/dispatch clock and must preserve replay tuple semantics independent of timestamp changes.

16) Backward Compatibility + Migration Contract
Additive/reversible changes only.
Legacy events without override remain valid.
No destructive backfill.
Migration spec MUST include rollback steps and post-rollback invariants.
17) Minimum Test Obligations (Strict)
MUST include all:

override success path
request-context fallback path
recipient-default fallback path
all-sources-missing failure path
invalid-override failure path
write-time vs dispatch-time disagreement path
advisory snapshot non-participation path
replay tuple stability path
retry-ordering equivalence path:
same tuple across T1/T2 => equivalent
changed tuple => non-equivalent
adapter output-shape conformance
ErrorClass → engine disposition mapping
reason-binding mismatch hard-fail path
migration forward check
rollback reverse check
post-rollback invariants check
non-regression checks for existing delivery semantics
18) Migration + Rollback Concrete Check Set
Migration forward check MUST verify:

new optional destination fields present
legacy rows remain readable without override values
deterministic default routing unchanged for legacy events
Rollback reverse check MUST verify:

schema rollback applies cleanly
pre-existing core functionality preserved
no orphaned required references
Post-rollback invariants MUST verify:

scheduler still processes due reminders deterministically
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
missing required artifacts
reason-binding mismatch
schema/enum contract mismatch
required conformance test regression
21) PR Change Classification (Mandatory)
Each PR touching this lane MUST declare:

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
25) Final Strictness Acceptance Gate
Final promotion readiness requires:

all Section 17 tests pass
Section 18 migration/rollback checks pass
audit field conformance passes
CI enforcement gates pass
version tuple emission verified
reason-binding structural compatibility verified
independent scoring integrity satisfied
final-phase coupling alignment satisfied under rubric gate