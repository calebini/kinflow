# Kinflow P1-B Verification Evidence

## Lint preflight

```bash
cd /home/agent/projects/apps/kinflow
python3 -m compileall -q src scripts tests && echo LINT_PASS_NORMALIZED
```

Observed output:
- `LINT_PASS_NORMALIZED`

## Acceptance suite (engine parity baseline)

```bash
cd /home/agent/projects/apps/kinflow
PYTHONPATH=src python3 -m unittest -v tests.test_acceptance_v0
```

Observed summary:
- `Ran 9 tests ...`
- `OK`

## P1-B targeted suite

```bash
cd /home/agent/projects/apps/kinflow
PYTHONPATH=src python3 -m unittest -v tests.test_p1b_repo_integration
```

Observed summary:
- `Ran 3 tests ...`
- `OK`

## Parity contracts preserved (proof refs)

- Resolver precedence: preserved
  - proof: `tests.test_acceptance_v0::test_resolver_precedence_explicit_beats_similarity`
- Confirmation gating: preserved
  - proof: `tests.test_acceptance_v0::test_confirmation_gate_blocks_persist_without_yes`
- Update/cancel invalidation semantics: preserved
  - proof: `tests.test_acceptance_v0::test_update_regenerates_and_invalidates_prior_version_reminders_without_drift`
  - proof: `tests.test_acceptance_v0::test_cancel_invalidates_all_future_pending_reminders`
- Timezone blocking semantics: preserved
  - proof: `tests.test_acceptance_v0::test_timezone_missing_blocks_delivery_scheduling`
- Dedupe behavior/replay safety: preserved
  - proof: `tests.test_acceptance_v0::test_retry_and_replay_no_duplicate_user_visible_delivery`
  - proof: `tests.test_p1b_repo_integration::test_receipt_replay_persists_across_engine_restart`

## Scope check evidence

- Comms adapter code added: **NO**
- Recovery/daemon loop features introduced: **NO**
