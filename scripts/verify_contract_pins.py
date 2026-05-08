#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "specs" / "KINFLOW_CONTRACT_FREEZE_MANIFEST_PHASE0_5.md"
PIN_ROW_RE = re.compile(
    r"^\|\s*`(?P<hash_id>[^`]+)`\s*"
    r"\|\s*(?P<artifact>[^|]+?)\s*"
    r"\|\s*(?P<version>[^|]+?)\s*"
    r"\|\s*`(?P<path>[^`]+)`\s*"
    r"\|\s*`(?P<sha>[0-9a-f]{64})`\s*\|$"
)


@dataclass(frozen=True)
class FreezePin:
    hash_id: str
    artifact: str
    version: str
    manifest_path: str
    resolved_path: Path
    sha256: str


def _resolve_manifest_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.exists():
        return path

    marker = "/kinflow/"
    if raw_path.startswith("/") and marker in raw_path:
        relative = raw_path.split(marker, 1)[1]
        return ROOT / relative

    if not path.is_absolute():
        return ROOT / path

    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_pins() -> list[FreezePin]:
    if not MANIFEST_PATH.exists():
        raise RuntimeError(f"missing freeze manifest: {MANIFEST_PATH}")

    pins: list[FreezePin] = []
    for line in MANIFEST_PATH.read_text(encoding="utf-8").splitlines():
        match = PIN_ROW_RE.match(line)
        if not match:
            continue
        raw_path = match.group("path")
        pins.append(
            FreezePin(
                hash_id=match.group("hash_id"),
                artifact=match.group("artifact").strip(),
                version=match.group("version").strip(),
                manifest_path=raw_path,
                resolved_path=_resolve_manifest_path(raw_path),
                sha256=match.group("sha"),
            )
        )
    if not pins:
        raise RuntimeError(f"no freeze pins found in {MANIFEST_PATH}")
    return pins


def _verify_freeze_pins(pins: list[FreezePin]) -> list[str]:
    failures: list[str] = []
    for pin in pins:
        if not pin.resolved_path.exists():
            failures.append(f"MISSING_PINNED_ARTIFACT:{pin.hash_id}:{pin.manifest_path}")
            continue
        observed = _sha256(pin.resolved_path)
        if observed != pin.sha256:
            failures.append(
                f"HASH_MISMATCH:{pin.hash_id}:expected={pin.sha256}:observed={observed}:path={pin.resolved_path}"
            )
    return failures


def _verify_runtime_declarations(pins: list[FreezePin]) -> list[str]:
    sys.path.insert(0, str(ROOT / "src"))
    from ctx002_v0.contract_versions import IMPLEMENTED_CONTRACTS

    pins_by_relpath = {str(pin.resolved_path.relative_to(ROOT)): pin for pin in pins if pin.resolved_path.is_relative_to(ROOT)}
    failures: list[str] = []

    for declaration in IMPLEMENTED_CONTRACTS:
        path = ROOT / declaration.artifact_path
        if not path.exists():
            failures.append(f"DECLARED_CONTRACT_MISSING:{declaration.name}:{declaration.artifact_path}")
            continue

        pin = pins_by_relpath.get(declaration.artifact_path)
        if pin is None:
            continue
        if pin.version != declaration.version:
            failures.append(
                f"DECLARED_VERSION_MISMATCH:{declaration.name}:runtime={declaration.version}:manifest={pin.version}"
            )

    return failures


def main() -> int:
    pins = _load_pins()
    failures = _verify_freeze_pins(pins)
    failures.extend(_verify_runtime_declarations(pins))

    if failures:
        print("CONTRACT_PIN_VERIFY_FAIL")
        for failure in failures:
            print(failure)
        return 1

    print(f"CONTRACT_PIN_VERIFY_PASS:{len(pins)} pins")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
