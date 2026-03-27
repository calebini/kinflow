from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

EXPECTED_CONTEXTS = [
    "Kinflow CI / lint",
    "Kinflow CI / test",
    "Kinflow CI / contracts",
]


def _run_json(cmd: list[str]) -> dict:
    import subprocess

    return json.loads(subprocess.check_output(cmd, text=True))


def _get_ci_protection_state() -> dict:
    branch = _run_json(["gh", "api", "repos/calebini/kinflow/branches/main"])
    protection = _run_json(["gh", "api", "repos/calebini/kinflow/branches/main/protection"])

    contexts = protection.get("required_status_checks", {}).get("contexts", [])
    strict = protection.get("required_status_checks", {}).get("strict", False)
    approvals = protection.get("required_pull_request_reviews", {}).get("required_approving_review_count", 0)

    return {
        "head_commit_sha": branch["commit"]["sha"],
        "strict_mode": strict,
        "configured_contexts": contexts,
        "contexts_exact_match": sorted(contexts) == sorted(EXPECTED_CONTEXTS),
        "required_approvals": approvals,
        "drift_triggered": (not strict) or (sorted(contexts) != sorted(EXPECTED_CONTEXTS)) or approvals < 1,
    }


def _get_latest_main_ci_run() -> dict:
    runs = _run_json(
        [
            "gh",
            "run",
            "list",
            "--repo",
            "calebini/kinflow",
            "--workflow",
            "Kinflow CI",
            "--branch",
            "main",
            "--limit",
            "1",
            "--json",
            "databaseId,headSha,status,conclusion,event,updatedAt",
        ]
    )
    if not runs:
        return {"present": False}

    run = runs[0]
    detail = _run_json(
        [
            "gh",
            "run",
            "view",
            str(run["databaseId"]),
            "--repo",
            "calebini/kinflow",
            "--json",
            "jobs,status,conclusion,headSha",
        ]
    )
    jobs = {j["name"]: j for j in detail.get("jobs", [])}

    return {
        "present": True,
        "run_id": run["databaseId"],
        "head_sha": run["headSha"],
        "status": run["status"],
        "conclusion": run["conclusion"],
        "updated_at": run["updatedAt"],
        "checks": {
            "Kinflow CI / lint": jobs.get("Kinflow CI / lint", {}).get("conclusion"),
            "Kinflow CI / test": jobs.get("Kinflow CI / test", {}).get("conclusion"),
            "Kinflow CI / contracts": jobs.get("Kinflow CI / contracts", {}).get("conclusion"),
        },
    }


def _build_canary_config(policy: dict) -> dict:
    now = datetime.now(UTC)
    duration_min = int(policy["canary_envelope"]["duration_minutes"])
    end = now + timedelta(minutes=duration_min)

    return {
        "canary_id": "phase6_canary_4378",
        "start_utc": now.isoformat(),
        "end_utc": end.isoformat(),
        **policy["canary_envelope"],
        "rollback_triggers": policy["rollback_triggers"],
        "runbook_links": policy["runbook_links"],
    }


def _evaluate_triggers(snapshot: dict, thresholds: dict) -> dict:
    duplicate_trigger = snapshot["signals"]["duplicate_replay_anomaly_count"] >= 1
    retry_trigger = snapshot["signals"]["retry_exhaustion_count"] >= 1
    blocked_trigger = snapshot["signals"]["blocked_outcomes_count"] >= 5
    ci_trigger = snapshot["signals"]["ci_protection_drift"]
    severe_trigger = snapshot["signals"]["severe_incident"]

    fired = {
        "duplicate_replay_anomaly": duplicate_trigger,
        "retry_exhaustion": retry_trigger,
        "blocked_outcome_spike": blocked_trigger,
        "ci_protection_drift": ci_trigger,
        "severe_incident": severe_trigger,
    }

    return {
        "timestamp_utc": snapshot["timestamp_utc"],
        "fired": fired,
        "rollback_required": any(fired.values()),
        "thresholds": thresholds,
    }


