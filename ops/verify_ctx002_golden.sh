#!/usr/bin/env bash
set -euo pipefail

KINFLOW_ROOT="/home/agent/projects/apps/kinflow"
DAEMON_PY="${KINFLOW_ROOT}/scripts/daemon_run.py"
OUTPUT_ROOT="${OUTPUT_ROOT:-/home/agent/projects/_backlog/output}"
SERVICE_NAME="${SERVICE_NAME:-kinflow-daemon.service}"
KINFLOW_DB_PATH="${KINFLOW_DB_PATH:-${KINFLOW_ROOT}/.anchor_runtime.sqlite}"
VERIFY_CTX002_GOLDEN_DRY_RUN="${VERIFY_CTX002_GOLDEN_DRY_RUN:-0}"
CANARY_COMMAND="${CANARY_COMMAND:-}"

JOURNAL_LINES="${JOURNAL_LINES:-500}"
HEALTH_WAIT_TIMEOUT_SEC="${HEALTH_WAIT_TIMEOUT_SEC:-90}"
HEALTH_POLL_INTERVAL_SEC="${HEALTH_POLL_INTERVAL_SEC:-5}"

if [[ ! -f "${DAEMON_PY}" ]]; then
  echo "fatal: missing daemon file: ${DAEMON_PY}" >&2
  exit 2
fi

mkdir -p "${OUTPUT_ROOT}"
UTCSTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_DIR="${OUTPUT_ROOT}/kinflow_verify_ctx002golden${UTCSTAMP}"
mkdir -p "${RUN_DIR}"

COMPILE_LOG="${RUN_DIR}/compile_check.log"
TARGETED_TESTS_LOG="${RUN_DIR}/targeted_tests.log"
DAEMON_RESTART_LOG="${RUN_DIR}/daemon_restart.log"
JOURNAL_HEALTH_LOG="${RUN_DIR}/journal_health.log"
CANARY_STAGE_LOG="${RUN_DIR}/canary_stage.log"
DB_ASSERTION_JSON="${RUN_DIR}/db_assertion.json"
SUMMARY_JSON="${RUN_DIR}/summary.json"
FINAL_VERDICT_TXT="${RUN_DIR}/final_verdict.txt"
STAGE_TSV="${RUN_DIR}/.stage_summary.tsv"

STAGE_ORDER=(
  "compile_check"
  "targeted_tests"
  "daemon_restart"
  "journal_health"
  "canary_stage"
  "db_assertion"
)
MANDATORY_STAGES=(
  "compile_check"
  "targeted_tests"
  "daemon_restart"
  "journal_health"
  "db_assertion"
)

declare -A STAGE_STATUS
declare -A STAGE_REASON
for stage in "${STAGE_ORDER[@]}"; do
  STAGE_STATUS["${stage}"]="NOT_RUN"
  STAGE_REASON["${stage}"]=""
done

RESTART_SINCE_UTC=""

is_mandatory_stage() {
  local candidate="$1"
  local item
  for item in "${MANDATORY_STAGES[@]}"; do
    if [[ "${item}" == "${candidate}" ]]; then
      return 0
    fi
  done
  return 1
}

mark_stage() {
  local stage="$1"
  local status="$2"
  local reason="${3:-}"
  STAGE_STATUS["${stage}"]="${status}"
  STAGE_REASON["${stage}"]="${reason}"
}

run_compile_check() {
  : >"${COMPILE_LOG}"
  {
    echo "stage=compile_check"
    echo "command=python3 -m py_compile ${DAEMON_PY}"
    python3 -m py_compile "${DAEMON_PY}"
    echo "result=PASS"
  } >>"${COMPILE_LOG}" 2>&1 || {
    mark_stage "compile_check" "FAIL" "py_compile_failed"
    return 1
  }
  mark_stage "compile_check" "PASS"
}

