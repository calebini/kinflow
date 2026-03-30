# Daemon Runner Test Hardening (run_code 4408)

## Failure Class (from landing run 4407)

Observed test-only subprocess startup failure:
- `PermissionError: [Errno 13] Permission denied: ''`

This indicates a subprocess launch path resolved to an empty string in the test fixture context.

## Patch Rationale

Hardened `tests/test_daemon_runner_v013.py` only (no runtime changes):

- Added `_validated_runner_subprocess_context(...)` helper to enforce:
  - non-empty `sys.executable`
  - executable exists on disk
  - valid cwd directory
  - runner script exists
- Switched terminal/startup subprocess test to deterministic temp directory setup.
- Added explicit pre-launch assertions ensuring all required runner env path fields are non-empty.
- Set explicit `PYTHONPATH` in subprocess env for deterministic module resolution.

## Scope Guarantee

- Runtime file unchanged: `scripts/daemon_run.py`.
- Changes limited to test + this documentation note.
