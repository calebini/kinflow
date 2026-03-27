# KINFLOW WhatsApp Target-Shape Discovery (Run 4339)

- Instruction ID: `KINFLOW-WHATSAPP-TARGET-SHAPE-DISCOVERY-20260323-001`
- Run Code: `4339`
- Probe Script: `/home/agent/projects/apps/kinflow/scripts/whatsapp_target_shape_probe.py`
- Raw Results Artifact: `/home/agent/projects/_backlog/output/kinflow_whatsapp_target_shape_4339_20260323T234000Z/raw_results.json`
- Timestamp (UTC): `2026-03-23T23:34:24Z`

## Purpose

Perform focused WhatsApp target-shape discovery for OpenClaw to determine canonical target format(s) for Kinflow adapter pre-validation and send behavior.

## Lint Preflight Gate

```bash
python3 -m compileall -q src scripts tests
```

Result: `LINT_PASS_NORMALIZED` (gate satisfied; probe execution allowed).

## Discovery Sequence

### 1) Enumeration from current runtime context
Attempted deterministic enumeration commands:
- `openclaw message channel-list --channel whatsapp --json`
- `openclaw message channel-info --channel whatsapp --json`
- `openclaw message thread-list --channel whatsapp --json`

Outcome: enumeration via these flags is **unsupported in current runtime CLI surface** for message plugin commands (`error: unknown option '--channel'`).

Disposition: marked as `unsupported/not available` and continued with controlled candidate probes per instruction.

### 2) Deterministic send probes (approved `g-caleb-loop` intent)
Low-noise probe payload prefix used for all sends:
- `[KINFLOW WA TARGET PROBE] {... "test_only": true, "noise_level": "low" ...}`

Candidate matrix:

| Case ID | Candidate target form | Outcome | Evidence signature |
|---|---|---|---|
| `c01_alias_protocol_prefixed` | `whatsapp:g-caleb-loop` | **FAIL** (`REJECTED_TARGET_SHAPE`) | `Delivering to WhatsApp requires target <E.164|group JID> or channels.whatsapp.allowFrom[0]` |
| `c02_alias_plain` | `g-caleb-loop` | **FAIL** (`REJECTED_UNKNOWN_TARGET`) | `Unknown target "g-caleb-loop" for WhatsApp. Hint: <E.164|group JID>` |
| `c03_group_jid_plain` | `120363425701060269@g.us` | **PASS** (`ACCEPTED`) | returncode `0`; payload result includes `messageId`, `toJid=120363425701060269@g.us` |
| `c04_group_jid_protocol_prefixed` | `whatsapp:120363425701060269@g.us` | **PASS** (`ACCEPTED`) | returncode `0`; payload normalized to `to=120363425701060269@g.us` with `messageId` |

### 3) Raw accept/reject payload capture
Captured in:
- `/home/agent/projects/_backlog/output/kinflow_whatsapp_target_shape_4339_20260323T234000Z/raw_results.json`

Includes full argv, returncode, stdout/stderr, parsed payload, and normalized class per candidate.

---

## Canonical Recommendation Block

### Accepted target format(s)
1. **Canonical (preferred):** plain WhatsApp group JID
   - Example: `120363425701060269@g.us`
2. **Also accepted (normalizable):** provider-prefixed group JID
   - Example: `whatsapp:120363425701060269@g.us`
   - Normalization behavior observed: gateway resolves to plain group JID in output payload.

### Rejected format(s) + reason patterns
- `whatsapp:g-caleb-loop` → rejected as invalid shape; reason pattern: `requires target <E.164|group JID>`.
- `g-caleb-loop` → rejected as unknown target; reason pattern: `Unknown target ... Hint: <E.164|group JID>`.

### Adapter pre-validation rule (before send)
Enforce one of:
- E.164 phone number (digits, optional leading `+`), or
- WhatsApp group JID (`<digits>@g.us`), with optional `whatsapp:` prefix.

Recommended normalization and regex:
- Normalize: strip optional `whatsapp:` prefix before transport submit.
- Regex:
  - `^(?:whatsapp:)?(?:\+?[1-9]\d{6,14}|\d{10,30}@g\.us)$`

Practical policy for Kinflow adapter:
- Accept alias-like forms only if explicitly resolved to a canonical JID upstream.
- Reject unresolved logical aliases pre-send with typed error class: `TARGET_SHAPE_INVALID_OR_UNRESOLVED_ALIAS`.

### Impact on OpenClaw adapter implementation spec updates
1. Update WhatsApp target contract section to designate `group JID` / `E.164` as canonical runtime-validated forms.
2. Add explicit normalization step for optional `whatsapp:` prefix.
3. Add deterministic error mapping:
   - `requires target <E.164|group JID>` → `TARGET_SHAPE_INVALID`
   - `Unknown target ... Hint: <E.164|group JID>` → `TARGET_UNRESOLVED`
4. Mark logical alias (`g-caleb-loop`) as non-canonical input unless a resolver stage is configured.

---

## Knuth Handoff Block

- READY_FOR_LANDING: `YES`
- Exact re-run commands:
  1. `cd /home/agent/projects/apps/kinflow`
  2. `python3 scripts/whatsapp_target_shape_probe.py --run-code 4339 --timestamp 20260323T234000Z`
- Expected outputs/artifact paths:
  - `/home/agent/projects/_backlog/output/kinflow_whatsapp_target_shape_4339_20260323T234000Z/raw_results.json`
  - `/home/agent/projects/apps/kinflow/docs/KINFLOW_WHATSAPP_TARGET_SHAPE_DISCOVERY_4339.md`
- Rollback notes:
  - `git checkout -- scripts/whatsapp_target_shape_probe.py docs/KINFLOW_WHATSAPP_TARGET_SHAPE_DISCOVERY_4339.md`
  - `rm -rf /home/agent/projects/_backlog/output/kinflow_whatsapp_target_shape_4339_20260323T234000Z`

---

ChangeLog Entry ID: `CL-20260323-233424Z-4339-KINFLOW-WA-TARGET-SHAPE`
ChangeLog Path: `/home/agent/.openclaw/workspace-knuth/ops/CHANGELOG.md`
Tier: `L1`
Final Status: `OK`
