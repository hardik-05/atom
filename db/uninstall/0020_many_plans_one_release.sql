-- Undo 0020: back to one non-failed EXECUTE run per account / universe / day.
-- Fails if several such runs exist today; discard the extra plans first.
DROP INDEX IF EXISTS atom.run_one_release_per_day_uk;
CREATE UNIQUE INDEX IF NOT EXISTS run_one_execute_per_day_uk
    ON atom.run (trading_account_id, universe_id, trade_date)
    WHERE run_type = 'EXECUTE' AND status <> 'FAILED';
ALTER TABLE atom.run DROP COLUMN IF EXISTS released_at;
