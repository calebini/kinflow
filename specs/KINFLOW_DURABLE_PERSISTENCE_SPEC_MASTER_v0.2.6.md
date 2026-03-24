source_message_id: 1484524158040670408
installed_by_instruction_id: KINFLOW-SPEC-INSTALL-PERSISTENCE-V026-20260320-001
run_code: 4318
installed_utc: 2026-03-20T12:16:17Z
status: canonical

Kinflow Durable Persistence Spec (Master Copy v0.2.7 — Convergence-Hardened)
0) Convergence Declaration (Non-Negotiable)
Convergence Phase: MID
Convergence Tier: T5-STRICT
Declared Couplings:
1) Failure taxonomy ↔ reason_code enum
2) Runtime mode ↔ execution paths
3) Retry policy ↔ delivery_attempts

---

1) Purpose, Scope, Status
Purpose
Provide durable, deterministic persistence for Kinflow so event/reminder/delivery/audit behavior survives restarts and supports replay/recovery without semantic drift.

In Scope
SQLite durable storage
Fully materialized enum governance
FK + CHECK + migration integrity
Transaction-bounded lifecycle writes
Deterministic recovery/batching
Capture-only runtime enforcement
Convergence evidence hooks

Out of Scope
Feature expansion
External DB engines
Calendar integrations
Distributed write coordination
---

2) Deterministic Modality and Language Contract
All normative statements use:
MUST
MUST NOT
MAY

Soft wording is prohibited in control-path requirements.

---

3) Canonical Enums (Materialized; Version-Governed)
3.1 Enum tables
enum_reason_codes
code TEXT PRIMARY KEY
class TEXT NOT NULL CHECK (class IN ('success','mutation','blocked','runtime','transient','permanent','suppressed'))
active INTEGER NOT NULL CHECK (active IN (0,1))
version_tag TEXT NOT NULL

enum_audit_stages
stage TEXT PRIMARY KEY
active INTEGER NOT NULL CHECK (active IN (0,1))
version_tag TEXT NOT NULL

enum_reminder_status
status TEXT PRIMARY KEY
terminal_flag INTEGER NOT NULL CHECK (terminal_flag IN (0,1))
schedulable_flag INTEGER NOT NULL CHECK (schedulable_flag IN (0,1))
version_tag TEXT NOT NULL
enum_attempt_status
status TEXT PRIMARY KEY
version_tag TEXT NOT NULL

3.2 Baseline enum content (v0.2.7)
Reminder statuses
scheduled (terminal=0, schedulable=1)
attempted (terminal=0, schedulable=1)
delivered (terminal=1, schedulable=0)
failed (terminal=1, schedulable=0)
suppressed (terminal=1, schedulable=0)
invalidated (terminal=1, schedulable=0)
blocked (terminal=0, schedulable=0)

Attempt statuses
attempted
delivered
failed
suppressed
blocked

Reason-code canonical set (minimum)
Success:
DELIVERED_SUCCESS

Lifecycle stage success (non-delivery audit stages):
INTAKE_RECEIVED
CONFIRMATION_ACCEPTED
SCHEDULE_QUEUED

Mutation:
RESOLVER_EXPLICIT
RESOLVER_MATCHED
RESOLVER_NO_MATCH
TZ_EXPLICIT
TZ_HOUSEHOLD_DEFAULT
UPDATED_REGENERATED
CANCEL_INVALIDATED
Blocked:
RESOLVER_AMBIGUOUS
TZ_MISSING
FAILED_CONFIG_INVALID_TARGET
FAILED_CAPABILITY_UNSUPPORTED
CAPTURE_ONLY_BLOCKED
BLOCKED_CONFIRMATION_REQUIRED
Transient:
FAILED_PROVIDER_TRANSIENT
VERSION_CONFLICT_RETRY
Permanent:
FAILED_PROVIDER_PERMANENT
FAILED_RETRY_EXHAUSTED
Suppressed:
SUPPRESSED_QUIET_HOURS
Runtime:
TZ_FALLBACK_USED
RECOVERY_RECONCILED
FAIRNESS_BOUND_EXCEEDED
DB_RECONNECT_EXHAUSTED
STARTUP_VALIDATION_FAILED
SHUTDOWN_GRACE_EXCEEDED

Audit stages (minimum)
intake
resolver
confirmation
timezone
mutation
schedule
delivery
recovery
system

Enum governance rule
Enum expansion/rename/removal MUST occur via migration and schema version bump.

---

4) Canonical State Model
Reminder state classes
Terminal: delivered|failed|suppressed|invalidated
Schedulable: scheduled|attempted
Blocked: blocked (not schedulable; not terminal in abstract)