run_targeted_tests() {
  : >"${TARGETED_TESTS_LOG}"

  if [[ "${STAGE_STATUS[compile_check]}" != "PASS" ]]; then
    {
      echo "stage=targeted_tests"
      echo "result=SKIPPED_PRECONDITION"
      echo "reason=compile_check_not_pass"
    } >>"${TARGETED_TESTS_LOG}"
    mark_stage "targeted_tests" "SKIPPED_PRECONDITION" "compile_check_not_pass"
    return 0
  fi

  local -a tests=(
    "tests.test_daemon_runner_v013.DaemonRunnerV013Tests.test_whatsapp_body_uses_event_context_and_preserves_delivery_semantics"
    "tests.test_daemon_runner_v013.DaemonRunnerV013Tests.test_whatsapp_body_fallback_when_event_lookup_missing"
    "tests.test_daemon_runner_v013.DaemonRunnerV013Tests.test_pf03_terminal_evidence_guard_blocks_invalid_adapter_result"
    "tests.test_daemon_runner_v013.DaemonRunnerV013Tests.test_pf04_fail_token_consequence_on_bypass"
  )

  {
    echo "stage=targeted_tests"
    echo -n "command=PYTHONPATH=${KINFLOW_ROOT}:${KINFLOW_ROOT}/src python3 -m unittest"
    local t
    for t in "${tests[@]}"; do
      echo -n " ${t}"
    done
    echo
    PYTHONPATH="${KINFLOW_ROOT}:${KINFLOW_ROOT}/src" python3 -m unittest "${tests[@]}"
    echo "result=PASS"
  } >>"${TARGETED_TESTS_LOG}" 2>&1 || {
    mark_stage "targeted_tests" "FAIL" "targeted_tests_failed"
    return 1
  }

  mark_stage "targeted_tests" "PASS"
}

run_daemon_restart() {
  : >"${DAEMON_RESTART_LOG}"

  if [[ "${STAGE_STATUS[targeted_tests]}" != "PASS" ]]; then
    {
      echo "stage=daemon_restart"
      echo "result=SKIPPED_PRECONDITION"
      echo "reason=targeted_tests_not_pass"
    } >>"${DAEMON_RESTART_LOG}"
    mark_stage "daemon_restart" "SKIPPED_PRECONDITION" "targeted_tests_not_pass"
    return 0
  fi

  if [[ "${VERIFY_CTX002_GOLDEN_DRY_RUN}" == "1" ]]; then
    {
      echo "stage=daemon_restart"
      echo "result=SKIPPED_DRY_RUN"
      echo "reason=dry_run_requested"
      echo "command=sudo -n systemctl restart ${SERVICE_NAME}"
    } >>"${DAEMON_RESTART_LOG}"
    mark_stage "daemon_restart" "SKIPPED_DRY_RUN" "dry_run_requested"
    return 0
  fi

  if ! command -v sudo >/dev/null 2>&1; then
    {
      echo "stage=daemon_restart"
      echo "result=FAIL"
      echo "reason=sudo_unavailable"
    } >>"${DAEMON_RESTART_LOG}"
    mark_stage "daemon_restart" "FAIL" "sudo_unavailable"
    return 1
  fi

  if ! command -v systemctl >/dev/null 2>&1; then
    {
      echo "stage=daemon_restart"
      echo "result=FAIL"
      echo "reason=systemctl_unavailable"
    } >>"${DAEMON_RESTART_LOG}"
    mark_stage "daemon_restart" "FAIL" "systemctl_unavailable"
    return 1
  fi

  if ! sudo -n true >/dev/null 2>&1; then
    {
      echo "stage=daemon_restart"
      echo "result=FAIL"
      echo "reason=sudo_non_interactive_unavailable"
    } >>"${DAEMON_RESTART_LOG}"
    mark_stage "daemon_restart" "FAIL" "sudo_non_interactive_unavailable"
    return 1
  fi

  RESTART_SINCE_UTC="$(date -u '+%Y-%m-%d %H:%M:%S UTC')"

  {
    echo "stage=daemon_restart"
    echo "command=sudo -n systemctl restart ${SERVICE_NAME}"
    sudo -n systemctl restart "${SERVICE_NAME}"
    echo "command=sudo -n systemctl is-active ${SERVICE_NAME}"
    sudo -n systemctl is-active "${SERVICE_NAME}"
    echo "result=PASS"
  } >>"${DAEMON_RESTART_LOG}" 2>&1 || {
    mark_stage "daemon_restart" "FAIL" "daemon_restart_failed"
    return 1
  }

  mark_stage "daemon_restart" "PASS"
}

