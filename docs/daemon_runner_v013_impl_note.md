# Daemon Runner v0.1.3 — Implementation Note

Canonical entrypoint:
- `scripts/daemon_run.py`

## Invocation

```bash
KINFLOW_DB_PATH=/var/lib/kinflow/kinflow.sqlite \
python3 scripts/daemon_run.py
```

Useful overrides:
- `KINFLOW_HEALTH_PATH` (default `/var/lib/kinflow/health.json`)
- `KINFLOW_STATE_STAMP_PATH` (default `/var/lib/kinflow/dispatch_mode.state`)
- `KINFLOW_LOCK_PATH` (default `/var/lib/kinflow/daemon.lock`)
- `KINFLOW_OWNER_META_PATH` (default `/var/lib/kinflow/daemon.owner.json`)
- `KINFLOW_EXPECT_RUNTIME_CONTRACT` (default `v0.1.4`)
- `KINFLOW_EXPECT_DEPLOYMENT_CONTRACT` (default `v0.1.4`)

## Test commands

```bash
python3 -m pytest -q tests/test_daemon_runner_v013.py
python3 -m pytest -q
```

## What this seam enforces

- Ordered startup gates (config -> validation -> version binding -> db path -> singleton -> runtime -> health -> state stamp -> loop)
- Closed fail-token behavior for runner-level exits
- Health file minimum wire shape and readiness semantics
- Cycle identity (`<trace_id>:<cycle_seq>`) and overrun no-burst policy
- Singleton takeover evidence JSONL artifact shape
- Structured single-line JSON logs including terminal JSON line
