KINFLOW_DISPATCHER_OC_ADAPTER_INTEGRATION_ADDENDUM_v0.1.7b (Master Cut)
0) Convergence Declaration
Review Phase: MASTER_CANDIDATE
Activation Posture: STRICT
Parent spec:
KINFLOW_DISPATCHER_OC_ADAPTER_INTEGRATION_ADDENDUM_v0.1.7
Scope:
PF04/PF05 closure criteria only
no expansion of delivery model scope
Parent artifact binding (explicit):
path: /home/agent/projects/apps/kinflow/specs/KINFLOW_DISPATCHER_OC_ADAPTER_INTEGRATION_ADDENDUM_v0.1.7.md
version: v0.1.7
sha256: fc3d8e70a2c9609a65b08582053b01576debb240e8912a76ee891c6b244faeae (must be recorded at install and used in proof runs)

1) Purpose
Eliminate PF04/PF05 interpretation drift by defining exact runtime behaviors and exact proof artifact schema required for gate pass.
2) PF05 — Startup Adapter Binding Gate (Normative)
For WhatsApp-routed dispatch path, startup MUST perform this gate before loop entry:

1) adapter object exists
2) hasattr(adapter, "send") == true
3) callable(getattr(adapter, "send")) == true
4) binding check result emitted in startup log record

If any check fails:
fail token: DISPATCH_ADAPTER_BINDING_INVALID
runner MUST:
emit fail-token audit/log record
return explicit failure result
not enter steady-state loop

3) PF04 — Deterministic Fail-Token Consequence Chain (Normative)
On any of:
DISPATCH_ADAPTER_BYPASS_DETECTED
DELIVERED_WITHOUT_ADAPTER_RESULT
FALLBACK_PATH_USED_WITHOUT_FLAG

dispatcher MUST execute all actions in order:

1) block terminal state transition (DELIVERED_SUCCESS forbidden)
2) append fail-token audit event with required fields:
attempt_id
reminder_id
path_id
fail_token
terminal_decision=BLOCK
3) persist delivery_attempt with explicit state:
status=failed
terminal=false (derived contract state; if not a physical column, derive from status/reason_code mapping)
reason_code=<fail_token>
4) return explicit failure result from dispatcher boundary

Missing any step => PF04 FAIL.

4) PF03 Non-Regression Guard (Normative)
Any PF04/PF05 patch MUST preserve:
terminal DELIVERED_SUCCESS allowed only when parent spec v0.1.7 §6 evidence criteria are satisfied.
proof run MUST cite parent spec path + version + pinned sha256 from §0.

5) Gate-Proof Artifact Schema (Required)
Evidence root MUST include machine-readable files:

pf03_gate_proof.json
pf04_gate_proof.json
pf05_gate_proof.json
pf_gate_summary.json
5.1 Required JSON fields (each pfXX file)
pf_id (PF03|PF04|PF05)
status (YES|NO)
checked_at_utc
source_paths (array)
assertions (array of {id, pass, note})
blockers (array)

5.2 Summary schema
pf_gate_summary.json MUST include:
PF03_STATUS
PF04_STATUS
PF05_STATUS
overall_status (GO|NO_GO)

5.3 Deterministic mapping rule
overall_status=GO iff all PF statuses are YES
otherwise overall_status=NO_GO

6) Scope-Check Normalization Rule
For proof-only/validation runs, scope check MUST ignore interpreter byproducts:
__pycache__/
*.pyc

If tooling cannot ignore automatically, cleanup is allowed only as repo-local non-destructive action.

Required cleanup commands (repo-local):
find <repo_root> -type d -name __pycache__ -prune -exec rm -rf {} +
find <repo_root> -name "*.pyc" -delete

Evidence MUST include:
asserted cwd
asserted repo_root
command transcript proving cleanup operated only under repo root
7) Acceptance Gates (This Addendum)
1) PF05 startup binding behavior proven with positive + negative path.
2) PF04 consequence chain proven end-to-end with deterministic ordering.
3) PF03 remains YES against bound parent artifact (§0).
4) Proof artifacts conform to §5 schema.
5) Scope-check handling conforms to §6.

8) Required Final Lines
PF03_STATUS: YES|NO
PF04_STATUS: YES|NO
PF05_STATUS: YES|NO
PF_CLOSURE_ADDENDUM_STATUS: GO|NO_GO
BLOCKERS: <count>