-- 0006_runs.sql
-- Runs, and the decision record.
--
-- `run_candidate` is where the answer to "why did ATOM do that in March" lives.
-- It is a table, not a log line, because a decision must be queryable and must
-- survive log archival (docs/07-logging/LOGGING-SPEC.md).

-- D-172: a batch groups the runs created by one "execute all universes" click.
-- Selecting a single universe simply creates a batch of one.
CREATE TABLE atom.run_batch (
    run_batch_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    triggered_by text NOT NULL,
    triggered_at timestamptz NOT NULL DEFAULT now(),
    trade_date   date NOT NULL
);

CREATE TABLE atom.run (
    run_id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_batch_id       bigint REFERENCES atom.run_batch,
    trading_account_id bigint NOT NULL REFERENCES atom.trading_account,
    universe_id        bigint NOT NULL REFERENCES atom.universe,
    snapshot_id        bigint REFERENCES atom.universe_snapshot,
    run_type           text NOT NULL,   -- EXECUTE | UNIVERSE_JOB | HARVEST | AVERAGE
    execution_mode     text NOT NULL,   -- copied from the account, frozen at run start
    trade_date         date NOT NULL,
    status             text NOT NULL,   -- QUEUED | EXECUTING | COMPLETED | FAILED   (D-057f)
    config_snapshot    jsonb NOT NULL,  -- fully resolved config, frozen (D-061)
    started_at         timestamptz NOT NULL DEFAULT now(),
    finished_at        timestamptz,
    CONSTRAINT run_status_ck CHECK (status IN ('QUEUED','EXECUTING','COMPLETED','FAILED')),
    CONSTRAINT run_type_ck
        CHECK (run_type IN ('EXECUTE','UNIVERSE_JOB','HARVEST','AVERAGE')),
    CONSTRAINT run_mode_ck CHECK (execution_mode IN ('LIVE','DRY')),
    CONSTRAINT run_finished_after_started_ck
        CHECK (finished_at IS NULL OR finished_at >= started_at)
);

-- Invariant 3: one execute run per account / universe / day (D-057e).
-- A FAILED run does not consume the day's slot, so a failure can be retried.
CREATE UNIQUE INDEX run_one_execute_per_day_uk
    ON atom.run (trading_account_id, universe_id, trade_date)
    WHERE run_type = 'EXECUTE' AND status <> 'FAILED';

COMMENT ON COLUMN atom.run.config_snapshot IS
    'D-061: a deliberate denormalisation of account_config. The config will change; a six-month-'
    'old decision must still be explicable, so the resolved config is frozen here at run start.';
COMMENT ON COLUMN atom.run.execution_mode IS
    'D-041: copied from the account and frozen. A run cannot change mode half way through, and a '
    'DRY run can never be mistaken for a LIVE one after the account is flipped.';

-- ---------------------------------------------------------------------------
-- run_candidate — one row per instrument considered, decided or not (D-052)
-- ---------------------------------------------------------------------------
CREATE TABLE atom.run_candidate (
    run_candidate_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id          bigint NOT NULL REFERENCES atom.run ON DELETE CASCADE,
    instrument_id   bigint NOT NULL REFERENCES atom.instrument,
    category        text NOT NULL,
    rank            integer NOT NULL,
    mean_price      numeric(18,4) NOT NULL,
    median_price    numeric(18,4),
    ltp             numeric(18,4) NOT NULL,      -- snapshotted (D-052)
    deviation_pct   numeric(18,4) NOT NULL,      -- percentage, 4dp (D-026/D-149)
    nav             numeric(18,4),
    nav_premium_pct numeric(18,4),
    holdings_status text,                        -- HELD | NOT_HELD | EXCLUDED
    gate_failed     text,                        -- NULL if it passed every gate
    decision        text NOT NULL,               -- BOUGHT | SOLD | SKIPPED | NOT_CONSIDERED
    decision_reason text NOT NULL,
    CONSTRAINT run_candidate_uk UNIQUE (run_id, instrument_id),
    CONSTRAINT run_candidate_decision_ck
        CHECK (decision IN ('BOUGHT','SOLD','SKIPPED','NOT_CONSIDERED')),
    CONSTRAINT run_candidate_holdings_status_ck
        CHECK (holdings_status IS NULL OR holdings_status IN ('HELD','NOT_HELD','EXCLUDED')),
    -- A candidate that failed a gate cannot also have been acted on.
    CONSTRAINT run_candidate_gate_ck
        CHECK (gate_failed IS NULL OR decision IN ('SKIPPED','NOT_CONSIDERED'))
);

COMMENT ON COLUMN atom.run_candidate.deviation_pct IS
    'D-149: PERCENTAGE deviation, four decimal places — never a rupee amount. Prices inside one '
    'bucket differ by up to 83x, so a rupee threshold would mean entirely different things for '
    'two instruments in the same category.';
COMMENT ON COLUMN atom.run_candidate.ltp IS
    'D-052: snapshotted at decision time. Re-reading the price later would change the answer to '
    '"why did it decide this", which defeats the purpose of the record.';
COMMENT ON COLUMN atom.run_candidate.decision_reason IS
    'NOT NULL with no default. Every decision, including NOT_CONSIDERED, states its reason in '
    'words. "No reason recorded" is not a permitted state.';
