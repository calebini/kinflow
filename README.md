# Kinflow

Kinflow is a deterministic, chat-first family scheduling coordinator: clear plans, calm reminders, and no mystery calendar magic.

It captures event intent from chat-shaped input, resolves create/update/cancel actions, requires explicit confirmation before persistence, and drives reminders with auditable state transitions.

## What It Does

- Maintains versioned scheduling records for family events.
- Resolves create, update, and cancel intent deterministically.
- Blocks ambiguous changes instead of guessing.
- Regenerates reminders when events change.
- Enforces recipient-aware delivery policy, including quiet-hours and missing-timezone blocks.
- Records lifecycle, delivery, retry, and policy decisions with canonical reason codes.

## Repository Layout

```text
src/kinflow/       Runtime package
tests/             Executable expectations
scripts/           Operator, daemon, probe, and verification entrypoints
migrations/        SQLite schema migrations
specs/             Normative specs, contracts, and freeze manifest
requirements/      Requirements baseline
architecture/      Architecture baseline
docs/              Current developer and operator docs
ops/               Operational scripts and playbooks
observability/     Alert, query, and canary policy assets
```

## Key Runtime Files

- `src/kinflow/engine.py` - deterministic lifecycle engine
- `src/kinflow/models.py` - event, reminder, delivery, and target models
- `src/kinflow/reason_codes.py` - canonical reason-code enum
- `src/kinflow/contract_versions.py` - implemented spec and contract declarations
- `src/kinflow/persistence/` - migration, reason binding, and state store primitives
- `src/kinflow/daemon.py` - daemon runtime primitives
- `src/kinflow/tickerd_runtime.py` - adapter layer for the external `tickerd` daemon component
- `src/kinflow/oc_adapter.py` - OpenClaw delivery adapter integration

## Verification

Run the required repository gates from the repo root:

```bash
python3 scripts/verify_contract_pins.py
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v
```

The pin verifier checks the freeze manifest against canonical artifacts and runtime version declarations.

## Operator Entrypoints

```bash
PYTHONPATH=src python3 scripts/operator_create.py
PYTHONPATH=src python3 scripts/operator_update.py
PYTHONPATH=src python3 scripts/operator_cancel.py
PYTHONPATH=src python3 scripts/operator_smoke.py
```

The current foreground daemon entrypoint is:

```bash
PYTHONPATH=src python3 scripts/tickerd_daemon_run.py
```

`scripts/daemon_run.py` remains as a compatibility/reference runner while the `tickerd` adapter path is exercised.

## Source Of Truth

Kinflow follows the Cortext1 one-way contract pinning model:

```text
Versions communicate compatibility.
Hashes prove exact reviewed artifacts.
Tests prove behavior.
The freeze manifest is one-way authoritative.
```

Canonical release-critical pins live in `specs/KINFLOW_CONTRACT_FREEZE_MANIFEST_PHASE0_5.md`.

Runtime code declares implemented versions in `src/kinflow/contract_versions.py`.

Public behavior changes require:

- updating the relevant spec or contract version;
- updating runtime implemented-version declarations;
- updating contract tests or golden fixtures;
- rebinding the freeze manifest if a pinned artifact changed.

## Docs

Current working docs are indexed in `docs/README.md`.