Blocked lifecycle
Blocked rows are immutable in-place.
Blocked rows MUST NOT transition directly to scheduled.
Recovery from blocked state MUST occur only via:
1) explicit regeneration command, or
2) new event-version generation after configuration repair.

---

5) Authoritative vs Derived Fields
Authoritative
events.current_version
event_versions.start_at_local_iso
event_versions.event_timezone
reminders.trigger_at_utc
reminders.next_attempt_at_utc
reminders.recipient_timezone_snapshot
reminders.tz_source
system_state.runtime_mode
system_state.max_retry_attempts
system_state.idempotency_window_hours

Derived/materialized
reminder rows generated from version policy
delivery attempts generated from execution events

Historical UTC trigger/attempt values MUST NOT be recomputed on read/replay.

---
6) Canonical Schema
6.1 events
event_id TEXT PRIMARY KEY
current_version INTEGER NOT NULL
status TEXT NOT NULL CHECK (status IN ('active','cancelled','completed'))
created_at_utc TEXT NOT NULL
updated_at_utc TEXT NOT NULL

6.2 event_versions
event_id TEXT NOT NULL
version INTEGER NOT NULL
title TEXT NOT NULL
start_at_local_iso TEXT NOT NULL
end_at_local_iso TEXT NULL
all_day INTEGER NOT NULL DEFAULT 0
event_timezone TEXT NOT NULL
participants_json TEXT NOT NULL
audience_json TEXT NOT NULL
reminder_offset_minutes INTEGER NOT NULL
source_message_ref TEXT NOT NULL
intent_hash TEXT NOT NULL
normalized_fields_hash TEXT NOT NULL
created_at_utc TEXT NOT NULL
PRIMARY KEY (event_id,version)
FOREIGN KEY (event_id) REFERENCES events(event_id)

6.3 delivery_targets
target_id TEXT PRIMARY KEY
person_id TEXT NOT NULL
channel TEXT NOT NULL
target_ref TEXT NOT NULL
timezone TEXT NULL
quiet_hours_start INTEGER NOT NULL DEFAULT 23
quiet_hours_end INTEGER NOT NULL DEFAULT 7
is_active INTEGER NOT NULL DEFAULT 1
updated_at_utc TEXT NOT NULL
INDEX (person_id)
INDEX (channel,target_ref)

6.4 reminders
reminder_id TEXT PRIMARY KEY
dedupe_key TEXT NOT NULL UNIQUE
event_id TEXT NOT NULL
event_version INTEGER NOT NULL
recipient_target_id TEXT NOT NULL
offset_minutes INTEGER NOT NULL
trigger_at_utc TEXT NOT NULL
next_attempt_at_utc TEXT NULL
attempts INTEGER NOT NULL DEFAULT 0
status TEXT NOT NULL
recipient_timezone_snapshot TEXT NOT NULL
tz_source TEXT NOT NULL
last_error_code TEXT NULL
created_at_utc TEXT NOT NULL
updated_at_utc TEXT NOT NULL
FOREIGN KEY (event_id,event_version) REFERENCES event_versions(event_id,version)
FOREIGN KEY (recipient_target_id) REFERENCES delivery_targets(target_id)
FOREIGN KEY (status) REFERENCES enum_reminder_status(status)
UNIQUE (event_id,event_version,offset_minutes,recipient_target_id)
INDEX (trigger_at_utc,reminder_id)

Sentinel contract for unresolved timezone:
recipient_timezone_snapshot='UNKNOWN'
tz_source='MISSING'
last_error_code='TZ_MISSING'
status='blocked'
6.5 delivery_attempts
attempt_id TEXT PRIMARY KEY
reminder_id TEXT NOT NULL
attempt_index INTEGER NOT NULL
attempted_at_utc TEXT NOT NULL
status TEXT NOT NULL
reason_code TEXT NOT NULL -- MUST be canonical from KINFLOW_REASON_CODES_CANONICAL.md; successful delivery stage MUST use DELIVERED_SUCCESS; every non-delivery stage row MUST carry an explicit canonical reason code
provider_ref TEXT NULL
provider_status_code TEXT NULL
provider_error_text TEXT NULL
provider_accept_only INTEGER NOT NULL DEFAULT 0
delivery_confidence TEXT NOT NULL CHECK (delivery_confidence IN ('provider_confirmed','provider_accepted','none'))
result_at_utc TEXT NOT NULL
trace_id TEXT NOT NULL
causation_id TEXT NOT NULL
source_adapter_attempt_id TEXT NULL
FOREIGN KEY (reminder_id) REFERENCES reminders(reminder_id)
FOREIGN KEY (status) REFERENCES enum_attempt_status(status)
FOREIGN KEY (reason_code) REFERENCES enum_reason_codes(code)
UNIQUE (reminder_id,attempt_index)

