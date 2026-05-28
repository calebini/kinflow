# Kinflow Usage

This is a practical operator guide, not a normative API spec.

## Preflight

Run from the repository root:

```bash
python3 --version
git status --short
python3 scripts/verify_contract_pins.py
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v
```

## Operator Scripts

```bash
PYTHONPATH=src python3 scripts/operator_create.py
PYTHONPATH=src python3 scripts/operator_update.py
PYTHONPATH=src python3 scripts/operator_cancel.py
PYTHONPATH=src python3 scripts/operator_smoke.py
```

`operator_update.py` and `operator_cancel.py` create demonstration baseline events before applying their mutation path.

## Direct Engine Check

```bash
PYTHONPATH=src python3 - <<'PY'
from kinflow.engine import FamilySchedulerV0

scheduler = FamilySchedulerV0()
print(scheduler.active_events)
PY
```

This shows engine behavior and may not reflect persisted shared runtime state across sessions.

## Operator Rules

- Clarify missing required fields before mutation.
- Normalize timezone before commit.
- Use explicit reminder offsets in minutes.
- Reuse the same idempotency key for retries of the same intent.
- Rotate to a new idempotency key for semantic changes.
- Never claim success without an actual execution result.

## Destination Routing

Destination source precedence is fixed:

```text
event_override
request_context_default
recipient_default
```

Accepted ingress shapes:

```json
{
  "event_override_channel": "whatsapp",
  "event_override_target_ref": "family-chat"
}
```

```json
{
  "event_override": {
    "channel": "whatsapp",
    "target_ref": "family-chat"
  }
}
```

When flattened and nested fields both exist, flattened fields win.

If a destination cannot be resolved, dispatch fails closed with `FAILED_CONFIG_INVALID_TARGET` and no delivered-success emission.
