# Kinflow v0 — Knuth landing handoff

READY_FOR_LANDING: YES

## Scope
Canonical scope executed:
`/home/agent/projects/apps/kinflow/**`

## Change summary
- Added deterministic v0 core engine implementing intake -> resolver -> confirmation -> persistence -> scheduling -> delivery -> audit.
- Enforced canonical resolver precedence and canonical reason-code enum IDs.
- Implemented lifecycle mutation behavior:
  - update => invalidate future prior-version reminders + deterministic regeneration
  - cancel => invalidate all future pending reminders
- Enforced timezone contract:
  - event timezone drives event semantics
  - recipient timezone drives quiet-hours and delivery timing
  - missing recipient timezone blocks scheduling (`TZ_MISSING`)
- Added bounded retry + dedupe to guarantee no duplicate user-visible sends in replay/retry flow.
- Added acceptance harness with deterministic replay, DST/cross-timezone fixture coverage, ambiguity blocking, and regeneration drift checks.

## Files changed
- `src/ctx002_v0/__init__.py`
- `src/ctx002_v0/reason_codes.py`
- `src/ctx002_v0/models.py`
- `src/ctx002_v0/engine.py`
- `tests/test_acceptance_v0.py`
- `pyproject.toml`
- `docs/KINFLOW_V0_IMPLEMENTATION_NOTES.md`
- `docs/KINFLOW_V0_VERIFICATION_EVIDENCE.md`
- `docs/KINFLOW_V0_KNUTH_LANDING_HANDOFF.md`

## Commands Knuth should run

```bash
cd /home/agent/projects/apps/kinflow
python3 -m compileall -q src tests && echo LINT_PASS_NORMALIZED
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v
```

## Expected outputs
- Lint preflight must print exactly:
  - `LINT_PASS_NORMALIZED`
- Test harness must end with:
  - `Ran 9 tests ...`
  - `OK`

## Known risks
- Current implementation is in-memory only (no durable persistence backend).
- Capture-only degradation mode is not yet wired as a separate runtime mode flag.
- Similarity scoring is deterministic but intentionally simple (title/time/participants exact tuple strategy).

## Rollback notes
- Revert by removing `src/ctx002_v0`, `tests/test_acceptance_v0.py`, and new docs files.
- No runtime/system mutations were performed.
