# Kinflow Operations

## Startup Checks

Run from the repository root:

```bash
python3 scripts/verify_contract_pins.py
python3 -m compileall -q src scripts tests
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Optional runtime probes:

```bash
PYTHONPATH=src python3 scripts/p2c_e2e_runtime_probe.py --output-dir tmp/p2c-probe
PYTHONPATH=src python3 scripts/phase4_hardening_drills.py --output-dir tmp/hardening-drills
```

## Daemon Entrypoint

```bash
PYTHONPATH=src python3 scripts/tickerd_daemon_run.py
```

`scripts/daemon_run.py` remains available as a compatibility/reference runner.

## Degraded Mode

When provider or adapter behavior degrades:

1. Capture the failing command and UTC timestamp.
2. Run the pin verifier.
3. Run the focused probe or drill for the affected path.
4. Classify the failure as deterministic mismatch, persistence violation, replay risk, duplicate-send risk, provider transient, or environment error.
5. Halt rollout or mutation work until the failure has a reproducible receipt.

## Incident Response

For every incident, capture:

- command and environment;
- current git status;
- verification command output;
- failing event, reminder, delivery attempt, or adapter receipt;
- final classification and next action.

Duplicate visible sends, replay divergence, invalid canonical reason codes, and pinned artifact drift are release blockers.
