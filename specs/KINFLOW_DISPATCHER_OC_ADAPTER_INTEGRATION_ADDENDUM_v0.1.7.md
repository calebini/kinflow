KINFLOW_DISPATCHER_OC_ADAPTER_INTEGRATION_ADDENDUM_v0.1.7 (Master Cut)
0) Convergence Declaration
Review Phase: MASTER_CANDIDATE
Activation Posture: STRICT
Scope: Dispatcher↔OC adapter integration for WhatsApp-routed notification path (daemon path)
Canonical companion artifacts (explicit):
Dispatcher runtime contract:
/home/agent/projects/apps/kinflow/specs/KINFLOW_DAEMON_RUNTIME_CONTRACT_MASTER_v0.1.4.md
Dispatcher deployment contract:
/home/agent/projects/apps/kinflow/specs/KINFLOW_DAEMON_DEPLOYMENT_CONTRACT_MASTER_v0.1.4.md
OC comms adapter contract (authoritative):
/home/agent/projects/apps/kinflow/specs/KINFLOW_COMMS_ADAPTER_CONTRACT_MASTER_v0.1.8.md

1) Purpose
Define the required bridge for WhatsApp-routed dispatcher notifications and prevent false-terminal delivery states caused by adapter bypass behavior.
2) Channel-Scoped Bridge Rule
When notification_route.channel == whatsapp, dispatcher delivery MUST route through the OC adapter seam defined by:
/home/agent/projects/apps/kinflow/specs/KINFLOW_COMMS_ADAPTER_CONTRACT_MASTER_v0.1.8.md

3) Normative Terminal Guard (Single Source Rule)
DELIVERED_SUCCESS terminal state transition is allowed only when required evidence criteria in §6 are present and valid.

4) Allowed / Forbidden Paths (WhatsApp lane)
4.1 Allowed
dispatcher -> OC adapter send -> adapter result mapping -> delivery_attempt persistence + audit

4.2 Forbidden
direct WhatsApp transport send from dispatcher path bypassing OC adapter seam
direct terminal state transition mutation without OC adapter result
any DELIVERED_SUCCESS transition that violates §3
Fail tokens:
DISPATCH_ADAPTER_BYPASS_DETECTED
DELIVERED_WITHOUT_ADAPTER_RESULT

5) Dispatcher Startup Binding Gate
At startup, dispatcher MUST verify:
1) OC adapter binding exists
2) OC adapter binding is callable

Binding failure:
fail-stop with DISPATCH_ADAPTER_BINDING_INVALID

6) Required Evidence Criteria for DELIVERED_SUCCESS
Terminal DELIVERED_SUCCESS requires all fields present and valid in persisted delivery_attempt:

1) reason_code = DELIVERED_SUCCESS
2) delivery_confidence present (opaque non-empty string; taxonomy governed by OC adapter contract)
3) provider_status_code present (opaque non-empty string; taxonomy governed by OC adapter contract)
4) provider_ref present, unless nullability is explicitly allowed by authoritative OC adapter contract
5) result_at_utc present and valid UTC timestamp

If criteria are incomplete/invalid:
terminal state transition is forbidden,
dispatcher persists failed non-terminal outcome.

7) Deterministic Fail-Token Consequences
On DISPATCH_ADAPTER_BYPASS_DETECTED or DELIVERED_WITHOUT_ADAPTER_RESULT, dispatcher MUST:
1) block terminal state transition,
2) append audit event with fail token + reminder id + path id,
3) persist delivery_attempt as failed non-terminal,
4) return explicit failure result from dispatcher operation boundary.

8) Temporary Fallback Path (Break-Glass Only)
Invariant:
fallback path use requires explicit config flag.

If fallback is used without explicit flag:
fail token: FALLBACK_PATH_USED_WITHOUT_FLAG
block terminal state transition
return explicit failure result

Fallback path MUST NOT emit DELIVERED_SUCCESS unless §6 criteria are satisfied.
Production default is disabled.

9) Minimal Audit Schema (Fixed)
Each WhatsApp-routed delivery_attempt MUST append audit including:
attempt_id
adapter_result (string)
terminal_decision (ALLOW|BLOCK)
reason_code
10) Acceptance Gates
1) Daemon WhatsApp path proves OC adapter binding.
2) No WhatsApp path emits DELIVERED_SUCCESS without §6 evidence criteria.
3) Persisted delivery_attempt rows include required §6 fields.
4) Bypass-negative proof: bypass attempt triggers fail token + deterministic consequences (§7).
5) Fallback-negative proof: fallback use without flag triggers FALLBACK_PATH_USED_WITHOUT_FLAG.

11) Evidence Required
daemon WhatsApp adapter binding proof
persisted delivery_attempt evidence rows
bypass-negative proof (fail token + consequence chain)
fallback-negative proof (fail token + consequence chain)
finalization block with RUN_FINALIZED: YES

12) Required Final Lines
ADAPTER_INTEGRATION_STATUS: GO|NO_GO
WHATSAPP_ADAPTER_BOUND: YES|NO
TERMINAL_EVIDENCE_GUARD: PASS|FAIL
FAIL_TOKEN_ENFORCEMENT: PASS|FAIL
BLOCKERS: <count>
