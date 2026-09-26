-- 0017_config_gaps.sql
-- Three gaps found while writing the config resolver — each one a place where the
-- schema could not hold something a decision already requires.

-- ---------------------------------------------------------------------------
-- 1. Two keys the run lifecycle names and the catalogue never had
-- ---------------------------------------------------------------------------
-- RUN-LIFECYCLE.md 7.1 and D-059b compute buy quantity as
--     floor(trade_amount x budget_buffer_pct / price)
-- and call the buffer "configurable" -- but 0016 seeded no such key, so the
-- engine would have had to hardcode it, which D-037 forbids.
--
-- EXECUTION-MODES-AND-DRY-RUN.md 4 describes a buy as "limit at LTP + buffer"
-- without ever defining the buffer. It is a real choice -- zero never pays up
-- and may not fill; more fills more often and pays for it -- so it is a key the
-- operator sets, not a number chosen here.
INSERT INTO atom.config_key (key_name, scope, value_type, is_required, suggested_value, description)
VALUES
('budget_buffer_pct', 'ACCOUNT', 'NUMERIC', true, '99.0000',
 'Share of trade_amount_inr actually spent on units, so that brokerage and charges fit inside the budget (D-059b). Rs 20,000 at 99% on a Rs 2,440 unit is floor(19,800 / 2,440) = 8 units.'),
('buy_limit_premium_pct', 'ACCOUNT', 'NUMERIC', true, '0.2500',
 'How far above the last traded price a buy limit is set, rounded UP to the tick. Zero never pays more than LTP and may not fill on a rising print; a positive premium fills more often and costs up to that much. Quantity is computed against this limit price, never against LTP, so the order can never exceed its budget.')
ON CONFLICT (key_name) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. GLOBAL keys had nowhere to live
-- ---------------------------------------------------------------------------
-- 0016 seeded six GLOBAL keys -- kill_switch among them -- but account_config
-- requires a trading_account_id AND a universe_id. A global kill switch stored
-- per account and universe is not a kill switch: it is N switches that can
-- disagree, and the one that matters is the one somebody forgot.
CREATE TABLE atom.global_config (
    config_key_id bigint PRIMARY KEY REFERENCES atom.config_key,
    value_text    text,             -- NULL with is_configured = true is an explicit NULL (D-039)
    is_configured boolean NOT NULL DEFAULT true,
    version       integer NOT NULL DEFAULT 1,
    updated_by    text NOT NULL,
    updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE atom.global_config_history (
    global_config_history_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    config_key_id bigint NOT NULL REFERENCES atom.config_key,
    old_value  text,
    new_value  text,
    changed_by text NOT NULL,
    changed_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX global_config_history_key_idx
    ON atom.global_config_history (config_key_id, changed_at DESC);

COMMENT ON TABLE atom.global_config IS
    'Values for config keys whose scope is GLOBAL. One row per key, so there is exactly one '
    'kill switch rather than one per account and universe.';

-- A GLOBAL key must never be written into account_config, and vice versa; the
-- resolver enforces that, and this trigger makes the database agree.
CREATE FUNCTION atom.global_config_scope_ck() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
    IF (SELECT scope FROM atom.config_key WHERE config_key_id = NEW.config_key_id) <> 'GLOBAL' THEN
        RAISE EXCEPTION 'global_config_scope_ck: config key % is not GLOBAL', NEW.config_key_id
            USING ERRCODE = 'check_violation', CONSTRAINT = 'global_config_scope_ck';
    END IF;
    RETURN NEW;
END
$fn$;

CREATE TRIGGER global_config_scope_ck
    BEFORE INSERT OR UPDATE ON atom.global_config
    FOR EACH ROW EXECUTE FUNCTION atom.global_config_scope_ck();

CREATE FUNCTION atom.account_config_scope_ck() RETURNS trigger
LANGUAGE plpgsql AS $fn$
DECLARE
    key_scope text;
BEGIN
    SELECT scope INTO key_scope FROM atom.config_key WHERE config_key_id = NEW.config_key_id;
    IF key_scope = 'GLOBAL' THEN
        RAISE EXCEPTION 'account_config_scope_ck: config key % is GLOBAL and belongs in global_config', NEW.config_key_id
            USING ERRCODE = 'check_violation', CONSTRAINT = 'account_config_scope_ck';
    END IF;
    IF key_scope = 'ACCOUNT' AND NEW.category_code IS NOT NULL THEN
        RAISE EXCEPTION 'account_config_scope_ck: config key % is account-level and takes no category', NEW.config_key_id
            USING ERRCODE = 'check_violation', CONSTRAINT = 'account_config_scope_ck';
    END IF;
    IF key_scope = 'ACCOUNT_CATEGORY' AND NEW.category_code IS NULL THEN
        RAISE EXCEPTION 'account_config_scope_ck: config key % is per category and needs one', NEW.config_key_id
            USING ERRCODE = 'check_violation', CONSTRAINT = 'account_config_scope_ck';
    END IF;
    RETURN NEW;
END
$fn$;

CREATE TRIGGER account_config_scope_ck
    BEFORE INSERT OR UPDATE ON atom.account_config
    FOR EACH ROW EXECUTE FUNCTION atom.account_config_scope_ck();

-- ---------------------------------------------------------------------------
-- 3. Duplicate account-level values were storable
-- ---------------------------------------------------------------------------
-- account_config_uk is UNIQUE (account, universe, key, category_code), and in
-- Postgres NULLs are distinct under UNIQUE. Every account-level key has a NULL
-- category_code -- so two rows for the SAME account-level key could coexist, and
-- which one the engine read would depend on row order. 0004's comment described
-- the NULL behaviour as intended; it was intended for category-vs-account, and it
-- also let account-vs-account through.
--
-- NULLS NOT DISTINCT (Postgres 15+) closes it without touching the category case.
CREATE UNIQUE INDEX account_config_one_value_uk
    ON atom.account_config (trading_account_id, universe_id, config_key_id, category_code)
    NULLS NOT DISTINCT;

-- ---------------------------------------------------------------------------
-- 4. Settlement was only idempotent by convention
-- ---------------------------------------------------------------------------
-- RUN-LIFECYCLE.md 9.2: "Settlement re-runs safely. Fills key on
-- broker_trade_id." Nothing made that true. A settle re-run after a crash would
-- have inserted every fill again -- and since lots are one-per-fill (D-166), it
-- would have doubled the position, and then tried to sell stock that does not
-- exist. A dry-run fill has no broker trade id, hence the partial index.
CREATE UNIQUE INDEX order_fill_trade_uk
    ON atom.order_fill (order_request_id, broker_trade_id)
    WHERE broker_trade_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Grants and RLS for the two new tables (0014's loop ran once; it does not
-- reach tables created after it, which is exactly what the README warns about)
-- ---------------------------------------------------------------------------
ALTER TABLE atom.global_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE atom.global_config_history ENABLE ROW LEVEL SECURITY;
CREATE POLICY atom_engine_all ON atom.global_config
    FOR ALL TO atom_engine USING (true) WITH CHECK (true);
CREATE POLICY atom_engine_all ON atom.global_config_history
    FOR ALL TO atom_engine USING (true) WITH CHECK (true);

GRANT SELECT, INSERT, UPDATE ON atom.global_config TO atom_engine;
GRANT SELECT, INSERT ON atom.global_config_history TO atom_engine;  -- append-only
REVOKE UPDATE ON atom.global_config_history FROM atom_engine;
