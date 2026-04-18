KINFLOW_DAEMON_RUNNER_IMPLEMENTATION_SPEC_MASTER_v0.1.3 (Master Cut)
0) Convergence Declaration
Review Phase: MASTER_CANDIDATE
Activation Posture: STRICT (fail-closed on contract violations)
Scope: Executable daemon launcher seam only
Companion specs:
KINFLOW_DAEMON_RUNTIME_CONTRACT_MASTER_v0.1.4.md
KINFLOW_DAEMON_DEPLOYMENT_CONTRACT_MASTER_v0.1.4.md

1) Purpose
Define the concrete executable runner that instantiates and drives Kinflow daemon runtime semantics as a long-lived process suitable for systemd supervision.

2) Non-Goals
No changes to runtime contract semantics
No changes to deployment contract policy
No adapter/notification rendering redesign
3) Canonical Entrypoint
Required script:
/home/agent/projects/apps/kinflow/scripts/daemon_run.py
Runner execution mode:
long-lived foreground process (systemd owns lifecycle)

4) Startup Contract (Runner Layer, Ordered)
Runner MUST execute startup in this order:

1) load external config/env
2) validate required config presence/shape
3) validate contract version bindings (§5)
4) resolve effective DB path
5) initialize singleton guard machinery
6) acquire singleton lock and verify ownership
7) initialize store/adapter/runtime bindings
8) initialize health surface
9) initialize state stamp (dispatch_mode=daemon)
10) enter main loop

Critical rules:
Runner MUST acquire and verify singleton ownership before any stateful runtime initialization.
If lock acquisition times out or ownership cannot be proven, runner exits non-zero with LOCK_ACQUIRE_FAILED.
State stamp write occurs after step 7 succeeds and before loop entry; health may still be starting with is_ready=false.

5) Version Binding Validation (Explicit)
Runner MUST compare externally configured expected versions against observed versions for:
runtime contract
deployment contract

Hash-level coupling is out-of-scope in v0.1.3.

On missing/mismatch:
fail-stop token: CONTRACT_VERSION_VALIDATION_FAILED
runner MUST NOT enter loop.

6) Canonical Runner Fail Tokens (Closed Set)
STARTUP_CONFIG_MISSING
STARTUP_CONFIG_INVALID
CONTRACT_VERSION_VALIDATION_FAILED
DB_OPEN_FAILED
LOCK_ACQUIRE_FAILED
HEALTH_WRITE_FAILED
RUNTIME_CYCLE_FATAL
FATAL_THRESHOLD_EXCEEDED
GRACEFUL_SHUTDOWN_TIMEOUT

No unregistered runner fail tokens are permitted in v0.1.3.

7) Clock Source Guidance
Monotonic clock MUST be used for:
interval scheduling decisions
sleep timing
drift/elapsed computations where feasible
Wall-clock UTC MUST be used for:
emitted timestamps
health/state file timestamps
audit/log surface timestamps

8) Main Loop Contract (Runner Layer)
Per iteration, runner MUST:
1) compute scheduled and actual tick timestamps
2) execute one runtime cycle
3) update health surface
4) refresh singleton heartbeat
5) emit structured cycle summary
6) apply sleep/overrun rule (§11)
No unbounded worker/process/thread spawning in v0.1.3.

9) Health Surface Contract
Canonical health file:
/var/lib/kinflow/health.json

9.1 Minimum wire shape (required fields)
Health file MUST include at minimum:
state
is_ready
snapshot_ts_utc
last_successful_cycle_id
last_failure_reason_code
health_age_ms

9.2 Runner-level health state enum (minimum)
starting
ready
degraded
stopping
failed

9.3 is_ready semantics
is_ready MUST be true only after successful startup validation and at least one successfully completed cycle.
is_ready MUST be false in starting, stopping, and failed.
is_ready behavior in degraded MUST be implementation-consistent and documented; recommended default is true when invariant-preserving cycle execution continues.

9.4 Freshness semantics
snapshot_ts_utc is authoritative freshness anchor.
health_age_ms is advisory/best-effort at write time.

9.5 Health write failure policy
startup inability to create/write health surface => fatal (HEALTH_WRITE_FAILED)
runtime health write failure => cycle failure + structured event; process exits only if fatal threshold is exceeded
10) Cycle Identity Semantics
trace_id: unique per process run
cycle_seq: monotonic integer starting at 1
canonical cycle_id:
<trace_id>:<cycle_seq>

Requirements:
cycle_id format MUST be deterministic
sequence MUST be strictly monotonic within a run