run_journal_health() {
  : >"${JOURNAL_HEALTH_LOG}"

  if [[ "${STAGE_STATUS[daemon_restart]}" != "PASS" ]]; then
    {
      echo "stage=journal_health"
      echo "result=SKIPPED_PRECONDITION"
      echo "reason=daemon_restart_not_pass"
    } >>"${JOURNAL_HEALTH_LOG}"
    mark_stage "journal_health" "SKIPPED_PRECONDITION" "daemon_restart_not_pass"
    return 0
  fi

  local since_value
  since_value="${JOURNAL_SINCE:-${RESTART_SINCE_UTC}}"
  local fatal_regex='Traceback|uncaught exception|Unhandled exception|\bfatal\b|fail_token[^[:alnum:]_]*"?BOUNDARY_[A-Z0-9_]+'
  local success_regex='cycle_success[^[:alnum:]]*true'
  local tmp_log="${JOURNAL_HEALTH_LOG}.tmp"
  local start_epoch
  start_epoch="$(date +%s)"

  {
    echo "stage=journal_health"
    echo "service=${SERVICE_NAME}"
    echo "since=${since_value}"
    echo "journal_lines=${JOURNAL_LINES}"
    echo "health_wait_timeout_sec=${HEALTH_WAIT_TIMEOUT_SEC}"
    echo "health_poll_interval_sec=${HEALTH_POLL_INTERVAL_SEC}"
  } >>"${JOURNAL_HEALTH_LOG}"

  while true; do
    if ! sudo -n journalctl -u "${SERVICE_NAME}" --since "${since_value}" --no-pager -n "${JOURNAL_LINES}" >"${tmp_log}" 2>&1; then
      cat "${tmp_log}" >>"${JOURNAL_HEALTH_LOG}" 2>/dev/null || true
      echo "result=FAIL" >>"${JOURNAL_HEALTH_LOG}"
      echo "reason=journalctl_failed" >>"${JOURNAL_HEALTH_LOG}"
      mark_stage "journal_health" "FAIL" "journalctl_failed"
      rm -f "${tmp_log}" || true
      return 1
    fi

    cat "${tmp_log}" >>"${JOURNAL_HEALTH_LOG}"
    printf '\n' >>"${JOURNAL_HEALTH_LOG}"

    if grep -Eiq "${fatal_regex}" "${tmp_log}"; then
      echo "result=FAIL" >>"${JOURNAL_HEALTH_LOG}"
      echo "reason=fatal_signal_detected" >>"${JOURNAL_HEALTH_LOG}"
      mark_stage "journal_health" "FAIL" "fatal_signal_detected"
      rm -f "${tmp_log}" || true
      return 1
    fi

    if grep -Eiq 'cycle_summary' "${tmp_log}" && grep -Eiq "${success_regex}" "${tmp_log}"; then
      echo "result=PASS" >>"${JOURNAL_HEALTH_LOG}"
      mark_stage "journal_health" "PASS"
      rm -f "${tmp_log}" || true
      return 0
    fi

    if (( $(date +%s) - start_epoch >= HEALTH_WAIT_TIMEOUT_SEC )); then
      echo "result=FAIL" >>"${JOURNAL_HEALTH_LOG}"
      echo "reason=missing_cycle_summary_success_true" >>"${JOURNAL_HEALTH_LOG}"
      mark_stage "journal_health" "FAIL" "missing_cycle_summary_success_true"
      rm -f "${tmp_log}" || true
      return 1
    fi

    sleep "${HEALTH_POLL_INTERVAL_SEC}"
  done
}