Status distinction:
reminder.status = lifecycle of trigger
delivery_attempts.status = outcome of attempt

Canonical persistence model decision:
`delivery_attempts` is the single canonical persistence surface for adapter outcomes.
`adapter_results` is an adapter-local transient shape only and MUST deterministically map 1:1 into `delivery_attempts` before commit.

Canonical adapter→persistence field mapping (deterministic):
adapter.delivery_id -> (resolved) reminder_id via scheduler attempt context
adapter.attempt_id -> delivery_attempts.source_adapter_attempt_id
adapter.status -> delivery_attempts.status (DELIVERED->delivered; FAILED_TRANSIENT/FAILED_PERMANENT->failed; SUPPRESSED->suppressed; BLOCKED->blocked)
adapter.reason_code -> delivery_attempts.reason_code
adapter.provider_receipt_ref -> delivery_attempts.provider_ref
adapter.provider_status_code -> delivery_attempts.provider_status_code
adapter.provider_error_text -> delivery_attempts.provider_error_text
adapter.provider_accept_only -> delivery_attempts.provider_accept_only
adapter.delivery_confidence -> delivery_attempts.delivery_confidence
adapter.result_at_utc -> delivery_attempts.result_at_utc
adapter.trace_id -> delivery_attempts.trace_id
adapter.causation_id -> delivery_attempts.causation_id
6.6 message_receipts
channel TEXT NOT NULL
conversation_id TEXT NOT NULL
message_id TEXT NOT NULL
correlation_id TEXT NOT NULL
intent_hash TEXT NOT NULL
result_json TEXT NOT NULL
created_at_utc TEXT NOT NULL
PRIMARY KEY (channel,conversation_id,message_id)
INDEX (intent_hash,created_at_utc)

6.7 audit_log (append-only)
audit_index INTEGER PRIMARY KEY AUTOINCREMENT
ts_utc TEXT NOT NULL
trace_id TEXT NOT NULL
causation_id TEXT NOT NULL
correlation_id TEXT NOT NULL
message_id TEXT NOT NULL
entity_type TEXT NOT NULL
entity_id TEXT NOT NULL
stage TEXT NOT NULL
reason_code TEXT NOT NULL -- MUST be canonical from KINFLOW_REASON_CODES_CANONICAL.md; successful delivery stage MUST use DELIVERED_SUCCESS; every non-delivery stage row MUST carry an explicit canonical reason code
payload_schema_version INTEGER NOT NULL
payload_json TEXT NOT NULL
FOREIGN KEY (stage) REFERENCES enum_audit_stages(stage)
FOREIGN KEY (reason_code) REFERENCES enum_reason_codes(code)

6.8 daily_overview_policy
policy_id TEXT PRIMARY KEY
recipient_scope TEXT NOT NULL
send_time_local TEXT NOT NULL
timezone TEXT NOT NULL
include_completed INTEGER NOT NULL DEFAULT 0
updated_at_utc TEXT NOT NULL
v0.2.7 scope note:
lifecycle-minimal stub; strict governance deferred to later phase.

6.9 system_state
key TEXT PRIMARY KEY
value_type TEXT NOT NULL CHECK (value_type IN ('int','string','bool','enum','json'))
value TEXT NOT NULL
updated_at_utc TEXT NOT NULL

Required keys:
runtime_mode (enum: normal|capture_only)
idempotency_window_hours (int)
max_retry_attempts (int)
adapter_dedupe_window_ms (int)

6.10 system_state_policy
key TEXT PRIMARY KEY
required INTEGER NOT NULL CHECK (required IN (0,1))
value_type TEXT NOT NULL
allowed_values_json TEXT NULL
min_int INTEGER NULL
max_int INTEGER NULL

Runtime MUST validate system_state against system_state_policy at startup.

6.11 schema_migrations
version TEXT PRIMARY KEY
checksum TEXT NOT NULL
applied_at_utc TEXT NOT NULL
dirty INTEGER NOT NULL DEFAULT 0

Checksum algorithm:
SHA-256 of canonical migration text bytes (UTF-8, LF normalized)

---
7) SQLite Enforcement Requirements
At every connection startup:
PRAGMA foreign_keys = ON MUST be executed.
Runtime MUST fail-fast if FK enforcement is inactive.

Recommended pragmas (policy-configurable):
journal_mode=WAL
synchronous=NORMAL or FULL

---

8) Runtime Mode ↔ Execution Path Coupling
runtime_mode=normal
intake, mutation, scheduling, delivery, recovery all enabled.
runtime_mode=capture_only
intake/follow-up/confirmation/persist/audit enabled.
scheduler execution MUST be blocked.
outbound delivery MUST be blocked.
blocked actions MUST emit CAPTURE_ONLY_BLOCKED.

