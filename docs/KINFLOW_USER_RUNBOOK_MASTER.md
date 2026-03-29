# KINFLOW_USER_RUNBOOK_MASTER.md

version: v1.2.7  
status: draft  
owner: kinflow  
last_updated_utc: 2026-03-28T23:54:00Z  
source_instruction_id: KINFLOW-USER-RUNBOOK-INSTALL-v1_2_7-20260329-001  
run_code: 4385  
installed_utc: 2026-03-29T00:08:30Z

## Header Note

This is an as-built operator runbook (practical usage), not a normative API spec.

---

## 1) Preflight Sanity Check (Run First)

```bash
export KINFLOW_ROOT="${KINFLOW_ROOT:-/home/agent/projects/apps/kinflow}"
echo "KINFLOW_ROOT=${KINFLOW_ROOT}"
test -d "${KINFLOW_ROOT}" || { echo "ERROR: invalid KINFLOW_ROOT"; exit 1; }
test -d "${KINFLOW_ROOT}/src" || { echo "ERROR: src path missing"; exit 1; }
python3 --version || { echo "ERROR: python3 not available"; exit 1; }
cd "${KINFLOW_ROOT}" || { echo "ERROR: cannot cd to KINFLOW_ROOT"; exit 1; }
git status --short
```

If preflight fails, stop and fix environment before any mutation commands.

---

## 2) Quick Start (Exact Commands)

Run from:

```bash
cd "${KINFLOW_ROOT}"
```

### 2.1 Create event

```bash
PYTHONPATH=src python3 scripts/operator_create.py
```

### 2.2 Update event

```bash
PYTHONPATH=src python3 scripts/operator_update.py
```

### 2.3 Cancel event

```bash
PYTHONPATH=src python3 scripts/operator_cancel.py
```

### 2.4 List events/reminders

Option A (today/upcoming summary):

```bash
PYTHONPATH=src python3 scripts/operator_smoke.py
```

Option B (direct engine seam):

```bash
PYTHONPATH=src python3 - <<'PY'
from ctx002_v0.engine import FamilySchedulerV0
s = FamilySchedulerV0()
print(s.active_events)
PY
```

Note: Option B shows engine seam behavior and may not reflect persisted shared runtime state across sessions.

---

## 3) What Success Looks Like

Illustrative shape only; field names and availability may vary by path.
Operational expectation: successful mutations include identity, action, and status signals.

```text
event_id: evt_9f3a2
action: create
status: committed
timestamp_utc: 2026-03-28T22:41:12Z
version: v0
```

---

## 4) Script Behavior Notes (Important)

- `operator_create.py` runs a direct create flow.
- `operator_update.py` currently demonstrates update behavior by creating a baseline event first, then updating it.
- `operator_cancel.py` currently demonstrates cancel behavior by creating a baseline event first, then cancelling it.
- `operator_smoke.py` is a smoke/list-proxy flow.

Update/cancel scripts currently include baseline-create scaffolding and are not exact mirrors of all production interaction paths.

---

## 5) Input Model (Operator Mental Model)

Illustrative model only; exact field names and required inputs may vary by callable path.

Create-like mental model:

```json
{
  "title": "Movie Night",
  "datetime": "2026-04-03T20:00:00",
  "timezone": "Europe/Paris"
}
```

For update/cancel flows, a stable event identifier (`event_id` or equivalent) is required.

---

## 6) Relative Scheduling Example (Concrete)

Illustrative expansion (example; actual runtime resolution may vary by path).

Input:

```text
every day at 9 AM for the 5 days before April 15
```

Example resolution:

- April 10 → 09:00
- April 11 → 09:00
- April 12 → 09:00
- April 13 → 09:00
- April 14 → 09:00

Timezone normalization is required before commit.

---

## 7) Failure Taxonomy (Operator)

Use deterministic failure class + raw error detail.

- `ENVIRONMENT_ERROR`: invalid path, missing dependency, wrong working directory
- `VALIDATION_ERROR`: missing or invalid required inputs
- `RUNTIME_ERROR`: exception/tool failure during execution
- `STATE_ERROR`: conflict with existing event/state transition constraints
- `PATH_UNAVAILABLE`: callable mutation path not available in current runtime context

---

## 8) Safety Rules (Practical)

- Clarify missing required fields before mutate.
- Normalize timezone before commit.
- Apply idempotency discipline:
  - reuse the same idempotency key for retries of the same intent
  - rotate to a new key for semantic changes
- Never claim success without actual execution result.

---

## 9) Golden Path Walkthrough (End-to-End)

1. Run preflight sanity checks (Section 1).
2. Create an event (`operator_create.py`) and capture event identity.
3. Verify via listing (`operator_smoke.py` and/or direct seam).
4. Run update flow (`operator_update.py`) and confirm updated status/output.
5. Run cancel flow (`operator_cancel.py`) and confirm cancellation outcome.
6. Re-list and verify expected final state.

---

## 10) Runtime Availability Behavior

If invocation path is unavailable, return deterministic failure classification with exact failing step/error text.

---

## 11) Practical Chat Examples

- “Schedule Movie Night on April 3 at 8 PM.”
- “Move Movie Night to 8:30 PM.”
- “Cancel Movie Night.”
- “Remind me every day at 9 AM for the 5 days before April 15.”
- “List upcoming reminders for next 7 days.”

---

## 12) Known Limits / Open Clarifications

- A single frozen canonical alias is not yet enforced beyond current script paths.
- Receipt field completeness may vary by callable path.
- Ambiguity-disambiguation reachability from all user paths should continue to be validated in UAT.

---

## 13) Ops Appendix (Non-Runtime Semantics)

- CI required checks
- branch protection
- merge policy

(Operational governance context; not user runtime behavior.)
