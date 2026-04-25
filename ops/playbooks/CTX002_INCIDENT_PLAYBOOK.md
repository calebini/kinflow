CTX-002 Incident Playbook 
0) Scope
Applies to Kinflow WhatsApp daemon delivery path (whatsapp-daemon) after CTX-002 soak baseline.

1) Known-Good Baseline
Stable tag: ctx002-soak-stable-2026-04-18
Canonical verifier:
/home/agent/projects/apps/kinflow/ops/verify_ctx002_golden.sh
Stable expectation:
outbound body format: Reminder: {title} at {YYYY-MM-DD HH:MM} {TZ}
delivery row success:
status=delivered
reason_code=DELIVERED_SUCCESS
provider_status_code=ok
provider ref present

2) First 3 Commands (always)
cd /home/agent/projects/apps/kinflow
bash /home/agent/projects/apps/kinflow/ops/verify_ctx002_golden.sh
sudo journalctl -u kinflow-daemon.service -n 400 -o cat | rg -i 'error|exception|traceback|boundary_|seam|failed'
python3 - <<'PY'
import sqlite3
con=sqlite3.connect('/home/agent/projects/apps/kinflow/.anchor_runtime.sqlite'); con.row_factory=sqlite3.Row
row=con.execute("SELECT attempt_id,reminder_id,status,reason_code,provider_ref,provider_status_code,delivery_confidence,attempted_at_utc FROM delivery_attempts ORDER BY attempted_at_utc DESC LIMIT 1").fetchone()
print(dict(row) if row else None); con.close()
PY
3) Failure-Class Map
BOUNDARY_GATEWAY_CALL_FAILED / auth-unresolved:
classify as gateway credential/override lane issue first.
Seam invalid signatures (FAILED_ADAPTER_RESULT_INVALID, seam branch A/B/C):
classify as adapter result schema/evidence handling issue.
Content wrong but delivered:
classify as renderer/body composition regression.
Healthy cycles, no sends:
classify as scheduling/no-due/candidate selection.

Destination provenance mismatch signature (operator-critical):
- event_versions has all destination fields NULL (`event_override_*`, `request_context_default_*`)
- delivery_attempts succeeds with `destination_source=recipient_default`
- audience is normal identity (example: `["caleb"]`)

Classify this as ingress mutation payload normalization loss (not dispatch resolver failure).
Likely seam: `FamilySchedulerV0.process_intent(...)` boundary receiving payload without flattened destination keys.

4) Destination-Provenance Seam Triage (quick path)
1. Confirm signature in DB:
   - `event_versions.event_override_*` + `request_context_default_*` are NULL
   - matching `delivery_attempts.destination_source=recipient_default`
2. Confirm this is not dispatch-only:
   - if destination fields are NULL in event_versions/reminders, dispatch fallback is expected behavior.
3. Inspect ingress payload shape at mutation boundary:
   - accepted shapes: nested (`event_override`, `request_context_default`) or flattened (`*_channel`, `*_target_ref`).
   - mixed shape rule: flattened wins when both present.
4. Remediate at narrow seam:
   - normalize nested shape to flattened keys at `process_intent` boundary.
5. Validate with one canary event:
   - `event_versions` non-null destination fields
   - `reminders` non-null destination fields
   - `delivery_attempts.destination_source` reflects precedence (`event_override` or `request_context_default`)

5) Incident Rules
One defect class at a time.
No opportunistic refactors during incident.
Rollback minimal first if blast radius unclear.
TEMP diagnostics allowed only if:
env-gated,
once-per-attempt,
removed immediately after capture.

6) Minimal Rollback Path
Prefer reverting the smallest recent commit(s) touching failing lane.
If ambiguity remains high, anchor to known-good tag behavior and re-apply forward surgically.

7) Recovery Exit Criteria (must all pass)
Golden verifier PASS (or justified stage skips with explicit reason).
Canary message delivers with correct body format.
Latest DB row confirms expected success semantics.
For destination incidents: canary DB must show
- non-null destination fields in `event_versions` and `reminders`
- `delivery_attempts.destination_source` equals expected precedence source (`event_override` or `request_context_default`), not unintended `recipient_default`
No repeating boundary/seam fatal signatures in recent logs.

8) Post-Incident Closeout
Record:
root cause
exact fix commit(s)
verification evidence path
guardrail update to prevent repeat.
Last Installed (UTC): 2026-04-18T23:29:30Z