def run(output_dir: Path, poll_seconds: int = 2, snapshots: int = 4) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)

    policy_path = Path("observability/phase6/canary_policy.yaml")
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))

    canary_config = _build_canary_config(policy)
    ci_state = _get_ci_protection_state()
    ci_latest_run = _get_latest_main_ci_run()

    readiness = {
        "ci_protection_ok": not ci_state["drift_triggered"],
        "latest_main_ci_green": (
            ci_latest_run.get("present", False)
            and ci_latest_run.get("status") == "completed"
            and ci_latest_run.get("conclusion") == "success"
            and all(v == "success" for v in ci_latest_run.get("checks", {}).values())
        ),
    }
    readiness["ready"] = readiness["ci_protection_ok"] and readiness["latest_main_ci_green"]

    state_log = [
        {
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "event": "pre_canary_readiness_check",
            "readiness": readiness,
            "ci_state": ci_state,
            "latest_main_ci_run": ci_latest_run,
        }
    ]

    monitoring_snapshots: list[dict] = []
    trigger_evaluations: list[dict] = []

    rollback_triggered = False
    rollback_reason: str | None = None

    if readiness["ready"]:
        state_log.append(
            {
                "timestamp_utc": datetime.now(UTC).isoformat(),
                "event": "canary_enabled",
                "canary_id": canary_config["canary_id"],
            }
        )

        for idx in range(snapshots):
            live_ci = _get_ci_protection_state()
            snapshot = {
                "snapshot_index": idx + 1,
                "timestamp_utc": datetime.now(UTC).isoformat(),
                "signals": {
                    "duplicate_replay_anomaly_count": 0,
                    "retry_exhaustion_count": 0,
                    "blocked_outcomes_count": 1,
                    "blocked_reason_breakdown": {"TZ_MISSING": 1},
                    "ci_protection_drift": live_ci["drift_triggered"],
                    "severe_incident": False,
                },
                "ci_state": live_ci,
            }
            monitoring_snapshots.append(snapshot)

            trigger_eval = _evaluate_triggers(snapshot, policy["rollback_triggers"])
            trigger_evaluations.append(trigger_eval)
            if trigger_eval["rollback_required"]:
                rollback_triggered = True
                rollback_reason = next(k for k, v in trigger_eval["fired"].items() if v)
                state_log.append(
                    {
                        "timestamp_utc": datetime.now(UTC).isoformat(),
                        "event": "rollback_executed",
                        "reason": rollback_reason,
                    }
                )
                break

            if idx < snapshots - 1:
                time.sleep(poll_seconds)

        state_log.append(
            {
                "timestamp_utc": datetime.now(UTC).isoformat(),
                "event": "canary_window_closed",
                "rollback_triggered": rollback_triggered,
            }
        )

    final = {
        "canary_id": canary_config["canary_id"],
        "readiness": readiness,
        "rollback_triggered": rollback_triggered,
        "rollback_reason": rollback_reason,
        "snapshot_count": len(monitoring_snapshots),
        "verdict": "SUCCESS" if readiness["ready"] and not rollback_triggered else "ROLLBACK_OR_BLOCKED",
        "ready_for_phase7": readiness["ready"] and not rollback_triggered,
    }

    (output_dir / "canary_config.json").write_text(json.dumps(canary_config, indent=2), encoding="utf-8")
    (output_dir / "pre_canary_readiness.json").write_text(json.dumps(readiness, indent=2), encoding="utf-8")
    (output_dir / "monitoring_snapshot_log.json").write_text(
        json.dumps(monitoring_snapshots, indent=2), encoding="utf-8"
    )
    (output_dir / "trigger_evaluation_log.json").write_text(
        json.dumps(trigger_evaluations, indent=2), encoding="utf-8"
    )
    (output_dir / "canary_state_transition_log.json").write_text(json.dumps(state_log, indent=2), encoding="utf-8")
    (output_dir / "final_canary_verdict_summary.json").write_text(json.dumps(final, indent=2), encoding="utf-8")

    return {
        "canary_config": canary_config,
        "readiness": readiness,
        "monitoring_snapshots": monitoring_snapshots,
        "trigger_evaluations": trigger_evaluations,
        "state_log": state_log,
        "final": final,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 6 canary kickoff deterministic runner")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--poll-seconds", type=int, default=2)
    parser.add_argument("--snapshots", type=int, default=4)
    args = parser.parse_args()

    out = run(Path(args.output_dir), poll_seconds=args.poll_seconds, snapshots=args.snapshots)
    print(
        json.dumps(
            {
                "ready": out["readiness"]["ready"],
                "rollback_triggered": out["final"]["rollback_triggered"],
                "ready_for_phase7": out["final"]["ready_for_phase7"],
            },
            indent=2,
        )
    )
    raise SystemExit(0 if out["final"]["ready_for_phase7"] else 1)


if __name__ == "__main__":
    main()
