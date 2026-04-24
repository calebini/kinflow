-- Per-event destination override schema (v0.1.9 contract slice)
-- Additive schema only.

PRAGMA foreign_keys = OFF;

ALTER TABLE event_versions
ADD COLUMN event_override_channel TEXT NULL
CHECK (event_override_channel IS NULL OR event_override_channel IN ('discord','signal','telegram','whatsapp','openclaw_auto'));

ALTER TABLE event_versions
ADD COLUMN event_override_target_ref TEXT NULL
CHECK (event_override_target_ref IS NULL OR length(event_override_target_ref) <= 256);

ALTER TABLE event_versions
ADD COLUMN request_context_default_channel TEXT NULL
CHECK (request_context_default_channel IS NULL OR request_context_default_channel IN ('discord','signal','telegram','whatsapp','openclaw_auto'));

ALTER TABLE event_versions
ADD COLUMN request_context_default_target_ref TEXT NULL
CHECK (request_context_default_target_ref IS NULL OR length(request_context_default_target_ref) <= 256);

ALTER TABLE reminders
ADD COLUMN event_override_channel TEXT NULL
CHECK (event_override_channel IS NULL OR event_override_channel IN ('discord','signal','telegram','whatsapp','openclaw_auto'));

ALTER TABLE reminders
ADD COLUMN event_override_target_ref TEXT NULL
CHECK (event_override_target_ref IS NULL OR length(event_override_target_ref) <= 256);

ALTER TABLE reminders
ADD COLUMN request_context_default_channel TEXT NULL
CHECK (request_context_default_channel IS NULL OR request_context_default_channel IN ('discord','signal','telegram','whatsapp','openclaw_auto'));

ALTER TABLE reminders
ADD COLUMN request_context_default_target_ref TEXT NULL
CHECK (request_context_default_target_ref IS NULL OR length(request_context_default_target_ref) <= 256);

ALTER TABLE delivery_attempts
ADD COLUMN destination_source TEXT NULL
CHECK (destination_source IS NULL OR destination_source IN ('event_override','request_context_default','recipient_default','none'));

ALTER TABLE delivery_attempts
ADD COLUMN destination_resolution_status TEXT NULL
CHECK (destination_resolution_status IS NULL OR destination_resolution_status IN ('ok','invalid','missing'));

ALTER TABLE delivery_attempts
ADD COLUMN resolved_channel TEXT NULL
CHECK (resolved_channel IS NULL OR resolved_channel IN ('discord','signal','telegram','whatsapp','openclaw_auto'));

ALTER TABLE delivery_attempts
ADD COLUMN resolved_target_ref TEXT NULL
CHECK (resolved_target_ref IS NULL OR length(resolved_target_ref) <= 256);

ALTER TABLE delivery_attempts
ADD COLUMN attempted_channel TEXT NULL
CHECK (attempted_channel IS NULL OR attempted_channel IN ('discord','signal','telegram','whatsapp','openclaw_auto'));

ALTER TABLE delivery_attempts
ADD COLUMN attempted_target_ref TEXT NULL
CHECK (attempted_target_ref IS NULL OR length(attempted_target_ref) <= 256);

PRAGMA foreign_keys = ON;
