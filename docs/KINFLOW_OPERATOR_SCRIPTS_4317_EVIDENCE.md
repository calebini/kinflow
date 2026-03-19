# KINFLOW operator scripts evidence (run_code 4317)

## Lint preflight

```bash
python3 -m compileall -q src scripts tests && echo LINT_PASS_NORMALIZED
```

Output:
- `LINT_PASS_NORMALIZED`

## Runnable evidence

### 1) operator_smoke.py
```bash
PYTHONPATH=src python3 scripts/operator_smoke.py
```
Output blocks present:
- `PROCESS`
- `DELIVERY_OUTCOMES`
- `BRIEF`
- `HASH`

### 2) operator_create.py
```bash
PYTHONPATH=src python3 scripts/operator_create.py
```
Output blocks present:
- `PROCESS`
- `DELIVERY_OUTCOMES`
- `HASH`

### 3) operator_update.py
```bash
PYTHONPATH=src python3 scripts/operator_update.py
```
Output blocks present:
- `PROCESS`
- `DELIVERY_OUTCOMES`
- `HASH`

### 4) operator_cancel.py
```bash
PYTHONPATH=src python3 scripts/operator_cancel.py
```
Output blocks present:
- `PROCESS`
- `DELIVERY_OUTCOMES`
- `HASH`

## Script purposes

- `scripts/operator_smoke.py` — bootstrap + create + due delivery + daily brief + deterministic hash.
- `scripts/operator_create.py` — deterministic create flow with due reminder delivery and final hash.
- `scripts/operator_update.py` — create then explicit update flow; regeneration-aware due delivery and final hash.
- `scripts/operator_cancel.py` — create then explicit cancel flow; post-cancel due delivery check and final hash.
