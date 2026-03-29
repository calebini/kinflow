KINFLOW_NOTIFICATION_RENDERING_MIN_SPEC_v0.5.3 (Master Cut)

0) Convergence Declaration
Review Phase: MASTER_CANDIDATE
Activation Posture: STRICT (fail-closed on spec violations)
Scope Class: Notification renderer only (formatting layer)

1) Purpose
Define deterministic, user-friendly reminder message formatting for Kinflow notifications using pre-normalized display fields from upstream engine/dispatcher logic.

2) Architectural Boundary (Normative)
Renderer is dumb formatting only.
Renderer MUST NOT perform:
- timezone precedence resolution
- timezone semantic validation policy (beyond renderer input shape checks)
- DST ambiguity/nonexistent-time handling
- datetime parsing/coercion from freeform text
These responsibilities belong to engine/dispatcher upstream.

3) Renderer Input Contract
Required:
- event_id: string
- reminder_id: string
- title_display: string
- display_time_hhmm: string
- display_tz_label: string
Optional:
- debug_suffix_enabled: boolean (default: false)
Validation gates:
- event_id non-empty after trim.
- reminder_id non-empty after trim.
- title_display non-empty after normalization (§6.1).
- display_time_hhmm valid per §5.2.
- display_tz_label valid per §6.2.
If validation fails, renderer MUST return fallback (§7).

4) RenderResult (Normative Return Type)
Renderer MUST return:
- message: string
- fallback_used: boolean
- reason_code: string | null
Rules:
- fallback_used=true => reason_code MUST be non-null delivery reason code.
- fallback_used=false => reason_code MUST be null.

5) Formatting Rules (Deterministic)
5.1 Primary format (exact)
🔔 Reminder: <TITLE> at <HH:MM> (<TZ_LABEL>)

5.2 display_time_hhmm validation
display_time_hhmm MUST:
1) match regex ^\d{2}:\d{2}$
2) parse to:
   - hour 00..23
   - minute 00..59
Else fallback.

5.3 Fixed separators/invariants
- Prefix: 🔔 Reminder:
- Infix: at
- TZ wrapper: ( + )
- Single-line output only
- No trailing spaces
- UTF-8 output

6) Normalization/Sanitization
6.1 title_display normalization
Renderer MUST:
1) trim leading/trailing whitespace
2) replace newline/tab/control chars with single space
3) collapse whitespace runs to single space
4) if empty after normalization => fallback
5) truncate with max 120 total characters including ellipsis
6) if truncated, last character MUST be … (U+2026)

6.2 display_tz_label sanitization + shape
Renderer MUST:
1) trim
2) replace newline/tab/control chars with single space
3) collapse whitespace runs to single space
4) enforce non-empty value after sanitization
5) enforce max length 64 characters
6) enforce single-line UTF-8 with no control chars post-sanitization
If any rule fails => fallback.

7) Fallback Contract
7.1 Exact fallback message
[KINFLOW] Reminder <event_id> (<reminder_id>)

7.2 Delivery reason code for fallback
RENDER_FALLBACK_USED

7.3 Explicit fallback triggers
Fallback MUST trigger on any:
1) invalid/missing event_id
2) invalid/missing reminder_id
3) missing/empty normalized title_display
4) invalid/missing display_time_hhmm
5) invalid/missing sanitized display_tz_label
6) renderer exception

7.4 Fallback-of-fallback safety
If exception and ids unavailable/invalid:
- event_id="unknown-event"
- reminder_id="unknown-reminder"
- message: [KINFLOW] Reminder unknown-event (unknown-reminder)
- fallback_used=true
- reason_code=RENDER_FALLBACK_USED

8) Startup/Config Gate Tokens (Classification Explicit)
8.1 REASON_CODE_REGISTRATION_MISSING
Classification: startup/config gate error token
Not a delivery reason_code
MUST NOT appear in per-message delivery reason_code fields
Trigger: required delivery reason code (RENDER_FALLBACK_USED) absent in canonical registry at enablement/startup
Behavior: fail feature activation before message processing

8.2 DEBUG_SUFFIX_PROD_FORBIDDEN
Classification: startup/config gate error token
Not a delivery reason_code
Trigger: runtime_mode=production with debug_suffix_enabled=true
Behavior: fail feature activation (fail-closed)

9) Callsite Audit Responsibility (Exact Marker Shape)
Renderer is pure.
When RenderResult.fallback_used=true, callsite MUST append one dispatch audit marker with minimum fields:
- event: RENDER_FALLBACK_USED
- reason_code: <RenderResult.reason_code>
- event_id: <event_id or "unknown-event">
- reminder_id: <reminder_id or "unknown-reminder">
- renderer_version: KINFLOW_NOTIFICATION_RENDERING_MIN_SPEC_v0.5.3
Callsite MUST continue normal delivery flow (fallback must not block dispatch).

10) Debug Suffix Policy
Optional suffix format:
[event_id=<event_id> reminder_id=<reminder_id>]
Rules:
- disabled by default
- explicit non-production enablement required
- production mode with suffix enabled is forbidden per §8.2 (fail-closed startup/config gate)

11) Determinism Invariants
- Same canonical inputs => byte-identical output.
- No stochastic wording.
- No channel-specific phrase mutation inside renderer.

12) Acceptance Criteria
Must pass all:
1) happy-path exact primary render
2) title normalization fixture (newline/control collapse)
3) title truncation fixture proving 120 total chars incl. …
4) invalid/empty event_id => exact fallback
5) invalid/empty reminder_id => exact fallback
6) invalid time shape => exact fallback
7) impossible time (24:00, 12:60) => exact fallback
8) tz label sanitization fixture (control/newline handling)
9) tz label >64 chars => exact fallback
10) renderer exception => fallback-of-fallback exact output
11) reason-code registry startup gate proof
12) debug suffix production-forbidden startup gate proof
13) callsite audit marker emitted with exact fields (§9)
14) delivery_attempt + delivery-audit lifecycle unchanged
15) one live send proof via OpenClaw

13) Implementation Seam
Implement deterministic helper:
- render_reminder_text(payload) -> RenderResult
Integrate at active dispatch runner callsite only.
No scheduler/daemon transition logic changes.

14) Rollback
Revert callsite message to:
"[KINFLOW] Reminder {event_id} ({reminder_id})"
Remove renderer helper integration.
Run smoke dispatch proof.

15) Evidence Required
- Fixture artifact with byte-equality assertions
- Startup/config gate artifacts for §8 tokens
- Audit marker proof for §9 shape
- Live send artifact
- Finalization block with RUN_FINALIZED: YES
