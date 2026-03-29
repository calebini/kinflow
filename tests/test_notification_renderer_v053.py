from __future__ import annotations

import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ctx002_v0.notification_renderer import (
    FALLBACK_REASON_CODE,
    RenderResult,
    render_reminder_text,
)
from ctx002_v0.persistence.db import bootstrap_database


class _BadText:
    def __str__(self) -> str:
        raise RuntimeError("boom")


class NotificationRendererV053Tests(unittest.TestCase):
    def test_happy_path_exact_primary_render(self) -> None:
        out = render_reminder_text(
            {
                "event_id": "evt-1",
                "reminder_id": "rem-1",
                "title_display": "Movie Night",
                "display_time_hhmm": "09:00",
                "display_tz_label": "Europe/Paris",
            }
        )
        self.assertEqual(out.message, "🔔 Reminder: Movie Night at 09:00 (Europe/Paris)")
        self.assertFalse(out.fallback_used)
        self.assertIsNone(out.reason_code)

    def test_title_normalization_and_truncation_120_total(self) -> None:
        title = "X\n\t" + ("A" * 150)
        out = render_reminder_text(
            {
                "event_id": "evt-1",
                "reminder_id": "rem-1",
                "title_display": title,
                "display_time_hhmm": "10:30",
                "display_tz_label": "UTC",
            }
        )
        rendered_title = out.message.split(" at ")[0].replace("🔔 Reminder: ", "")
        self.assertEqual(len(rendered_title), 120)
        self.assertTrue(rendered_title.endswith("…"))
        self.assertFalse(out.fallback_used)

    def test_invalid_time_shape_and_impossible_time_fallback(self) -> None:
        bad_shape = render_reminder_text(
            {
                "event_id": "evt-1",
                "reminder_id": "rem-1",
                "title_display": "T",
                "display_time_hhmm": "9:0",
                "display_tz_label": "UTC",
            }
        )
        bad_value = render_reminder_text(
            {
                "event_id": "evt-1",
                "reminder_id": "rem-1",
                "title_display": "T",
                "display_time_hhmm": "24:00",
                "display_tz_label": "UTC",
            }
        )
        self.assertTrue(bad_shape.fallback_used)
        self.assertTrue(bad_value.fallback_used)
        self.assertEqual(bad_shape.reason_code, FALLBACK_REASON_CODE)
        self.assertEqual(bad_value.reason_code, FALLBACK_REASON_CODE)

    def test_tz_label_sanitization_and_length(self) -> None:
        out = render_reminder_text(
            {
                "event_id": "evt-1",
                "reminder_id": "rem-1",
                "title_display": "T",
                "display_time_hhmm": "09:00",
                "display_tz_label": "  Europe/\nParis\t  ",
            }
        )
        self.assertEqual(out.message, "🔔 Reminder: T at 09:00 (Europe/ Paris)")
        too_long = render_reminder_text(
            {
                "event_id": "evt-1",
                "reminder_id": "rem-1",
                "title_display": "T",
                "display_time_hhmm": "09:00",
                "display_tz_label": "X" * 65,
            }
        )
        self.assertTrue(too_long.fallback_used)

    def test_exception_fallback_of_fallback(self) -> None:
        out = render_reminder_text(
            {
                "event_id": _BadText(),
                "reminder_id": _BadText(),
                "title_display": _BadText(),
                "display_time_hhmm": "09:00",
                "display_tz_label": "UTC",
            }
        )
        self.assertTrue(out.fallback_used)
        self.assertEqual(out.reason_code, FALLBACK_REASON_CODE)
        self.assertEqual(out.message, "[KINFLOW] Reminder unknown-event (unknown-reminder)")


