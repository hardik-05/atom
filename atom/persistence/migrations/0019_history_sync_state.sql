-- 0019_history_sync_state.sql
-- What the history sync has already ASKED the broker for, per instrument.
--
-- Coverage alone (min/max of price_daily) cannot tell "we never fetched this" from
-- "the broker has nothing there": an ETF listed last month has no bars before its
-- listing date, so every sync asked for the missing head again. And a sync run on
-- a Sunday asked for Saturday-Sunday each time, to be told nothing.
--
--   requested_from   the earliest date a successful fetch has covered
--   synced_through   the latest date a successful fetch has covered
--
-- A sync fetches only [requested_from - wanted, requested_from) at the head and
-- (max(last bar, synced_through), yesterday] at the tail. Nothing here is a price;
-- losing the table costs one full re-fetch and nothing else.
CREATE TABLE atom.history_sync_state (
    instrument_id  bigint NOT NULL REFERENCES atom.instrument,
    source         text   NOT NULL,
    requested_from date   NOT NULL,
    synced_through date   NOT NULL,
    updated_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, source),
    CONSTRAINT history_sync_state_ck CHECK (requested_from <= synced_through)
);

-- Baseline of 0014, which only covered the tables that existed then.
ALTER TABLE atom.history_sync_state ENABLE ROW LEVEL SECURITY;
CREATE POLICY atom_engine_all ON atom.history_sync_state FOR ALL TO atom_engine
    USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, UPDATE ON atom.history_sync_state TO atom_engine;
