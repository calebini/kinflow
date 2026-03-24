-- Packet2 schema reconciliation (post eb5d1fc8 baseline)
-- Forward-only migration.

PRAGMA foreign_keys = OFF;

-- Rebuild enum_reason_codes with canonical class taxonomy.
CREATE TABLE IF NOT EXISTS enum_reason_codes_v2 (
  code TEXT PRIMARY KEY,
  class TEXT NOT NULL CHECK (class IN ('success','mutation','blocked','runtime','transient','permanent','suppressed')),
  active INTEGER NOT NULL CHECK (active IN (0,1)),
  version_tag TEXT NOT NULL
);

INSERT OR REPLACE INTO enum_reason_codes_v2(code, class, active, version_tag) VALUES
('DELIVERED_SUCCESS','success',1,'v0.2.6'),
('RESOLVER_EXPLICIT','mutation',1,'v0.2.6'),
('RESOLVER_MATCHED','mutation',1,'v0.2.6'),
('RESOLVER_AMBIGUOUS','blocked',1,'v0.2.6'),
('RESOLVER_NO_MATCH','mutation',1,'v0.2.6'),
('TZ_EXPLICIT','mutation',1,'v0.2.6'),
('TZ_HOUSEHOLD_DEFAULT','mutation',1,'v0.2.6'),
('TZ_FALLBACK_USED','runtime',1,'v0.2.6'),
('TZ_MISSING','blocked',1,'v0.2.6'),
('FAILED_PROVIDER_TRANSIENT','transient',1,'v0.2.6'),
('FAILED_PROVIDER_PERMANENT','permanent',1,'v0.2.6'),
('FAILED_CONFIG_INVALID_TARGET','blocked',1,'v0.2.6'),
('FAILED_CAPABILITY_UNSUPPORTED','blocked',1,'v0.2.6'),
('FAILED_RETRY_EXHAUSTED','permanent',1,'v0.2.6'),
('SUPPRESSED_QUIET_HOURS','suppressed',1,'v0.2.6'),
('UPDATED_REGENERATED','mutation',1,'v0.2.6'),
('CANCEL_INVALIDATED','mutation',1,'v0.2.6'),
('BLOCKED_CONFIRMATION_REQUIRED','blocked',1,'v0.2.6'),
('VERSION_CONFLICT_RETRY','transient',1,'v0.2.6'),
('RECOVERY_RECONCILED','runtime',1,'v0.2.6'),
('FAIRNESS_BOUND_EXCEEDED','runtime',1,'v0.2.6'),
('DB_RECONNECT_EXHAUSTED','runtime',1,'v0.2.6'),
('STARTUP_VALIDATION_FAILED','runtime',1,'v0.2.6'),
('SHUTDOWN_GRACE_EXCEEDED','runtime',1,'v0.2.6'),
('CAPTURE_ONLY_BLOCKED','blocked',1,'v0.2.6');

-- Normalize historical DELIVERED reason codes before swapping table.
UPDATE audit_log SET reason_code = 'DELIVERED_SUCCESS' WHERE reason_code = 'DELIVERED';
UPDATE delivery_attempts SET reason_code = 'DELIVERED_SUCCESS' WHERE reason_code = 'DELIVERED';
UPDATE enum_reason_codes SET code = 'DELIVERED_SUCCESS' WHERE code = 'DELIVERED';

DROP TABLE enum_reason_codes;
ALTER TABLE enum_reason_codes_v2 RENAME TO enum_reason_codes;

-- Ensure blocked attempt status exists.
INSERT OR REPLACE INTO enum_attempt_status(status, version_tag) VALUES ('blocked','v0.2.6');

-- Rebuild delivery_attempts with canonical ledger fields.
CREATE TABLE IF NOT EXISTS delivery_attempts_v2 (
  attempt_id TEXT PRIMARY KEY,
  reminder_id TEXT NOT NULL,
  attempt_index INTEGER NOT NULL,
  attempted_at_utc TEXT NOT NULL,
  status TEXT NOT NULL,
  reason_code TEXT NOT NULL,
  provider_ref TEXT NULL,
  provider_status_code TEXT NULL,
  provider_error_text TEXT NULL,
  provider_accept_only INTEGER NOT NULL DEFAULT 0,
  delivery_confidence TEXT NOT NULL DEFAULT 'none' CHECK (delivery_confidence IN ('provider_confirmed','provider_accepted','none')),
  result_at_utc TEXT NOT NULL,
  trace_id TEXT NOT NULL,
  causation_id TEXT NOT NULL,
  source_adapter_attempt_id TEXT NULL,
  FOREIGN KEY (reminder_id) REFERENCES reminders(reminder_id),
  FOREIGN KEY (status) REFERENCES enum_attempt_status(status),
  FOREIGN KEY (reason_code) REFERENCES enum_reason_codes(code),
  UNIQUE (reminder_id,attempt_index)
);

INSERT INTO delivery_attempts_v2(
  attempt_id, reminder_id, attempt_index, attempted_at_utc, status, reason_code,
  provider_ref, provider_status_code, provider_error_text, provider_accept_only,
  delivery_confidence, result_at_utc, trace_id, causation_id, source_adapter_attempt_id
)
SELECT
  attempt_id,
  reminder_id,
  attempt_index,
  attempted_at_utc,
  status,
  reason_code,
  provider_ref,
  NULL,
  NULL,
  0,
  CASE WHEN reason_code = 'DELIVERED_SUCCESS' THEN 'provider_confirmed' ELSE 'none' END,
  attempted_at_utc,
  'migration:0002',
  reminder_id,
  NULL
FROM delivery_attempts;

DROP TABLE delivery_attempts;
ALTER TABLE delivery_attempts_v2 RENAME TO delivery_attempts;

-- Required system_state policy key.
INSERT OR REPLACE INTO system_state_policy(key, required, value_type, allowed_values_json, min_int, max_int)
VALUES ('adapter_dedupe_window_ms', 1, 'int', NULL, 0, NULL);

INSERT OR IGNORE INTO system_state(key, value_type, value, updated_at_utc)
VALUES ('adapter_dedupe_window_ms', 'int', '0', '1970-01-01T00:00:00+00:00');

PRAGMA foreign_keys = ON;
