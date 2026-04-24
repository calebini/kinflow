KINFLOW_USER_RUNBOOK_MASTER.md
version: v1.2.9
status: draft
owner: kinflow
last_updated_utc: 2026-04-24T17:30:00Z
source_instruction_id: KINFLOW-USER-RUNBOOK-MASTER-CUT-v1_2_9-20260424-001
run_code: runbook-mastercut-20260424-v129
installed_utc: pending

Header Note
This is an as-built operator runbook (practical usage), not a normative API spec.
---

1) Preflight Sanity Check (Run First)
export KINFLOW_ROOT="${KINFLOW_ROOT:-/home/agent/projects/apps/kinflow}"
echo "KINFLOW_ROOT=${KINFLOW_ROOT}"
test -d "${KINFLOW_ROOT}" || { echo "ERROR: invalid KINFLOW_ROOT"; exit 1; }
test -d "${KINFLOW_ROOT}/src" || { echo "ERROR: src path missing"; exit 1; }
python3 --version || { echo "ERROR: python3 not available"; exit 1; }
cd "${KINFLOW_ROOT}" || { echo "ERROR: cannot cd to KINFLOW_ROOT"; exit 1; }
git status --short


If preflight fails, stop and fix environment before any mutation commands.

---
2) Quick Start (Exact Commands)
Run from:

cd "${KINFLOW_ROOT}"


2.1 Create event
PYTHONPATH=src python3 scripts/operator_create.py


2.2 Update event
PYTHONPATH=src python3 scripts/operator_update.py


2.3 Cancel event
PYTHONPATH=src python3 scripts/operator_cancel.py


2.4 List events/reminders
Option A (today/upcoming summary):

PYTHONPATH=src python3 scripts/operator_smoke.py
Option B (direct engine seam):

PYTHONPATH=src python3 - <<'PY'
from ctx002_v0.engine import FamilySchedulerV0
s = FamilySchedulerV0()
print(s.active_events)
PY


Note: Option B shows engine seam behavior and may not reflect persisted shared runtime state across sessions.

---

3) What Success Looks Like
Illustrative shape only; field names and availability may vary by path.
Operational expectation: successful mutations include identity, action, and status signals.

event_id: evt_9f3a2
action: create
status: committed
timestamp_utc: 2026-03-28T22:41:12Z
version: v0


---

4) Script Behavior Notes (Important)
operator_create.py runs a direct create flow.
operator_update.py currently demonstrates update behavior by creating a baseline event first, then updating it.
operator_cancel.py currently demonstrates cancel behavior by creating a baseline event first, then cancelling it.
operator_smoke.py is a smoke/list-proxy flow.

Update/cancel scripts currently include baseline-create scaffolding and are not exact mirrors of all production interaction paths.

---

5) Input Model (Operator Mental Model)
Illustrative model only; exact field names and required inputs may vary by callable path.

Create-like mental model:

{
"title": "Movie Night",
"datetime": "2026-04-03T20:00:00",
"timezone": "Europe/Paris",
"reminder_offset_minutes": 30
}


For update/cancel flows, a stable event identifier (event_id or equivalent) is required.

---

6) Practical Operator Examples (Capability-True)
“Schedule Movie Night on April 3 at 8 PM, with reminder offset 30 minutes before.”
“Move Movie Night to 8:30 PM and keep the 30-minute reminder offset.”
“Change reminder offset to 60 minutes before for event evt_123.”
“Cancel Movie Night.”
“List upcoming reminders for next 7 days.”
---

7) Failure Taxonomy (Operator)
Use deterministic failure class + raw error detail.

ENVIRONMENT_ERROR: invalid path, missing dependency, wrong working directory
VALIDATION_ERROR: missing or invalid required inputs
RUNTIME_ERROR: exception/tool failure during execution
STATE_ERROR: conflict with existing event/state transition constraints
PATH_UNAVAILABLE: callable mutation path not available in current runtime context

---

8) Safety Rules (Practical)
Clarify missing required fields before mutate.
Normalize timezone before commit.
Use explicit reminder offsets (minutes) for deterministic reminder timing.
Apply idempotency discipline:
reuse the same idempotency key for retries of the same intent
rotate to a new key for semantic changes
Never claim success without actual execution result.

---

9) Golden Path Walkthrough (End-to-End)
Run preflight sanity checks (Section 1).
Create an event (operator_create.py) with explicit reminder offset.
Verify via listing (operator_smoke.py and/or direct seam).
Run update flow (operator_update.py) and confirm updated status/output.
Run cancel flow (operator_cancel.py) and confirm cancellation outcome.
Re-list and verify expected final state.
---

