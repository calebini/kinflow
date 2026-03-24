---
source_message_id: 1485226787330986095
installed_by_instruction_id: KINFLOW-SPEC-INSTALL-DAEMON-CONTRACT-V014-20260322-001
run_code: 4335
installed_utc: 2026-03-22T22:21:05Z
status: canonical
---

Kinflow Daemon Runtime Contract (Master Copy v0.1.4)
0) Convergence Declaration
Review Phase: FINAL
Tier Entry Mode: T5-STRICT
Activation Posture: STRICT (fail-closed on contract violations)

Tier-3 Critical Dimensions (declared)
1) Runtime ordering determinism
2) State-transition determinism
3) Capture-only side-effect isolation
4) Health/readiness determinism
5) Recovery fairness/starvation integrity
6) Failure/reconnect determinism

Declared Couplings (mandatory)
1) Runtime mode ↔ execution side effects
2) Tick scheduler ↔ fairness/starvation guarantees
3) Health state ↔ readiness semantics
4) Health freshness ↔ TTL/fail-mode policy
5) Reconnect policy ↔ daemon liveness/exit behavior
6) Reconciliation ordering ↔ replay determinism
7) Correlation semantics ↔ forensic traceability
8) Transaction scope ↔ partial-progress visibility/dedupe behavior

T5 Strict Entry Conditions
T5 activation is valid only when all required evidence gates in §18 pass with zero open blockers.

---

1) Purpose
Define deterministic daemon runtime behavior for Kinflow so scheduler/reconciliation execution is bounded, auditable, reproducible, and safe under restart/failure.

---
2) Canonical Clock and Time Source
2.1 Canonical clock
All runtime scheduling decisions MUST use:
system_utc_now (UTC wall clock)

2.2 Drift measurement
Per cycle:
scheduled_tick_ts
actual_start_ts
tick_drift_ms = actual_start_ts - scheduled_tick_ts

2.3 Overrun behavior
If cycle runtime exceeds tick interval:
daemon MUST skip sleep
daemon MUST proceed at next boundary
daemon MUST NOT execute burst catch-up loops
---

3) Runtime Process Model
Single-process deterministic loop with three cycle types:
1) execution cycle
2) reconciliation cycle
3) maintenance/health cycle

No unbounded worker spawning in v0.1.4.

---

4) Reconciliation Cadence Function (Closed)
Config:
daemon_tick_ms
reconcile_tick_ms
State:
last_reconcile_boundary_ms

Canonical function:
reconcile_boundary_ms = floor(system_utc_now_ms / reconcile_tick_ms) * reconcile_tick_ms
reconcile_due = reconcile_boundary_ms > last_reconcile_boundary_ms

Rules:
At most one reconciliation cycle per main loop iteration.
Missed intervals collapse to one due reconciliation.
No reconciliation burst replay within one loop.

---

5) Startup Contract (Deterministic Order)
Startup MUST execute in this exact order:
1) load config
2) validate config schema (fail-fast)
3) open DB connection
4) enforce PRAGMA foreign_keys=ON and verify active
5) run migration safety checks
6) load runtime state/config keys
7) initialize health state DOWN and is_ready=false
8) set is_ready=true only after successful startup validation
9) enter main loop with health DEGRADED
10) transition to UP only after first successful full cycle (§6)

Clarification:
is_ready=true means startup-valid and runnable, not runtime-healthy.

---

6) Full Cycle Success Predicate (Formal)
A loop iteration is a successful full cycle iff all hold:

1) runtime mode read succeeds
2) execution branch completes without fatal error (zero eligible rows allowed)
3) reconciliation branch (if due) completes without fatal error
4) cycle summary emission succeeds
5) no transaction remains open/failed

Health transition rule:
first successful full cycle transitions DEGRADED -> UP.

---

7) Main Loop Contract
Each iteration MUST execute in order:
1) compute now_ms
2) compute reconcile_due (§4)
3) read runtime_mode
4) run execution branch
5) run reconciliation branch if due
6) emit cycle summary
7) update last_reconcile_boundary_ms only if reconcile succeeded
8) apply sleep/overrun rule

---

8) Capture-Only Contract (Closed)
If runtime_mode=capture_only:
outbound side-effect execution MUST be blocked
lifecycle-advancing scheduler execution MUST be blocked
reconciliation is read-only except audit/diagnostic marker writes
lifecycle state mutation is prohibited

Emission mode:
CAPTURE_ONLY_BLOCKED MUST be emitted per blocked candidate row.

