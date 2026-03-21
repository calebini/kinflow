# Kinflow P1-A Verification Evidence

## Lint preflight

```bash
cd /home/agent/projects/apps/kinflow
python3 -m compileall -q src scripts tests && echo LINT_PASS_NORMALIZED
```

Observed output:
- `LINT_PASS_NORMALIZED`

## P1-A test suite output

```bash
cd /home/agent/projects/apps/kinflow
PYTHONPATH=src python3 -m unittest -v tests.test_p1a_schema_migrations
```

Observed summary:
- `Ran 5 tests ...`
- `OK`

## Enforced constraint evidence summary

- FK enforcement active: PASS
  - Verified by `test_fk_pragma_enforcement`.
- Enum validation active: PASS
  - Verified by `test_enum_fk_rejection_for_invalid_values`.
- Migration checksum guard active: PASS
  - Verified by `test_checksum_mismatch_fail_stop`.
- Dirty migration sentinel guard active: PASS
  - Verified by `test_dirty_sentinel_fail_stop`.
- Forward schema/migration application: PASS
  - Verified by `test_schema_create_and_forward_apply`.
