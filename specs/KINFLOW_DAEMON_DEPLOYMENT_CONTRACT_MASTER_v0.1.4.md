KINFLOW_DAEMON_DEPLOYMENT_CONTRACT_MASTER_v0.1.4 (Master Cut, Final Round)
0) Convergence Declaration
Review Phase: MASTER_CANDIDATE
Activation Posture: STRICT (fail-closed on contract violations)
Scope: Deployment/supervision/operations plane for Kinflow daemon runtime adoption
Companion Runtime Contract: KINFLOW_DAEMON_RUNTIME_CONTRACT_MASTER_v0.1.4.md

1) Purpose
Define production deployment requirements so Kinflow dispatch runs as a robust always-on daemon process with deterministic ownership, auditable health, and explicit cutover from cron tick mode.

2) Non-Goals
No redefinition of daemon loop semantics from runtime contract
No adapter protocol redesign
No reminder/domain model changes

3) Global Config Binding Rule
All deployment-defined values MUST be externally configurable via deployment manifest or environment.
Contract does not require specific key names for every value in this document.
Contract does not assign numeric default values unless explicitly required by a companion runtime contract.

4) Canonical Dispatch Path
Canonical dispatch path: daemon process
Cron tick dispatch path: fallback only
Steady-state dual-active mode (daemon + cron dispatch simultaneously) is forbidden

5) Supervisor Contract (Canonical)
5.1 Required supervisor
systemd is mandatory for v0.1.x
pm2 is out-of-scope for v0.1.x

5.2 Required service properties
auto-start on boot: enabled
restart on failure: enabled
restart policy: exponential backoff + bounded retry ceiling
terminal fail-stable state required after retry ceiling (no infinite restart loop)
explicit start/stop/status/log commands documented
working directory and environment source pinned
stdout/stderr captured by journald

6) Singleton Ownership Contract (Concrete SQLite Lock)
Exactly one active dispatcher instance per runtime DB is permitted.

6.1 Canonical lock mechanism
SQLite lock-row mechanism is required (single approved method for v0.1.x)

6.2 Required lock safety properties
SQLite WAL mode is required
SQLite busy_timeout must be explicitly configured
lock-holder heartbeat must be present and updated during operation
lock takeover must be safe and must produce auditable evidence
stale-lock threshold must be explicitly defined and consistently enforced by deployment

6.3 Acquisition behavior
lock acquisition timeout: explicitly configured
if lock unavailable within configured timeout: fail-stop startup
exit non-zero
startup/config token: SINGLETON_LOCK_UNAVAILABLE

6.4 Prohibition
no alternate singleton mechanism in v0.1.x

7) Datasource Path Contract
7.1 Canonical default
/home/agent/projects/apps/kinflow/.anchor_runtime.sqlite

7.2 Override policy
override is permitted only when declared via external deployment configuration (manifest/env)
7.3 Fail-closed override rule
undeclared override usage => fail-stop with:
DB_PATH_OVERRIDE_UNDECLARED

7.4 Startup logging
daemon MUST log effective DB path at startup

8) Canonical Health Exposure Surface
8.1 Single surface rule
exactly one canonical health exposure surface is allowed in v0.1.x

8.2 Canonical surface + path
health file only:
/var/lib/kinflow/health.json

8.3 Interface requirement (not schema lock)
health file MUST include minimum information to represent:
current state
readiness
last successful cycle
last failure reason
freshness
strict internal field schema is intentionally out-of-scope

9) Alert Semantics
thresholds are wall-clock based
evaluation cadence is per-cycle
threshold values MUST be externally configurable (not hardcoded)
deployment must apply configured thresholds consistently

10) Security / Secret Source Contract
10.1 Canonical secret source
/etc/kinflow/daemon.env
permission MUST be chmod 600
10.2 Secret handling rules
secret changes require service restart (systemctl restart ...)
daemon MUST NOT cache secrets beyond process lifetime

10.3 Prohibited
secrets inline in systemd ExecStart
secrets in CLI args
secrets in logs/artifacts

Violation => fail-stop:
SECRET_SOURCE_POLICY_VIOLATION

11) Operational State Stamp (Derived State)
11.1 Canonical file
/var/lib/kinflow/dispatch_mode.state

Allowed values:
dispatch_mode=daemon
dispatch_mode=cron_fallback

11.2 Behavior
state stamp is derived, not operator-controlled
MUST be overwritten on daemon startup
manual edits are non-authoritative and must be ignored/overwritten
daemon SHOULD emit warning when manual tamper is detected before overwrite

12) Companion Contract Binding (Lightweight)
Startup MUST validate companion runtime contract version binding.

Required:
runtime contract version is explicitly checked at startup

If validation missing or mismatched:
fail-stop with:
CONTRACT_VERSION_VALIDATION_FAILED

Note:
hash-level coupling is out-of-scope for this deployment contract version

13) Cutover Contract (Cron -> Daemon)
Strict order:
1) validate daemon config + DB path + singleton gate
2) start daemon under systemd
3) verify first successful full cycle
4) disable cron dispatch entries
5) verify disable via canonical command + artifact + output hash
6) run smoke dispatch check
7) record cutover evidence + rollback handle

13.1 Canonical disable verification command
crontab -l || true
13.2 Verification scope
verification scope is limited to user crontab for v0.1.x

13.3 Valid disabled state
no active Kinflow dispatch entries present
commented lines do not count as active entries

14) Rollback Contract (Daemon -> Cron Fallback)
Strict order:
1) stop daemon systemd service
2) enable one canonical cron fallback dispatch job
3) verify fallback tick success
4) set state stamp to dispatch_mode=cron_fallback
5) capture rollback verification artifact + output hash

15) Runbook Minimum Requirements
Must include copy-paste commands for:
systemd install/enable/start/stop/restart/status
journald logs
singleton lock diagnostics
health file inspection
cutover
rollback
state stamp verification
contract version validation check
exact canonical fallback cron command used in rollback

16) Acceptance Gates (GO Criteria)
All required:
1) systemd service installed and boot-persistent
2) singleton lock gate pass + contention fail path validated
3) WAL mode + busy_timeout configuration proven
4) canonical/default-or-declared DB path proven
5) effective DB path startup log present
6) first successful full cycle proven
7) cron dispatch entries disabled post-cutover with canonical command artifact + hash
8) smoke dispatch success
9) alert semantics demonstrated against configured thresholds
10) secret-source policy compliance proven
11) state stamp overwrite behavior proven
12) companion contract version validation proven
13) rollback drill successful with verification artifact + hash

17) Evidence Artifact Requirements
Required artifacts:
systemd unit snapshot
systemctl status proof
journald startup logs (DB path, readiness, version validation)
singleton lock proof (pass + contention)
WAL/busy_timeout proof
health file proof
cron before/after verification outputs
smoke dispatch output
state stamp proof
rollback drill proof

Output hash proof is required only for:
cutover cron-disable verification artifact
rollback verification artifact

18) Required Final Receipt Lines
DAEMON_DEPLOYMENT_STATUS: GO|NO_GO
CANONICAL_DISPATCH_PATH: daemon|cron_fallback
CRON_DISPATCH_DISABLED: YES|NO
SINGLETON_GUARD: PASS|FAIL
WAL_MODE: PASS|FAIL
BUSY_TIMEOUT: PASS|FAIL
HEALTH_SURFACE: /var/lib/kinflow/health.json
VERSION_VALIDATION: PASS|FAIL
BLOCKERS: <count>