This coupling is mandatory and test-gated.

---

9) Retry Policy ↔ Delivery Attempts Coupling
Retry scope is per reminder.
max_retry_attempts = authoritative from system_state (fallback default 3).
adapter_internal_retry_window_ms = authoritative adapter retry-window bound from runtime config/system_state when persisted.
Failed transient attempt increments reminder attempts.
If attempts exceed max, reminder transitions to failed + FAILED_RETRY_EXHAUSTED.
next_attempt_at_utc semantics:
NULL = no retry scheduled
non-NULL = authoritative next eligible retry instant

---

10) Failure Taxonomy ↔ Reason Code Coupling
Every failure class MUST map to canonical reason codes:

resolver ambiguity -> RESOLVER_AMBIGUOUS
version conflict -> VERSION_CONFLICT_RETRY
missing timezone -> TZ_MISSING
transient provider failure -> FAILED_PROVIDER_TRANSIENT
permanent provider failure -> FAILED_PROVIDER_PERMANENT
invalid target config -> FAILED_CONFIG_INVALID_TARGET
retry exhaustion -> FAILED_RETRY_EXHAUSTED
quiet-hours policy suppression -> SUPPRESSED_QUIET_HOURS
capture-only blocked side effect -> CAPTURE_ONLY_BLOCKED
reconciliation mutation -> RECOVERY_RECONCILED

Unmapped failures are prohibited.

Required emission points:
scheduler: timezone and scheduling decisions
delivery runner: attempt outcome and retry transitions
reconciler: recovery mutations
mutation engine: resolver/version/lifecycle transitions
audit writer: persisted reason_code for every stage record
audit writer: every emitted audit stage row MUST carry a canonical reason_code (NOT NULL + FK-valid)

---

11) Transaction and Concurrency Contract
For update/cancel mutations:
MUST use BEGIN IMMEDIATE.
MUST enforce optimistic version guard:
read v
insert v+1
update events.current_version with WHERE current_version=v
zero rows affected => rollback + VERSION_CONFLICT_RETRY

Backstop:
unique (event_id,version) prevents duplicate version insert races.

Future reminder invalidation predicate:
“future” means trigger_at_utc > mutation_now_utc.
overdue reminders remain eligible unless explicitly invalidated.

---
12) Recovery and Batching Contract
Due reminder fetch order MUST be:
ORDER BY trigger_at_utc ASC, reminder_id ASC

Batch loop MUST continue until:
1) no eligible reminders, OR
2) runtime limit reached.

Partial progress MUST preserve deterministic ordering across restarts/reruns.

---

13) Idempotency Contract
Primary replay identity:
(channel,conversation_id,message_id)
Secondary bounded dedupe:
intent_hash within configured window

Window clock:
MUST use system UTC clock at evaluation time
MUST NOT use event time/message payload time

Clock skew note:
accepted v0 boundary; host clock sync required operationally.

Daemon/adapter window precedence (deterministic):
1) adapter_dedupe_window_ms controls duplicate visible-send suppression at adapter boundary.
2) idempotency_window_hours controls daemon replay identity reuse.
3) If both windows apply, the stricter no-side-effect outcome MUST win; duplicate visible send remains prohibited.


---

14) Migration Safety Contract
Before migration (non-dev):
backup DB
schema fingerprint check
fail if any migration row has dirty=1

During migration:
set dirty=1
apply migration
verify SHA-256 checksum
set dirty=0 only on success

Failure on mismatch/dirty residue is mandatory.

---

15) Write Amplification Bound
Under retry/recovery bursts, system MUST tolerate repeated writes without violating:
dedupe invariants
idempotency invariants
deterministic convergence of reminder/delivery state

---

16) Verification/Evidence Hooks (Mandatory)
1) Restart durability proof
2) Replay determinism proof (ordering + batch continuation)
3) Capture-only invariant proof (no scheduling side effects, no outbound delivery)
4) Version-conflict proof emits VERSION_CONFLICT_RETRY
5) Reminder drift proof = zero
6) DST/cross-timezone replay consistency proof
7) FK enforcement proof (fails when foreign_keys off)
8) Enum enforcement proof (invalid stage/reason/status rejected)
9) TZ_MISSING blocked-row sentinel proof
10) Write amplification stress proof preserving invariants
---

17) Blast Radius and Rollback
Blast radius
state layer
scheduler/recovery transitions
audit write-path
idempotency behavior

rollback
set runtime to capture_only (contain side effects)
optional memory fallback flag (if retained)
preserve sqlite artifact for forensics
revert persistence integration commit set if required

---
18) Ownership Split
Tert: architecture/spec and acceptance gates
Vitruvius: implementation (schema/repos/migrations/recovery/tests)
Knuth: landing/check-in/verification receipts