# KINFLOW OpenClaw Gateway Assumption Probe

- Instruction ID: `KINFLOW-OC-GATEWAY-PROBE-IMPLEMENT-20260323-001`
- Run Code: `4338`
- Timestamp (UTC): `2026-03-23T23:24:21Z`
- Probe Script: `/home/agent/projects/apps/kinflow/scripts/oc_gateway_probe.py`
- Raw Artifact: `/home/agent/projects/_backlog/output/kinflow_oc_gateway_probe_4338_20260323T232421Z/raw_results.json`

## Purpose

Deterministically validate OpenClaw Gateway assumptions for:
1. Discord delivery in the active CTX-002 thread
2. WhatsApp delivery input/error shape for `whatsapp:g-caleb-loop`
3. Deterministic invalid target error-shape capture

Also validate correlation marker propagation visibility for:
- `delivery_id`
- `attempt_id`
- `trace_id`
- `causation_id`

## Preflight Gate

Command:

```bash
python3 -m compileall -q src scripts tests
```

Result: `LINT_PASS_NORMALIZED` (proceed gate satisfied).

## Deterministic Case Order and Outcomes

### Case 1 — Discord send (current CTX-002 thread)
- Request channel/target: `discord` / `1470840649052983337`
- Outcome class: `SUCCESS`
- Receipt/ref observed: `messageId`, `channelId`
- Correlation marker echo in tool response payload: all `false`
- Notes: delivery accepted by plugin and returned receipt IDs.

### Case 2 — WhatsApp send (`whatsapp:g-caleb-loop`)
- Request channel/target: `whatsapp` / `whatsapp:g-caleb-loop`
- Outcome class: `FAIL_INVALID_TARGET_SHAPE`
- Deterministic error signature:
  - `Delivering to WhatsApp requires target <E.164|group JID> or channels.whatsapp.allowFrom[0]`
- Correlation marker echo in tool response payload: all `false`
- Notes: channel policy/input contract blocked send; block evidence captured without alternate target improvisation.

### Case 3 — Invalid target (deterministic error-shape capture)
- Request channel/target: `discord` / `__kinflow_invalid_target__`
- Outcome class: `FAIL_UNKNOWN_TARGET`
- Deterministic error signature:
  - `Unknown target "__kinflow_invalid_target__" for Discord. Hint: <channelId|user:ID|channel:ID>`
- Correlation marker echo in tool response payload: all `false`

## Findings Summary

### Assumptions Confirmed
- Discord send path accepts current thread ID and returns deterministic receipt references (`messageId`, `channelId`).
- Invalid Discord target produces stable parseable error shape with explicit hinting.

### Assumptions Failed / Unknown
- `whatsapp:g-caleb-loop` alias is **not** accepted by current CLI send path as a valid WhatsApp delivery target shape in this runtime context.
- Correlation markers embedded in body/fixture are not echoed back in gateway send response envelopes (preservation in response payload unknown/absent).

### Recommended Spec Adjustments
1. Clarify comms adapter target canonicalization for WhatsApp (alias vs JID/E.164 input contract).
2. If correlation propagation is a requirement, explicitly define where markers must appear (request-only, adapter logs, or response echo fields).
3. Add deterministic target normalization rule and error class mapping for alias-like targets (e.g., `ALIAS_UNRESOLVED` vs `TARGET_SHAPE_INVALID`).

## Run Command + Output Summary

Command:

```bash
python3 scripts/oc_gateway_probe.py --run-code 4338
```

Observed output:

```json
{
  "artifact_dir": "/home/agent/projects/_backlog/output/kinflow_oc_gateway_probe_4338_20260323T232421Z",
  "status": "OK"
}
```

## Knuth Handoff Block

- READY_FOR_LANDING: `YES`
- Re-run commands:
  1. `cd /home/agent/projects/apps/kinflow`
  2. `python3 scripts/oc_gateway_probe.py --run-code 4338`
- Expected outputs/artifact paths:
  - `/home/agent/projects/_backlog/output/kinflow_oc_gateway_probe_4338_<timestamp>/raw_results.json`
  - `/home/agent/projects/apps/kinflow/docs/KINFLOW_OC_GATEWAY_ASSUMPTION_PROBE.md`
- Rollback notes:
  - Revert additive files/edits in kinflow repo:
    - `git checkout -- README.md docs/KINFLOW_OC_GATEWAY_ASSUMPTION_PROBE.md scripts/oc_gateway_probe.py`
  - Remove generated probe artifacts if needed:
    - `rm -rf /home/agent/projects/_backlog/output/kinflow_oc_gateway_probe_4338_*`

---

ChangeLog Entry ID: `CL-20260323-232421Z-4338-KINFLOW-OC-PROBE`
ChangeLog Path: `/home/agent/.openclaw/workspace-knuth/ops/CHANGELOG.md`
Tier: `L1`
Final Status: `OK`
