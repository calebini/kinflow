# KINFLOW Dispatcher↔OC Alignment Patch Note (run_code 4411)

## Scope
Close PF-03 / PF-04 / PF-05 gaps from spec install preflight (4410) against:
- `specs/KINFLOW_DISPATCHER_OC_ADAPTER_INTEGRATION_ADDENDUM_v0.1.7.md`
- `specs/KINFLOW_COMMS_ADAPTER_CONTRACT_MASTER_v0.1.8.md`

## Before / After seam

Before:
`daemon dispatch -> direct reminder status mutation -> delivered`

After:
`daemon dispatch (whatsapp) -> OC adapter send -> adapter result -> terminal evidence guard -> persistence + audit`

## What changed

1. Startup binding gate (PF-05)
- Runner now constructs OC adapter binding at startup and verifies binding exists + callable.
- On failure: `DISPATCH_ADAPTER_BINDING_INVALID` fail-stop.

2. WhatsApp route through OC adapter seam
- WhatsApp delivery path in `DispatchCallbacks.process_candidate` now routes through `OpenClawGatewayAdapter.send(...)`.
- Direct bypass path blocked with deterministic fail-token consequences.

3. Terminal evidence guard (PF-03)
- `DELIVERED_SUCCESS` transition requires adapter result evidence:
  - `reason_code=DELIVERED_SUCCESS`
  - non-empty `delivery_confidence`
  - non-empty `provider_status_code`
  - `result_at_utc` present
  - `provider_ref` nullability accepted per OC contract v0.1.8 (`string|null`)
- Evidence failure triggers `DELIVERED_WITHOUT_ADAPTER_RESULT` consequence flow.

4. Deterministic fail-token consequences (PF-04)
Implemented:
- `DISPATCH_ADAPTER_BYPASS_DETECTED`
- `DELIVERED_WITHOUT_ADAPTER_RESULT`
- `FALLBACK_PATH_USED_WITHOUT_FLAG`

Each consequence enforces:
- terminal transition blocked
- audit append with fail token + reminder id + path id
- failed non-terminal delivery_attempt persisted
- explicit failure result returned (`False` boundary result)

## Checklist closure mapping
- PF-03: CLOSED (YES)
- PF-04: CLOSED (YES)
- PF-05: CLOSED (YES)