def _load_dispatch_runner_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "dispatch_runner_tick.py"
    spec = importlib.util.spec_from_file_location("dispatch_runner_tick", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DispatchRunnerIntegrationV053Tests(unittest.TestCase):
    def test_registry_missing_gate_returns_no_go(self) -> None:
        tick = _load_dispatch_runner_module()

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            result = tick.run_tick(
                db_path=str(out / "missing.sqlite"),
                out_dir=out,
                registry_path=out / "missing_registry.md",
            )
            self.assertEqual(result["status"], "NO_GO")
            self.assertEqual(result["error"], "RENDER_REGISTRY_GATE_UNAVAILABLE")

    def test_fallback_audit_marker_emitted_and_delivery_lifecycle_unchanged(self) -> None:
        tick = _load_dispatch_runner_module()

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            db_path = tmp / "runtime.sqlite"
            bootstrap_database(str(db_path))

            conn = sqlite3.connect(db_path)
            now = "2026-03-29T15:30:00+00:00"
            conn.execute(
                "INSERT INTO enum_reason_codes(code,class,active,version_tag) VALUES (?,?,?,?)",
                ("RENDER_FALLBACK_USED", "runtime", 1, "v0.5.3"),
            )
            conn.execute(
                "INSERT INTO events(event_id,current_version,status,created_at_utc,updated_at_utc) VALUES (?,?,?,?,?)",
                ("evt-1", 1, "active", now, now),
            )
            conn.execute(
                """
                INSERT INTO event_versions(
                    event_id,version,title,start_at_local_iso,end_at_local_iso,all_day,event_timezone,
                    participants_json,audience_json,reminder_offset_minutes,source_message_ref,
                    intent_hash,normalized_fields_hash,created_at_utc
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    "evt-1",
                    1,
                    "T",
                    "2026-03-29T16:30:00",
                    None,
                    0,
                    "UTC",
                    "[]",
                    "[]",
                    30,
                    "m1",
                    "h1",
                    "h2",
                    now,
                ),
            )
            conn.execute(
                "INSERT INTO delivery_targets("
                "target_id,person_id,channel,target_ref,timezone,is_active,updated_at_utc"
                ") VALUES (?,?,?,?,?,?,?)",
                ("caleb", "caleb", "discord", "user:caleb", "UTC", 1, now),
            )
            conn.execute(
                """
                INSERT INTO reminders(
                    reminder_id,dedupe_key,event_id,event_version,recipient_target_id,offset_minutes,
                    trigger_at_utc,next_attempt_at_utc,attempts,status,recipient_timezone_snapshot,tz_source,
                    last_error_code,created_at_utc,updated_at_utc
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    "rem-1",
                    "dedupe-1",
                    "evt-1",
                    1,
                    "caleb",
                    30,
                    now,
                    None,
                    0,
                    "scheduled",
                    "UTC",
                    "EXPLICIT",
                    None,
                    now,
                    now,
                ),
            )
            conn.commit()
            conn.close()

            (tmp / "registry.md").write_text("RENDER_FALLBACK_USED", encoding="utf-8")

            with mock.patch.object(
                tick,
                "render_reminder_text",
                return_value=RenderResult(
                    message="[KINFLOW] Reminder evt-1 (rem-1)",
                    fallback_used=True,
                    reason_code=FALLBACK_REASON_CODE,
                ),
            ), mock.patch.object(tick, "_send_via_openclaw", return_value=(True, {"returncode": 0})):
                result = tick.run_tick(
                    db_path=str(db_path),
                    out_dir=tmp,
                    registry_path=tmp / "registry.md",
                )

            self.assertEqual(result["status"], "OK")
            self.assertEqual(len(result["outcomes"]), 1)
            self.assertEqual(result["outcomes"][0]["reason_code"], "DELIVERED_SUCCESS")

            conn2 = sqlite3.connect(db_path)
            row = conn2.execute(
                "SELECT reason_code,payload_json FROM audit_log WHERE reason_code='RENDER_FALLBACK_USED'"
            ).fetchone()
            self.assertIsNotNone(row)
            payload = json.loads(row[1])
            self.assertEqual(payload["event"], "RENDER_FALLBACK_USED")
            self.assertEqual(payload["renderer_version"], "KINFLOW_NOTIFICATION_RENDERING_MIN_SPEC_v0.5.3")
            conn2.close()


if __name__ == "__main__":
    unittest.main()
