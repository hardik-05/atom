-- 0020_many_plans_one_release.sql
-- Any number of EXECUTE plans per account / universe / day, but only one may ever be RELEASED
-- (orders sent). A plan that failed or was blocked no longer uses up the day.
--
-- `released_at` is stamped, in the same transaction that checks for an earlier release, when a
-- run's orders start to go out. It is never cleared, even if the release then halts: a run that
-- reached the broker is settled, not released a second time.

ALTER TABLE atom.run ADD COLUMN IF NOT EXISTS released_at timestamptz;

-- Runs that already sent orders count as released.
UPDATE atom.run r SET released_at = COALESCE(r.finished_at, r.started_at)
WHERE r.run_type = 'EXECUTE' AND r.released_at IS NULL
  AND EXISTS (SELECT 1 FROM atom.order_request o
              WHERE o.run_id = r.run_id AND o.status <> 'INTENT' AND o.status <> 'CANCELLED');

DROP INDEX IF EXISTS atom.run_one_execute_per_day_uk;

CREATE UNIQUE INDEX IF NOT EXISTS run_one_release_per_day_uk
    ON atom.run (trading_account_id, universe_id, trade_date)
    WHERE run_type = 'EXECUTE' AND released_at IS NOT NULL;
