# Kinflow Runner Test Stabilization v2 (run_code 4413)

## Failure Reference (from 4412)
- `AssertionError: python executable path is empty`

## Patch
- Updated only `tests/test_daemon_runner_v013.py`.
- In `_validated_runner_subprocess_context(...)`:
  - prefer `sys.executable` when present and valid
  - fallback to `python3` via `shutil.which("python3")` when `sys.executable` is empty/unset/invalid
  - keep deterministic subprocess launch path and existing cwd/script validations

## Scope
- Runtime behavior untouched (`scripts/daemon_run.py` unchanged).
- Test/doc-only stabilization patch.
