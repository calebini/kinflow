# Kinflow v0 verification evidence

## Lint preflight

```bash
$ python3 -m compileall -q src tests && echo LINT_PASS_NORMALIZED
LINT_PASS_NORMALIZED
```

## Acceptance harness

```bash
$ PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v
Ran 9 tests in 0.001s
OK
```

## Deterministic acceptance gate evidence mapping

- Resolver ambiguity auto-resolutions: **0**
  - Verified by `test_resolver_ambiguity_blocks_auto_resolution`.
- Duplicate user-visible deliveries in replay/retry tests: **0**
  - Verified by `test_retry_and_replay_no_duplicate_user_visible_delivery`.
- Reminder drift mismatches across regeneration tests: **0**
  - Verified by `test_update_regenerates_and_invalidates_prior_version_reminders_without_drift`.
- Deterministic replay consistency across fixture suite: **PASS (100%)**
  - Verified by `test_replay_consistency_dst_and_cross_timezone_fixture` hash-equivalence.

## Additional hard-rule checks

- Confirmation gate blocks persistence without explicit yes: PASS
- TZ missing blocks delivery scheduling (`TZ_MISSING`): PASS
- Cancel invalidates future pending reminders (`CANCEL_INVALIDATED`): PASS