run_canary_stage() {
  : >"${CANARY_STAGE_LOG}"

  if [[ "${STAGE_STATUS[journal_health]}" != "PASS" ]]; then
    {
      echo "stage=canary_stage"
      echo "result=SKIPPED_PRECONDITION"
      echo "reason=journal_health_not_pass"
    } >>"${CANARY_STAGE_LOG}"
    mark_stage "canary_stage" "SKIPPED_PRECONDITION" "journal_health_not_pass"
    return 0
  fi

  if [[ -z "${CANARY_COMMAND}" ]]; then
    {
      echo "stage=canary_stage"
      echo "result=SKIPPED"
      echo "reason=canary_command_unset"
    } >>"${CANARY_STAGE_LOG}"
    mark_stage "canary_stage" "SKIPPED" "canary_command_unset"
    return 0
  fi

  if [[ "${VERIFY_CTX002_GOLDEN_DRY_RUN}" == "1" ]]; then
    {
      echo "stage=canary_stage"
      echo "result=SKIPPED_DRY_RUN"
      echo "reason=dry_run_requested"
      echo "command=${CANARY_COMMAND}"
    } >>"${CANARY_STAGE_LOG}"
    mark_stage "canary_stage" "SKIPPED_DRY_RUN" "dry_run_requested"
    return 0
  fi

  {
    echo "stage=canary_stage"
    echo "command=${CANARY_COMMAND}"
    bash -lc "${CANARY_COMMAND}"
    echo "result=PASS"
  } >>"${CANARY_STAGE_LOG}" 2>&1 || {
    mark_stage "canary_stage" "FAIL" "canary_command_failed"
    return 1
  }

  mark_stage "canary_stage" "PASS"
}