---

9) Reconciliation and Fairness Contract
9.1 Selection order
Due rows MUST be selected by:
ORDER BY trigger_at_utc ASC, reminder_id ASC

9.2 Bounded continuation
Per reconcile cycle:
process up to max_reconcile_batches_per_tick batches
each batch size <= max_reconcile_batch_size
9.3 Deferral definition
For eligible row r, increment deferral_tick_count(r) by 1 each daemon loop where:
r is eligible at loop start,
r is not processed that loop,
r is not blocked by allowed blocking reason.

9.4 Fairness bound
Oldest due row MUST satisfy:
deferral_tick_count(oldest_due) <= max_tick_deferral_for_oldest_due
unless blocked by allowed blocking reason enum.

Allowed blocking reasons (closed):
CAPTURE_ONLY_BLOCKED
TZ_MISSING
FAILED_CONFIG_INVALID_TARGET
SUPPRESSED_QUIET_HOURS
FAILED_PROVIDER_PERMANENT
If bound exceeded:
MUST emit fairness violation audit event with row identity + reason classification.

9.5 Assumption clause (explicit)
Fairness guarantee applies under bounded ingress/load:
effective_ingress_rate <= effective_service_capacity
and fixed snapshot eligibility semantics (§14).
If assumption fails, daemon MUST emit overload diagnostic events; no silent fairness claims.

9.6 Fixture baseline
Conformance fixture baseline:
max_tick_deferral_for_oldest_due=3

---

10) Correlation Semantics (Execution Envelope Generation + Scope)
Required fields:
cycle_id
trace_id
causation_id

Semantics:
cycle_id: unique per loop iteration within a daemon run
trace_id: daemon-run lineage id (stable for run)
causation_id: parent causal id for emission

Root-cause convention (closed):
root cycle emissions: causation_id = ROOT:<cycle_id>
startup-origin emissions: causation_id = ROOT:STARTUP:<trace_id>
shutdown-origin emissions: causation_id = ROOT:SHUTDOWN:<trace_id>

Restart behavior:
new daemon run MUST generate new trace_id
cycle_id uniqueness scope MUST not collide across runs (prefix or UUID scheme)

Daemon→Adapter handoff mapping (normative):
Execution Envelope = {cycle_id, trace_id, causation_id}.
For every outbound adapter invocation, daemon MUST pass:
- trace_id -> OutboundMessage.trace_id
- causation_id -> OutboundMessage.causation_id
- cycle_id -> OutboundMessage.metadata_json.daemon_cycle_id (with metadata_schema_version).

---

11) Health and Readiness Contract
States:
DOWN
DEGRADED
UP

Readiness:
is_ready=false initially
is_ready=true only after startup validation success

Initial state:
before first valid health snapshot, state=DOWN
Freshness policy:
max_health_age_ms required (>0)
health_fail_mode required (strict|non_strict)

Stale transition:
strict -> DOWN
non_strict -> DEGRADED
stale UP prohibited

Invalid/missing health_fail_mode => startup failure.

11.1 Canonical Health Snapshot Contract
Authoritative health snapshot object MUST include:
state
is_ready
snapshot_ts_utc (authoritative timestamp)
max_health_age_ms
health_fail_mode
last_successful_cycle_id
last_failure_reason_code (nullable)

Emission rules:
MUST emit on startup completion, each health transition, and at least every health_emit_interval_ms.

Freshness computation:
health_age_ms = system_utc_now_ms - snapshot_ts_utc_ms

---

12) DB Reconnect Policy (Closed)
Config:
db_reconnect_strategy (fixed|linear|exponential_capped)
db_reconnect_backoff_ms (>0)
db_reconnect_max_attempts (>0)
db_reconnect_max_backoff_ms (required when strategy=exponential_capped)

12.1 Delay formulas
Let n = attempt index starting at 1.

fixed: delay = db_reconnect_backoff_ms
linear: delay = db_reconnect_backoff_ms * n
exponential_capped: delay = min(db_reconnect_backoff_ms * 2^(n-1), db_reconnect_max_backoff_ms)

12.2 Attempt counter semantics
attempt counter resets only after successful reconnect and one successful full cycle.
partial connection that fails before cycle success does NOT reset counter.

12.3 Delay anchor semantics
delay clock starts at reconnect attempt completion time (failure return), not detection time.
12.4 Exhaustion behavior
On attempt exhaustion:
transition DOWN
emit reconnect-exhausted event
exit non-zero

