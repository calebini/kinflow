from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path


@dataclass(frozen=True)
class ReasonCodeBinding:
    spec_path: str
    spec_version: str
    spec_sha256: str


class ReasonCodeBindingError(RuntimeError):
    pass


def validate_reason_code_binding(binding: ReasonCodeBinding) -> None:
    spec_file = Path(binding.spec_path)
    if not spec_file.exists():
        raise ReasonCodeBindingError(f"reason code spec missing: {binding.spec_path}")

    observed_hash = sha256(spec_file.read_bytes()).hexdigest()
    if observed_hash != binding.spec_sha256:
        raise ReasonCodeBindingError(
            "reason code spec hash mismatch: "
            f"expected={binding.spec_sha256} observed={observed_hash} version={binding.spec_version}"
        )
