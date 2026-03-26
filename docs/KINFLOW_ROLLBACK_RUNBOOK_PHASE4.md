# KINFLOW Rollback Runbook (Phase 4 Hardening)

status: canonical
last_updated_utc: 2026-03-26T11:37:00Z

## Purpose

Define reversible rollback procedures for high-risk lanes touched in Phase 4 hardening kickoff (docs/runbooks/scripts/evidence plumbing).

## Rollback scope covered

- Hardening drill harness scripts
- Phase 4 hardening kickoff report and runbooks
- Checklist/readme pointer additions

## General rollback rule

Every rollback must produce a deterministic receipt containing:
- commit(s) reverted
- commands executed
- post-rollback lint status
- post-rollback integrity checks

## Git rollback procedure

From repo root:

1. Inspect latest hardening commits:
   - `git log --oneline -n 10`
2. Revert target commit(s):
   - `git revert <commit-hash>`
3. Verify working tree clean:
   - `git status --short`
4. Re-run lint preflight:
   - `python3 -m compileall -q src scripts tests`
   - `ruff check .`

## Simulated rollback proof (non-prod)

Use drill ID `D3_ROLLBACK_DRILL` in:
- `PYTHONPATH=src python3 scripts/phase4_hardening_drills.py --output-dir <evidence-root>`

Success criteria:
- backup artifact created
- mutation changes hash
- restore returns hash exactly to original

## Failure handling

If rollback does not restore expected hash/state:
- classify `PHASE4_HARDENING_INCOMPLETE`
- stop progression to Phase 5
- attach mismatch evidence in incident packet

## Known rollback references from prior phase packets

- P2-B rollback:
  - `git -C /home/agent/projects/apps/kinflow revert 90474f6`
- P2-C rollback:
  - `git -C /home/agent/projects/apps/kinflow revert d4c079c`
- Phase 2 consolidation rollback:
  - `git -C /home/agent/projects/apps/kinflow revert d5abf38`
