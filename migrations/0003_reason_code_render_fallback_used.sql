-- Add renderer fallback reason code to canonical enum registry.
INSERT OR IGNORE INTO enum_reason_codes(code, class, active, version_tag)
VALUES ('RENDER_FALLBACK_USED','runtime',1,'v0.5.3');