11) Sleep/Overrun Behavior
Runner schedules against configured tick boundary.
If a cycle overruns tick interval:
skip sleep
continue at next boundary evaluation
do not run burst catch-up replay loops
12) Fatal Cycle Semantics + Threshold
12.1 RUNTIME_CYCLE_FATAL definition
A cycle is fatal when invariant-preserving cycle completion cannot be guaranteed and the failure must count toward consecutive fatal threshold.

Contained business/data issues that are cycle-local and do not violate runtime invariants are non-fatal cycle failures.

12.2 Threshold policy source
threshold value is externally configured
runner MUST fail-stop with FATAL_THRESHOLD_EXCEEDED when threshold is crossed

13) Singleton Guard + Takeover Safety
Runner MUST:
acquire singleton lock before stateful runtime init
refresh heartbeat during operation
fail-stop on acquisition timeout/failure (LOCK_ACQUIRE_FAILED)

Takeover is permitted only when:
prior heartbeat age exceeds configured stale threshold
takeover+acquire is atomic
new owner verifies exclusive ownership immediately post-takeover
no competing runner may observe successful ownership for the same lock epoch

Stale-owner determination MUST rely on singleton guard’s canonical liveness basis.
Persisted UTC timestamps are required for audit evidence but are not by themselves sufficient as sole liveness oracle unless lock implementation explicitly defines them as such.

14) Singleton Takeover Evidence
On takeover, runner MUST emit evidence event with minimum fields:
event: LOCK_TAKEOVER
previous_owner_id
new_owner_id
previous_heartbeat_ts_utc
takeover_ts_utc
stale_threshold_ms
db_path
pid
hostname

Artifact location:
<evidence_root>/singleton/takeover_events.jsonl

15) State Stamp Behavior
Canonical stamp file:
/var/lib/kinflow/dispatch_mode.state

Rules:
derived state only
write stamp after lock acquisition and successful runtime initialization
overwrite on startup
treat manual edits as non-authoritative (ignore/overwrite)

16) Exit Behavior
exit 0 only on controlled graceful shutdown
fail-stop exits non-zero with canonical fail token
terminal record MUST be structured single-line JSON record including:
final_status
fail_token (if any)
trace_id
last_cycle_id
pid
hostname
owner_id

17) Logging Contract
structured logs MUST be single-line JSON records
terminal line MUST be single-line JSON record
startup/singleton/terminal records MUST include pid/hostname/owner_id
secrets MUST NOT appear in logs
18) Runner-Level State Transitions (Minimum)
starting -> ready
ready -> degraded
degraded -> ready
* -> stopping
* -> failed

Transitions MUST be observable via structured events.

19) systemd Compatibility Contract
Runner MUST be suitable for:
ExecStart=<python3 ... scripts/daemon_run.py>
foreground process model
SIGTERM/SIGINT graceful handling within configured grace
journald-readable output via JSONL lines

20) Acceptance Criteria
1) runner enters steady-state loop only after all startup gates pass
2) startup order enforces lock acquisition prior to stateful init
3) version binding validation enforced per §5
4) fail tokens restricted to closed set (§6)
5) health file emitted and updated with required minimum wire shape (§9.1)
6) is_ready semantics proven per §9.3
7) runner does not enter loop if startup health surface create/write fails
8) cycle_id format deterministic and sequence monotonic
9) overrun behavior conforms to §11
10) fatal cycle classification + threshold enforcement proven
11) singleton acquire/fail/takeover safety + evidence proven
12) state stamp write timing and overwrite behavior proven
13) graceful shutdown and fail-stop exits proven
14) structured logs validated as single-line JSON records
15) systemd execution compatibility proven

21) Evidence Required
startup gate/order proof
version validation proof
cycle summary logs
health snapshots + readiness transition proof
startup health-write failure/no-loop-entry proof
overrun behavior proof
singleton acquire/fail/takeover artifacts
fatal-threshold trip artifact
state stamp timing proof
shutdown/terminal JSON record proof
systemd execution proof
finalization block with RUN_FINALIZED: YES

22) Required Final Lines
DAEMON_RUNNER_IMPL_STATUS: GO|NO_GO
VERSION_VALIDATION: PASS|FAIL
LOCK_GUARD: PASS|FAIL
HEALTH_SURFACE: PASS|FAIL
READINESS_SEMANTICS: PASS|FAIL
CYCLE_ID_SEMANTICS: PASS|FAIL
OVERRUN_POLICY: PASS|FAIL
FATAL_THRESHOLD_POLICY: PASS|FAIL
BLOCKERS: <count>