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
    target: str
    rationale: str


def _utc_stamp() -> str:
    return datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")


def _run(cmd: list[str], cwd: Path, timeout_s: int = 20) -> dict[str, Any]:
    try:
        completed = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout_s)
        return {
            "argv": cmd,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "argv": cmd,
            "returncode": 124,
            "stdout": exc.stdout or "",
            "stderr": (exc.stderr or "") + f"\nTIMEOUT_EXPIRED_{timeout_s}s",
            "timed_out": True,
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
    if raw["returncode"] == 0 and isinstance(parsed, dict):
        payload = parsed.get("payload") or {}
        result = payload.get("result") or {}
        if payload.get("ok") is True or result.get("messageId"):
            return "ACCEPTED"
    hay = "\n".join([raw.get("stdout", ""), raw.get("stderr", "")]).lower()
    if "timeout_expired" in hay:
        return "REJECTED_TIMEOUT"
    if "cross-context" in hay:
        return "REJECTED_CROSS_CONTEXT"
    if "requires target" in hay:
        return "REJECTED_TARGET_SHAPE"
    if "unknown target" in hay:
        return "REJECTED_UNKNOWN_TARGET"
    if "no active whatsapp web listener" in hay:
        return "REJECTED_LISTENER_UNAVAILABLE"
    return "REJECTED_OTHER"


def _message(run_code: str, case_id: str, target: str) -> str:
    payload = {
        "probe": "KINFLOW_WHATSAPP_TARGET_SHAPE_DISCOVERY",
        "run_code": run_code,
        "case_id": case_id,
        "target": target,
        "test_only": True,
        "noise_level": "low",
    }
    return "[KINFLOW WA TARGET PROBE] " + json.dumps(payload, sort_keys=True)


def run_probe(run_code: str, output_dir: Path, root: Path) -> dict[str, Any]:
    lint = _run(["python3", "-m", "compileall", "-q", "src", "scripts", "tests"], cwd=root)
    lint_status = "LINT_PASS_NORMALIZED" if lint["returncode"] == 0 else "LINT_FAIL"

    results: dict[str, Any] = {
        "instruction_id": "KINFLOW-WHATSAPP-TARGET-SHAPE-DISCOVERY-20260323-001",
        "run_code": run_code,
        "timestamp_utc": datetime.now(tz=UTC).isoformat(),
        "lint_preflight": {
            "command": "python3 -m compileall -q src scripts tests",
            "status": lint_status,
            "raw": lint,
        },
        "enumeration": [],
        "cases": [],
    }

    if lint_status not in {"LINT_PASS", "LINT_PASS_NORMALIZED"}:
        results["status"] = "BLOCKED"
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "raw_results.json").write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
        return results

    enum_cmds: list[tuple[str, list[str]]] = [
        (
            "message_channel_list_whatsapp",
            ["openclaw", "message", "channel-list", "--channel", "whatsapp", "--json"],
        ),
        (
            "message_channel_info_whatsapp",
            ["openclaw", "message", "channel-info", "--channel", "whatsapp", "--json"],
        ),
        (
            "message_thread_list_whatsapp",
            ["openclaw", "message", "thread-list", "--channel", "whatsapp", "--json"],
        ),
    ]

    for enum_id, cmd in enum_cmds:
        raw = _run(cmd, cwd=root)
        parsed = _extract_json(raw.get("stdout", ""))
        results["enumeration"].append({"enum_id": enum_id, "raw": raw, "parsed": parsed})

    cases = [
        ProbeCase("c01_alias_protocol_prefixed", "whatsapp:g-caleb-loop", "logical alias with provider prefix"),
        ProbeCase("c02_alias_plain", "g-caleb-loop", "logical alias plain form"),
        ProbeCase(
            "c03_group_jid_plain",
            "120363425701060269@g.us",
            "group JID style form discovered from runtime incident evidence",
        ),
        ProbeCase(
            "c04_group_jid_protocol_prefixed",
            "whatsapp:120363425701060269@g.us",
            "provider-prefixed group JID variant",
        ),
    ]

    for case in cases:
        cmd = [
            "openclaw",
            "message",
            "send",
            "--channel",
            "whatsapp",
            "--target",
            case.target,
            "--message",
            _message(run_code, case.case_id, case.target),
            "--json",
        ]
        raw = _run(cmd, cwd=root)
        parsed = _extract_json(raw.get("stdout", ""))
        results["cases"].append(
            {
                "case_id": case.case_id,
                "target": case.target,
                "rationale": case.rationale,
                "raw_response_payload": raw,
                "parsed_response_payload": parsed,
                "result_class": _classify(raw, parsed),
            }
        )

    results["status"] = "OK"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "raw_results.json").write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="KINFLOW WhatsApp target-shape discovery probe")
    parser.add_argument("--run-code", default="4339")
    parser.add_argument("--timestamp", default=_utc_stamp())
    parser.add_argument("--output-root", default="/home/agent/projects/_backlog/output")
    args = parser.parse_args()

    root = Path("/home/agent/projects/apps/kinflow")
    out_dir = Path(args.output_root) / f"kinflow_whatsapp_target_shape_{args.run_code}_{args.timestamp}"
    results = run_probe(run_code=args.run_code, output_dir=out_dir, root=root)
    print(json.dumps({"status": results.get("status"), "artifact_dir": str(out_dir)}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
