from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProbeCase:
    case_id: str
    channel: str
    target: str
    note: str


def _utc_stamp() -> str:
    return datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")


def _run(cmd: list[str], cwd: Path) -> dict[str, Any]:
    completed = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return {
        "argv": cmd,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _extract_json(stdout: str) -> Any:
    text = (stdout or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _classify(raw: dict[str, Any], parsed: Any) -> str:
    if raw["returncode"] == 0 and isinstance(parsed, dict) and parsed.get("payload", {}).get("ok") is True:
        return "SUCCESS"
    stderr = (raw.get("stderr") or "") + "\n" + (raw.get("stdout") or "")
    s = stderr.lower()
    if "cross-context" in s:
        return "BLOCKED_CROSS_CONTEXT"
    if "requires target" in s:
        return "FAIL_INVALID_TARGET_SHAPE"
    if "unknown target" in s:
        return "FAIL_UNKNOWN_TARGET"
    return "FAIL_OTHER"


def _receipt_fields(parsed: Any) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        return {}
    result = (parsed.get("payload") or {}).get("result") or {}
    keep = {}
    for key in ("messageId", "channelId", "threadId", "id", "ref", "receipt", "target"):
        if key in result:
            keep[key] = result[key]
    return keep


def _marker_echo_status(markers: dict[str, str], raw: dict[str, Any], parsed: Any) -> dict[str, bool]:
    hay = json.dumps(parsed, sort_keys=True, default=str) if parsed is not None else ""
    hay = "\n".join([hay, raw.get("stdout", ""), raw.get("stderr", "")])
    return {k: (v in hay) for k, v in markers.items()}


def _build_markers(run_code: str) -> dict[str, str]:
    stamp = _utc_stamp()
    return {
        "delivery_id": f"kinflow-delivery-{run_code}-{stamp}",
        "attempt_id": f"kinflow-attempt-{run_code}-{stamp}",
        "trace_id": f"kinflow-trace-{run_code}-{stamp}",
        "causation_id": f"kinflow-causation-{run_code}-{stamp}",
    }


def _build_message(case_id: str, markers: dict[str, str], note: str) -> str:
    payload = {
        "probe": "KINFLOW_OC_GATEWAY_ASSUMPTION_PROBE",
        "case_id": case_id,
        "note": note,
        "markers": markers,
        "test_only": True,
        "noise_level": "low",
    }
    return "[KINFLOW PROBE] " + json.dumps(payload, sort_keys=True)


def run_probe(run_code: str, output_dir: Path, root: Path) -> dict[str, Any]:
    lint = _run(["python3", "-m", "compileall", "-q", "src", "scripts", "tests"], cwd=root)
    lint_status = "LINT_PASS_NORMALIZED" if lint["returncode"] == 0 else "LINT_FAIL"

    results: dict[str, Any] = {
        "instruction_id": "KINFLOW-OC-GATEWAY-PROBE-IMPLEMENT-20260323-001",
        "run_code": run_code,
        "timestamp_utc": datetime.now(tz=UTC).isoformat(),
        "lint_preflight": {
            "command": "python3 -m compileall -q src scripts tests",
            "status": lint_status,
            "raw": lint,
        },
        "cases": [],
    }

    if lint_status not in {"LINT_PASS", "LINT_PASS_NORMALIZED"}:
        results["status"] = "BLOCKED"
        return results

    markers = _build_markers(run_code)
    cases = [
        ProbeCase(
            case_id="01_discord_current_thread",
            channel="discord",
            target="1470840649052983337",
            note="approved current Discord thread",
        ),
        ProbeCase(
            case_id="02_whatsapp_g_caleb_loop",
            channel="whatsapp",
            target="whatsapp:g-caleb-loop",
            note="approved WhatsApp alias target",
        ),
        ProbeCase(
            case_id="03_invalid_target_capture",
            channel="discord",
            target="__kinflow_invalid_target__",
            note="deterministic invalid target for error-shape capture",
        ),
    ]

    for case in cases:
        message = _build_message(case.case_id, markers, case.note)
        cmd = [
            "openclaw",
            "message",
            "send",
            "--channel",
            case.channel,
            "--target",
            case.target,
            "--message",
            message,
            "--json",
        ]
        raw = _run(cmd, cwd=root)
        parsed = _extract_json(raw.get("stdout", ""))
        normalized = {
            "success_failure_class": _classify(raw, parsed),
            "receipt_ref_fields": _receipt_fields(parsed),
            "correlation_echo_status": _marker_echo_status(markers, raw, parsed),
        }
        results["cases"].append(
            {
                "case_id": case.case_id,
                "request_payload_fixture": {
                    "channel": case.channel,
                    "target": case.target,
                    "message": message,
                    "metadata_payload": {"markers": markers},
                },
                "raw_response_payload": raw,
                "parsed_response_payload": parsed,
                "normalized": normalized,
            }
        )

    results["status"] = "OK"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "raw_results.json").write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Deterministic OpenClaw gateway assumption probe")
    parser.add_argument("--run-code", default="4338")
    parser.add_argument("--timestamp", default=_utc_stamp())
    parser.add_argument(
        "--output-root",
        default="/home/agent/projects/_backlog/output",
        help="Backlog output root for artifacts",
    )
    args = parser.parse_args()

    root = Path("/home/agent/projects/apps/kinflow")
    out_dir = Path(args.output_root) / f"kinflow_oc_gateway_probe_{args.run_code}_{args.timestamp}"

    results = run_probe(run_code=args.run_code, output_dir=out_dir, root=root)
    print(json.dumps({"status": results.get("status"), "artifact_dir": str(out_dir)}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
