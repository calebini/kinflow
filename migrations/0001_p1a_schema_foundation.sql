CREATE TABLE IF NOT EXISTS enum_reason_codes (
  code TEXT PRIMARY KEY,
  class TEXT NOT NULL CHECK (class IN ('resolver','time','delivery','lifecycle','recovery','system')),
  active INTEGER NOT NULL CHECK (active IN (0,1)),
  version_tag TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS enum_audit_stages (
  stage TEXT PRIMARY KEY,
  active INTEGER NOT NULL CHECK (active IN (0,1)),
  version_tag TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS enum_reminder_status (
  status TEXT PRIMARY KEY,
  terminal_flag INTEGER NOT NULL CHECK (terminal_flag IN (0,1)),
  schedulable_flag INTEGER NOT NULL CHECK (schedulable_flag IN (0,1)),
  version_tag TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS enum_attempt_status (
  status TEXT PRIMARY KEY,
  version_tag TEXT NOT NULL
);

INSERT OR REPLACE INTO enum_reason_codes(code, class, active, version_tag) VALUES
('RESOLVER_EXPLICIT','resolver',1,'v0.2.6'),
('RESOLVER_MATCHED','resolver',1,'v0.2.6'),
('RESOLVER_AMBIGUOUS','resolver',1,'v0.2.6'),
('RESOLVER_NO_MATCH','resolver',1,'v0.2.6'),
('TZ_EXPLICIT','time',1,'v0.2.6'),
('TZ_HOUSEHOLD_DEFAULT','time',1,'v0.2.6'),
('TZ_FALLBACK_USED','time',1,'v0.2.6'),
('TZ_MISSING','time',1,'v0.2.6'),
('DELIVERED','delivery',1,'v0.2.6'),
('FAILED_PROVIDER_TRANSIENT','delivery',1,'v0.2.6'),
('FAILED_PROVIDER_PERMANENT','delivery',1,'v0.2.6'),
('FAILED_CONFIG_INVALID_TARGET','delivery',1,'v0.2.6'),
('FAILED_RETRY_EXHAUSTED','delivery',1,'v0.2.6'),
('SUPPRESSED_QUIET_HOURS','delivery',1,'v0.2.6'),
('UPDATED_REGENERATED','lifecycle',1,'v0.2.6'),
('CANCEL_INVALIDATED','lifecycle',1,'v0.2.6'),
('BLOCKED_CONFIRMATION_REQUIRED','lifecycle',1,'v0.2.6'),
('VERSION_CONFLICT_RETRY','lifecycle',1,'v0.2.6'),
('RECOVERY_RECONCILED','recovery',1,'v0.2.6'),
('CAPTURE_ONLY_BLOCKED','system',1,'v0.2.6'),
('FAILED_ADAPTER_RESULT_MISSING','system',1,'v0.2.6'),
('FAILED_ADAPTER_RESULT_INVALID','system',1,'v0.2.6'),
('FAILED_ADAPTER_RESULT_UNMAPPABLE','system',1,'v0.2.6');

INSERT OR REPLACE INTO enum_audit_stages(stage, active, version_tag) VALUES
('intake',1,'v0.2.6'),
('resolver',1,'v0.2.6'),
('confirmation',1,'v0.2.6'),
('timezone',1,'v0.2.6'),
('mutation',1,'v0.2.6'),
('schedule',1,'v0.2.6'),
('delivery',1,'v0.2.6'),
('recovery',1,'v0.2.6'),
('system',1,'v0.2.6');

INSERT OR REPLACE INTO enum_reminder_status(status, terminal_flag, schedulable_flag, version_tag) VALUES
('scheduled',0,1,'v0.2.6'),
('attempted',0,1,'v0.2.6'),
('delivered',1,0,'v0.2.6'),
('failed',1,0,'v0.2.6'),
('suppressed',1,0,'v0.2.6'),
('invalidated',1,0,'v0.2.6'),
('blocked',0,0,'v0.2.6');

INSERT OR REPLACE INTO enum_attempt_status(status, version_tag) VALUES
('attempted','v0.2.6'),
('delivered','v0.2.6'),
('failed','v0.2.6'),
('suppressed','v0.2.6');

CREATE TABLE IF NOT EXISTS events (
  event_id TEXT PRIMARY KEY,
  current_version INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('active','cancelled','completed')),
  created_at_utc TEXT NOT NULL,
  updated_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event_versions (
  event_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  title TEXT NOT NULL,
  start_at_local_iso TEXT NOT NULL,
  end_at_local_iso TEXT NULL,
  all_day INTEGER NOT NULL DEFAULT 0,
  event_timezone TEXT NOT NULL,
  participants_json TEXT NOT NULL,
  audience_json TEXT NOT NULL,
  reminder_offset_minutes INTEGER NOT NULL,
  source_message_ref TEXT NOT NULL,
  intent_hash TEXT NOT NULL,
  normalized_fields_hash TEXT NOT NULL,
  created_at_utc TEXT NOT NULL,
  PRIMARY KEY (event_id,version),
  FOREIGN KEY (event_id) REFERENCES events(event_id)
);

CREATE TABLE IF NOT EXISTS delivery_targets (
  target_id TEXT PRIMARY KEY,
  person_id TEXT NOT NULL,
  channel TEXT NOT NULL,
  target_ref TEXT NOT NULL,
  timezone TEXT NULL,
  quiet_hours_start INTEGER NOT NULL DEFAULT 23,
  quiet_hours_end INTEGER NOT NULL DEFAULT 7,
  is_active INTEGER NOT NULL DEFAULT 1,
  updated_at_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_delivery_targets_person_id ON delivery_targets(person_id);
CREATE INDEX IF NOT EXISTS idx_delivery_targets_channel_target_ref ON delivery_targets(channel, target_ref);

CREATE TABLE IF NOT EXISTS reminders (
  reminder_id TEXT PRIMARY KEY,
  dedupe_key TEXT NOT NULL UNIQUE,
  event_id TEXT NOT NULL,
  event_version INTEGER NOT NULL,
  recipient_target_id TEXT NOT NULL,
  offset_minutes INTEGER NOT NULL,
  trigger_at_utc TEXT NOT NULL,
  next_attempt_at_utc TEXT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL,
  recipient_timezone_snapshot TEXT NOT NULL,
  tz_source TEXT NOT NULL,
  last_error_code TEXT NULL,
  created_at_utc TEXT NOT NULL,
  updated_at_utc TEXT NOT NULL,
  FOREIGN KEY (event_id,event_version) REFERENCES event_versions(event_id,version),
  FOREIGN KEY (recipient_target_id) REFERENCES delivery_targets(target_id),
  FOREIGN KEY (status) REFERENCES enum_reminder_status(status),
  UNIQUE (event_id,event_version,offset_minutes,recipient_target_id)
);
CREATE INDEX IF NOT EXISTS idx_reminders_trigger_at_utc_reminder_id ON reminders(trigger_at_utc, reminder_id);

CREATE TABLE IF NOT EXISTS delivery_attempts (
  attempt_id TEXT PRIMARY KEY,
  reminder_id TEXT NOT NULL,
  attempt_index INTEGER NOT NULL,
  attempted_at_utc TEXT NOT NULL,
  status TEXT NOT NULL,
  reason_code TEXT NOT NULL,
  provider_ref TEXT NULL,
  FOREIGN KEY (reminder_id) REFERENCES reminders(reminder_id),
  FOREIGN KEY (status) REFERENCES enum_attempt_status(status),
  FOREIGN KEY (reason_code) REFERENCES enum_reason_codes(code),
  UNIQUE (reminder_id,attempt_index)
);

CREATE TABLE IF NOT EXISTS message_receipts (
  channel TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  message_id TEXT NOT NULL,
  correlation_id TEXT NOT NULL,
  intent_hash TEXT NOT NULL,
  result_json TEXT NOT NULL,
  created_at_utc TEXT NOT NULL,
  PRIMARY KEY (channel,conversation_id,message_id)
);
CREATE INDEX IF NOT EXISTS idx_message_receipts_intent_hash_created_at_utc ON message_receipts(intent_hash,created_at_utc);

CREATE TABLE IF NOT EXISTS audit_log (
  audit_index INTEGER PRIMARY KEY AUTOINCREMENT,
  ts_utc TEXT NOT NULL,
  trace_id TEXT NOT NULL,
  causation_id TEXT NOT NULL,
  correlation_id TEXT NOT NULL,
  message_id TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  stage TEXT NOT NULL,
  reason_code TEXT NOT NULL,
  payload_schema_version INTEGER NOT NULL,
  payload_json TEXT NOT NULL,
  FOREIGN KEY (stage) REFERENCES enum_audit_stages(stage),
  FOREIGN KEY (reason_code) REFERENCES enum_reason_codes(code)
);

CREATE TABLE IF NOT EXISTS daily_overview_policy (
  policy_id TEXT PRIMARY KEY,
  recipient_scope TEXT NOT NULL,
  send_time_local TEXT NOT NULL,
  timezone TEXT NOT NULL,
  include_completed INTEGER NOT NULL DEFAULT 0,
  updated_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS system_state (
  key TEXT PRIMARY KEY,
  value_type TEXT NOT NULL CHECK (value_type IN ('int','string','bool','enum','json')),
  value TEXT NOT NULL,
  updated_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS system_state_policy (
  key TEXT PRIMARY KEY,
  required INTEGER NOT NULL CHECK (required IN (0,1)),
  value_type TEXT NOT NULL,
  allowed_values_json TEXT NULL,
  min_int INTEGER NULL,
  max_int INTEGER NULL
);

INSERT OR REPLACE INTO system_state_policy(key, required, value_type, allowed_values_json, min_int, max_int) VALUES
('runtime_mode', 1, 'enum', '["normal", "capture_only"]', NULL, NULL),
('idempotency_window_hours', 1, 'int', NULL, 0, NULL),
('max_retry_attempts', 1, 'int', NULL, 0, NULL);

CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY,
  checksum TEXT NOT NULL,
  applied_at_utc TEXT NOT NULL,
  dirty INTEGER NOT NULL DEFAULT 0
);
