-- Enforce target_ref width alignment (<=256) for delivery destination rows.
-- Compatibility-lock remediation for per-event destination contract v0.1.9 §4.5.

PRAGMA foreign_keys = OFF;

CREATE TABLE IF NOT EXISTS delivery_targets_v3 (
  target_id TEXT PRIMARY KEY,
  person_id TEXT NOT NULL,
  channel TEXT NOT NULL,
  target_ref TEXT NOT NULL,
  timezone TEXT NULL,
  quiet_hours_start INTEGER NOT NULL DEFAULT 23,
  quiet_hours_end INTEGER NOT NULL DEFAULT 7,
  is_active INTEGER NOT NULL DEFAULT 1,
  updated_at_utc TEXT NOT NULL,
  CONSTRAINT ck_delivery_targets_target_ref_max_256 CHECK (length(target_ref) <= 256)
);

INSERT INTO delivery_targets_v3(
  target_id,
  person_id,
  channel,
  target_ref,
  timezone,
  quiet_hours_start,
  quiet_hours_end,
  is_active,
  updated_at_utc
)
SELECT
  target_id,
  person_id,
  channel,
  target_ref,
  timezone,
  quiet_hours_start,
  quiet_hours_end,
  is_active,
  updated_at_utc
FROM delivery_targets;

DROP TABLE delivery_targets;
ALTER TABLE delivery_targets_v3 RENAME TO delivery_targets;

CREATE INDEX IF NOT EXISTS idx_delivery_targets_person_id ON delivery_targets(person_id);
CREATE INDEX IF NOT EXISTS idx_delivery_targets_channel_target_ref ON delivery_targets(channel, target_ref);

PRAGMA foreign_keys = ON;
