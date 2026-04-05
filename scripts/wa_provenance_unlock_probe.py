from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from ctx002_v0.oc_adapter import OutboundMessage
from daemon_run import build_oc_adapter_binding


def _read_systemd_env() -> dict[str, str]:
    out = subprocess.check_output(
        ["systemctl", "show", "kinflow-daemon.service", "-p", "Environment", "--no-pager"], text=True
    )
    m = re.search(r"^Environment=(.*)$", out, re.M)
    env: dict[str, str] = {}
    if not m:
        return env
    tokens = re.findall(r'(?:[^\s"]+="[^"]*"|[^\s]+)', m.group(1))
    for t in tokens:
        if "=" in t:
            k, v = t.split("=", 1)
            env[k] = v.strip('"')
    return env


def _provenance_fields() -> dict[str, str]:
    sys_env = _read_systemd_env()
    return {
        "auth_source": "systemd_environment" if sys_env.get("OPENCLAW_ACCOUNT") else "process_environment",
        "auth_profile_id": sys_env.get("OPENCLAW_PROFILE") or os.environ.get("OPENCLAW_PROFILE") or "missing",
        "runtime_env_source": "systemctl:kinflow-daemon.service",
        "channel_route_selected": sys_env.get("OPENCLAW_CHANNEL") or os.environ.get("OPENCLAW_CHANNEL") or "missing",
        "target_ref": sys_env.get("OPENCLAW_TARGET") or os.environ.get("OPENCLAW_TARGET") or "",
    }


def run(output_dir: Path) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    prov = _provenance_fields()

    target = prov.get("target_ref") or "120363425701060269@g.us"
    now = datetime.now(UTC)
    outbound = OutboundMessage(
        delivery_id=f"dly-provunlock-{now.strftime('%H%M%S')}",
        attempt_id=f"att-provunlock-{now.strftime('%H%M%S')}",
        attempt_index=1,
        trace_id="wa_provenance_unlock_probe",
        causation_id="run-20260405-07",
        channel_hint="whatsapp",
        target_ref=target,
        subject_type="probe",
        priority="normal",
        body_text="WA provenance unlock direct adapter proof",
        dedupe_key=f"provunlock-{now.strftime('%Y%m%dT%H%M%SZ')}",
        created_at_utc=now,
        metadata_json={"run_code": "20260405-07", "purpose": "provenance_unlock"},
        metadata_schema_version=1,
    )

    adapter = build_oc_adapter_binding()
    result = adapter.send(outbound)

    (output_dir / "adapter_send_provenance_capture.json").write_text(
        json.dumps(
            {
                "timestamp_utc": now.isoformat(),
                "send_boundary": {
                    "module": "scripts/wa_provenance_unlock_probe.py",
                    "function": "run",
                    "adapter_call": "build_oc_adapter_binding -> OpenClawGatewayAdapter.send",
                },
                "provenance": prov,
            },
            indent=2,
            default=str,
        )
    )

    (output_dir / "direct_adapter_probe_request_response.json").write_text(
        json.dumps(
            {
                "request": {
                    "channel_hint": outbound.channel_hint,
                    "target_ref": outbound.target_ref,
                    "subject_type": outbound.subject_type,
                    "priority": outbound.priority,
                    "body_text": outbound.body_text,
                    "trace_id": outbound.trace_id,
                },
                "response": {
                    "status": result.status,
                    "reason_code": result.reason_code,
                    "provider_status_code": result.provider_status_code,
                    "provider_receipt_ref": result.provider_receipt_ref,
                    "provider_accept_only": result.provider_accept_only,
                    "delivery_confidence": result.delivery_confidence,
                },
            },
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    import sys

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("./output")
    raise SystemExit(run(out))