10) Runtime Availability Behavior
If invocation path is unavailable, return deterministic failure classification with exact failing step/error text.

---

11) Destination Routing (Per-Event Override)
11.1 What this enables
Kinflow can route reminders per event instead of only using recipient default destination.

Destination source precedence is fixed:

event_override
request_context_default
recipient_default

11.2 Operator responsibilities
At event create/update time:

derive ingress channel/context
persist request_context_default in mutation payload
set/clear event_override intentionally
do not rely on dispatch-time heuristic inference

The engine consumes persisted routing inputs deterministically; it does not infer ingress context at send-time.

11.3 Destination validation behavior
Validation is dual-phase:
write-time validation (mutation path)
dispatch-time validation (authoritative pre-send check)

Dispatch-time result is authoritative on disagreement.

11.4 Failure behavior (deterministic)
If destination cannot be resolved from any source:

terminal failure
reason_code=FAILED_CONFIG_INVALID_TARGET
no delivered-success emission

If event_override is invalid:

terminal failure
reason_code=FAILED_CONFIG_INVALID_TARGET
canonical resolved destination fields remain null
diagnostic attempted values may be emitted separately

11.5 target_ref constraints
max length: 256
non-empty trimmed string
no control characters
canonicalized through adapter validation path

11.6 Replay / idempotency note
Destination tuple equivalence in this feature is feature-scoped and does not redefine global replay identity semantics.

11.7 Concrete create/update payload examples
Create with request-context default + per-event override:
{
"title": "Canary Swim",
"datetime": "2026-04-25T19:30:00",
"timezone": "Europe/Paris",
"reminder_offset_minutes": 30,
"request_context_default": {
"channel": "whatsapp",
"target_ref": "whatsapp:120363425701060269@g.us"
},
"event_override": {
"channel": "whatsapp",
"target_ref": "whatsapp:120363425701060269@g.us",
"meta": {
"meta_schema_id": "dest.v1"
}
}
}


Update to set/replace override:

{
"event_id": "evt-123",
"reminder_offset_minutes": 45,
"request_context_default": {
"channel": "whatsapp",
"target_ref": "whatsapp:120363425701060269@g.us"
},
"event_override": {
"channel": "whatsapp",
"target_ref": "whatsapp:120363425701060269@g.us"
}
}


Update to clear override (falls back to precedence chain):

{
"event_id": "evt-123",
"event_override": null
}


---
12) Explicit Verification Commands
Run from repo root:

cd /home/agent/projects/apps/kinflow


12.1 Unit/targeted checks
PYTHONPATH=src pytest -q


12.2 Compile check
python3 -m compileall src scripts


12.3 Daemon health snapshot (if daemon is active in environment)
journalctl -u kinflow-daemon.service -n 200 -o cat | tail -n 200


12.4 DB latest delivery attempt check
python3 - <<'PY'
import sqlite3
con = sqlite3.connect('/home/agent/projects/apps/kinflow/.anchor_runtime.sqlite')
con.row_factory = sqlite3.Row
row = con.execute("""
SELECT attempt_id, reminder_id, status, reason_code, provider_ref, provider_status_code, attempted_at_utc
FROM delivery_attempts
ORDER BY attempted_at_utc DESC
LIMIT 1
""").fetchone()
print(dict(row) if row else None)
con.close()
PY


12.5 Verify destination precedence evidence in logs
bash
journalctl -u kinflow-daemon.service -n 500 -o cat | rg 'destination_source|FAILED_CONFIG_INVALID_TARGET|cycle_summary'


---

13) Troubleshooting Quick Map
FAILED_CONFIG_INVALID_TARGET:
invalid/missing destination source resolution
check override payload, request-context default persistence, recipient-default fallback
dispatch validation fail after write-time pass:
adapter canonicalization mismatch or stale destination value
unexpected fallback source:
verify precedence and recorded destination_source audit field
reminder time mismatch:
verify event datetime + timezone + reminder_offset_minutes
---

14) Known Limits / Open Clarifications
A single frozen canonical alias is not yet enforced beyond current script paths.
Receipt field completeness may vary by callable path.
Ambiguity-disambiguation reachability from all user paths should continue to be validated in UAT.

---

15) Ops Appendix (Non-Runtime Semantics)
CI required checks
branch protection
merge policy

(Operational governance context; not user runtime behavior.)