-- KINFLOW Phase 5.5 observability minimum query pack
-- Lookback window is parameterized via :lookback_iso_utc in calling script.

-- 1) duplicate/replay-send anomaly signal
SELECT
  COUNT(*) AS replay_anomaly_count
FROM delivery_attempts
WHERE attempted_at_utc >= :lookback_iso_utc
  AND source_adapter_attempt_id IS NOT NULL
  AND source_adapter_attempt_id <> attempt_id;

-- 2) retry exhaustion signal
SELECT
  COUNT(*) AS retry_exhaustion_count
FROM delivery_attempts
WHERE attempted_at_utc >= :lookback_iso_utc
  AND reason_code = 'FAILED_RETRY_EXHAUSTED';

-- 3) blocked outcomes signal (total)
SELECT
  COUNT(*) AS blocked_outcomes_count
FROM delivery_attempts
WHERE attempted_at_utc >= :lookback_iso_utc
  AND status = 'blocked';

-- 3b) blocked outcomes reason-code breakdown
SELECT
  reason_code,
  COUNT(*) AS n
FROM delivery_attempts
WHERE attempted_at_utc >= :lookback_iso_utc
  AND status = 'blocked'
GROUP BY reason_code
ORDER BY n DESC, reason_code ASC;