run_db_assertion() {
  : >"${DB_ASSERTION_JSON}"

  if [[ "${STAGE_STATUS[journal_health]}" != "PASS" ]]; then
    python3 - "${DB_ASSERTION_JSON}" <<'PY'
import json
import sys
out = sys.argv[1]
payload = {
    "stage": "db_assertion",
    "pass": False,
    "status": "SKIPPED_PRECONDITION",
    "reason": "journal_health_not_pass",
}
with open(out, "w", encoding="utf-8") as f:
    json.dump(payload, f, indent=2)
    f.write("\n")
PY
    mark_stage "db_assertion" "SKIPPED_PRECONDITION" "journal_health_not_pass"
    return 0
  fi

  if python3 - "${KINFLOW_DB_PATH}" "${DB_ASSERTION_JSON}" <<'PY'
import json
import sqlite3
import sys

db_path = sys.argv[1]
out_path = sys.argv[2]

payload = {
    "stage": "db_assertion",
    "db_path": db_path,
    "pass": False,
    "reason": None,
    "latest_row": None,
    "checks": {},
}

try:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT attempt_id, reminder_id, attempted_at_utc, status, reason_code, provider_status_code, provider_ref
        FROM delivery_attempts
        ORDER BY attempted_at_utc DESC, rowid DESC
        LIMIT 1
        """
    ).fetchone()
    conn.close()

    if row is None:
        payload["reason"] = "no_delivery_attempt_rows"
    else:
        latest = dict(row)
        payload["latest_row"] = latest
        checks = {
            "status_delivered": latest.get("status") == "delivered",
            "reason_code_delivered_success": latest.get("reason_code") == "DELIVERED_SUCCESS",
            "provider_status_code_ok": latest.get("provider_status_code") == "ok",
            "provider_ref_non_empty": bool((latest.get("provider_ref") or "").strip()),
        }
        payload["checks"] = checks
        payload["pass"] = all(checks.values())
        if not payload["pass"]:
            failed = [k for k, v in checks.items() if not v]
            payload["reason"] = "failed_checks:" + ",".join(failed)
except Exception as exc:
    payload["reason"] = f"exception:{type(exc).__name__}:{exc}"

with open(out_path, "w", encoding="utf-8") as f:
    json.dump(payload, f, indent=2)
    f.write("\n")

sys.exit(0 if payload.get("pass") else 1)
PY
  then
    mark_stage "db_assertion" "PASS"
  else
    mark_stage "db_assertion" "FAIL" "db_assertion_failed"
    return 1
  fi
}

write_summary_and_verdict() {
  : >"${STAGE_TSV}"

  local stage
  local mandatory
  for stage in "${STAGE_ORDER[@]}"; do
    mandatory="false"
    if is_mandatory_stage "${stage}"; then
      mandatory="true"
    fi
    printf '%s\t%s\t%s\t%s\n' "${stage}" "${STAGE_STATUS[${stage}]}" "${mandatory}" "${STAGE_REASON[${stage}]}" >>"${STAGE_TSV}"
  done

  local verdict="PASS"
  for stage in "${MANDATORY_STAGES[@]}"; do
    if [[ "${STAGE_STATUS[${stage}]}" != "PASS" ]]; then
      verdict="FAIL"
      break
    fi
  done

  printf '%s\n' "${verdict}" >"${FINAL_VERDICT_TXT}"

  python3 - "${STAGE_TSV}" "${SUMMARY_JSON}" "${UTCSTAMP}" "${RUN_DIR}" "${KINFLOW_DB_PATH}" "${SERVICE_NAME}" "${VERIFY_CTX002_GOLDEN_DRY_RUN}" "${verdict}" <<'PY'
import json
import sys
from pathlib import Path

stage_tsv, summary_json, utcstamp, run_dir, db_path, service_name, dry_run_flag, verdict = sys.argv[1:]

stages = []
with open(stage_tsv, "r", encoding="utf-8") as f:
    for line in f:
        stage, status, mandatory, reason = line.rstrip("\n").split("\t", 3)
        stages.append(
            {
                "stage": stage,
                "status": status,
                "mandatory": mandatory == "true",
                "reason": reason or None,
            }
        )

summary = {
    "run_timestamp_utc": utcstamp,
    "run_dir": run_dir,
    "service_name": service_name,
    "db_path": db_path,
    "dry_run": dry_run_flag == "1",
    "final_verdict": verdict,
    "stages": stages,
    "artifacts": {
        "compile_check_log": str(Path(run_dir) / "compile_check.log"),
        "targeted_tests_log": str(Path(run_dir) / "targeted_tests.log"),
        "daemon_restart_log": str(Path(run_dir) / "daemon_restart.log"),
        "journal_health_log": str(Path(run_dir) / "journal_health.log"),
        "canary_stage_log": str(Path(run_dir) / "canary_stage.log"),
        "db_assertion_json": str(Path(run_dir) / "db_assertion.json"),
        "summary_json": str(Path(run_dir) / "summary.json"),
        "final_verdict_txt": str(Path(run_dir) / "final_verdict.txt"),
    },
}

with open(summary_json, "w", encoding="utf-8") as f:
    json.dump(summary, f, indent=2)
    f.write("\n")
PY

  local concise="compile_check=${STAGE_STATUS[compile_check]} targeted_tests=${STAGE_STATUS[targeted_tests]} daemon_restart=${STAGE_STATUS[daemon_restart]} journal_health=${STAGE_STATUS[journal_health]} canary_stage=${STAGE_STATUS[canary_stage]} db_assertion=${STAGE_STATUS[db_assertion]} verdict=${verdict} artifacts=${RUN_DIR}"
  echo "${concise}"

  if [[ "${verdict}" == "PASS" ]]; then
    return 0
  fi
  return 1
}

run_compile_check || true
run_targeted_tests || true
run_daemon_restart || true
run_journal_health || true
run_canary_stage || true
run_db_assertion || true
write_summary_and_verdict