No infinite reconnect loops allowed.

---

13) Config Schema (Authoritative Keys)
Required:
runtime_mode (normal|capture_only)
daemon_tick_ms (int >= 1000)
reconcile_tick_ms (int >= 5000)
max_due_batch_size (int >= 1)
max_reconcile_batch_size (int >= 1)
max_reconcile_batches_per_tick (int >= 1)
max_tick_deferral_for_oldest_due (int >= 1)
max_health_age_ms (int > 0)
health_fail_mode (strict|non_strict)
health_emit_interval_ms (int > 0)
idempotency_window_hours (int >= 0)
max_retry_attempts (int >= 0)
adapter_internal_retry_window_ms (int >= 0)
adapter_dedupe_window_ms (int >= 0)
shutdown_grace_ms (int > 0)
db_reconnect_strategy (fixed|linear|exponential_capped)
db_reconnect_backoff_ms (int > 0)
db_reconnect_max_attempts (int > 0)
db_reconnect_max_backoff_ms (int > 0 when exponential_capped)
max_consecutive_fatal_cycles (int > 0)
transaction_scope_mode (per_row|per_batch) (see §14 constraints)

Any missing/invalid required key => fail-fast startup.
---

14) Replay Determinism and Transaction Scope (Closed)
14.1 Transaction scope mode
For this contract version, transaction scope MUST be explicitly declared via config:
transaction_scope_mode = per_row OR per_batch

Mixed mode in one runtime is prohibited.

14.2 Conformance requirement
Implementation MUST provide conformance evidence for selected mode:
partial-progress visibility behavior
dedupe/duplicate-avoidance behavior
fairness implications under failure

14.3 Eligibility snapshot semantics
Eligibility set for each cycle is frozen at cycle-start snapshot:
rows becoming eligible mid-cycle are deferred to next cycle.

14.4 Determinism invariant scope
Invariant “same DB state + config + clock order => same transitions” applies under:
fixed transaction_scope_mode
fixed eligibility snapshot semantics
fixed ordering query
stable isolation assumptions documented by implementation.

---

15) Failure Model
Config invalid
startup fail-fast, non-zero exit
DB unavailable
bounded reconnect policy (§12)
exhaustion => DOWN + non-zero exit

Cycle exception
rollback active transaction
emit structured failure reason
continue unless fatal threshold exceeded

Fatal threshold
If consecutive fatal cycles > max_consecutive_fatal_cycles:
transition DOWN
exit non-zero deterministically

---

16) Logging and Audit Minimum
Per cycle MUST emit:
cycle_id
trace_id
causation_id
cycle_type
scheduled_tick_ts
actual_start_ts
tick_drift_ms
rows_scanned
rows_processed
rows_blocked
rows_failed
reason_code_counts

Required emissions:
startup success/failure
shutdown
capture-only blocked events
reconciliation mutations (RECOVERY_RECONCILED)
fairness violations
reconnect attempts/exhaustion

---

17) Runtime FSM (Normalized)
Transitions:

STARTING + startup_valid -> DEGRADED (is_ready=true)
DEGRADED + first_successful_full_cycle -> UP
UP + stale_health(strict) -> DOWN
UP + stale_health(non_strict) -> DEGRADED
UP|DEGRADED + reconnect_exhausted -> DOWN + exit
UP|DEGRADED + fatal_threshold_exceeded -> DOWN + exit
UP|DEGRADED + shutdown_signal -> SHUTTING_DOWN -> STOPPED

Each transition MUST emit required audit/log event with correlation semantics.

---

18) Evidence Gates (Conformance)
Must pass before daemon phase exit:

1) deterministic tick ordering proof
2) reconcile cadence proof (collapsed missed intervals, max one reconcile per loop)
3) bounded continuation proof
4) fairness/deferral bound proof (max_tick_deferral_for_oldest_due=3 fixture)
5) graceful shutdown no-corruption proof
6) capture-only no-side-effect proof (per-row blocked emission)
7) startup config fail-fast proof
8) health/readiness transition + snapshot freshness proof
9) reconnect strategy formula + exhaustion proof
10) correlation semantics proof (generation, root semantics, restart uniqueness)
11) transaction scope conformance proof for declared mode
12) replay determinism assumption conformance proof

---

19) Out-of-Scope Clarification
This contract does not define:
adapter/provider mapping internals
multi-process/distributed execution
deployment orchestration policy

Covered by adapter/deployment contracts.