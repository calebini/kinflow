# Kinflow Rollback

## General Rule

Every rollback must leave a receipt with:

- commit or file range reverted;
- commands executed;
- pin verification result;
- test result;
- remaining known risk.

## Git Rollback

From the repository root:

```bash
git log --oneline -n 10
git revert <commit-hash>
git status --short
python3 scripts/verify_contract_pins.py
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v
```

## Simulated Runtime Rollback

Use the hardening drill runner when validating rollback behavior without touching a host service:

```bash
PYTHONPATH=src python3 scripts/phase4_hardening_drills.py --output-dir tmp/rollback-drill
```

The rollback proof should show that the backup artifact is created, mutation changes state, and restore returns state exactly to the original hash.

## Failure Handling

If rollback does not restore the expected hash or runtime state, stop progression and classify the issue before attempting further rollout.
