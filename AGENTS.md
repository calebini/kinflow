# Kinflow Agent Instructions

## Cortext1 Spec Versioning Standard

Kinflow follows the Cortext1 one-way contract pinning model.

Core doctrine:

```text
Versions communicate compatibility.
Hashes prove exact reviewed artifacts.
Tests prove behavior.
The freeze manifest is one-way authoritative.
```

Public behavior MUST be tied to a spec or contract version. Runtime code MUST declare the spec and contract versions it implements. Release-critical specs and contracts MUST be pinned in the freeze manifest by version, artifact path, and sha256.

Contract or public behavior changes require:

- updating the relevant spec or contract version;
- updating runtime implemented-version declarations;
- updating contract tests or golden fixtures;
- rebinding the freeze manifest if a pinned artifact changed.

The freeze manifest is the sole gate-critical source for canonical artifact pins. Do not add reciprocal hard-hash gates between docs, checklists, reports, or specs. Downstream docs may reference freeze entries by artifact path or Hash ID, and any copied hashes outside the manifest are informational unless a validation run explicitly copies them from the manifest.

## Required Verification

Before landing changes that touch specs, contracts, runtime declarations, migrations, or public behavior, run:

```bash
python3 scripts/verify_contract_pins.py
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v
```

If only implementation files changed and no pinned artifacts or public contracts changed, the pin verifier should still pass without a re-freeze.
