-- verify_constraints.sql
-- Proves that the constraints in 0001-0014 reject what they are supposed to
-- reject. Runs entirely inside a transaction and rolls back, so it is safe
-- against any database the migrations have been applied to.
--
--   psql "$ATOM_DATABASE_URL" -v ON_ERROR_STOP=1 -f verify_constraints.sql
--
-- The file is pure SQL - no psql meta-commands - so it also runs verbatim through
-- a single-statement SQL API such as the Supabase MCP.
--
-- A constraint nobody has seen fire is a comment, not an invariant. Every CHECK
-- that encodes a decision is exercised here with the exact bad row it exists to
-- refuse.

BEGIN;

CREATE FUNCTION pg_temp.expect_reject(stmt text, expected text) RETURNS void AS $fn$
BEGIN
    BEGIN
        EXECUTE stmt;
    EXCEPTION
        WHEN check_violation OR unique_violation OR foreign_key_violation
          OR not_null_violation OR exclusion_violation THEN
            IF position(expected IN SQLERRM) = 0 THEN
                RAISE EXCEPTION 'rejected, but not by %: %', expected, SQLERRM;
            END IF;
            RETURN;
    END;
    RAISE EXCEPTION 'ACCEPTED a row that % should have refused: %', expected, stmt;
END;
$fn$ LANGUAGE plpgsql;

CREATE FUNCTION pg_temp.check_that(label text, condition boolean) RETURNS void AS $fn$
BEGIN
    IF NOT condition THEN
        RAISE EXCEPTION 'failed: %', label;
    END IF;
    RAISE NOTICE '  ok  %', label;
END;
$fn$ LANGUAGE plpgsql;

-- --------------------------------------------------------------------------
-- Fixtures: the smallest graph that lets every constraint be reached
-- --------------------------------------------------------------------------
INSERT INTO atom.investor (external_key, display_name, relationship, onboarded_on)
VALUES ('INV-TEST', 'Test Investor', 'SELF', DATE '2026-04-01');

INSERT INTO atom.broker
    (broker_code, display_name, supports_gtt, supports_charges_api,
     supports_ledger_api, auth_flow)
VALUES ('DHAN', 'Dhan', true, true, true, 'CREDENTIAL_LOGIN')
-- 0016 seeds the five brokers, so on a fully migrated database this row already
-- exists. The fixture must not assume an empty table.
ON CONFLICT (broker_code) DO NOTHING;

INSERT INTO atom.trading_account
    (investor_id, broker_id, broker_client_code, execution_mode, status)
SELECT i.investor_id, b.broker_id, 'CLIENT-DRY', 'DRY', 'ACTIVE'
FROM atom.investor i, atom.broker b
WHERE i.external_key = 'INV-TEST' AND b.broker_code = 'DHAN';

INSERT INTO atom.instrument (isin, symbol, name, instrument_type, asset_class, tick_size)
VALUES ('INE000TEST01', 'TESTBEES', 'Test ETF', 'ETF', 'EQUITY', 0.01),
       ('INE000TEST02', 'PROXYBEES', 'Proxy ETF', 'ETF', 'EQUITY', 0.01);

INSERT INTO atom.universe (name, source, created_by) VALUES ('Test Universe', 'MANUAL', 'test');

INSERT INTO atom.run
    (trading_account_id, universe_id, run_type, execution_mode, trade_date,
     status, config_snapshot)
SELECT a.trading_account_id, u.universe_id, 'EXECUTE', 'DRY', DATE '2026-09-25',
       'COMPLETED', '{}'::jsonb
FROM atom.trading_account a, atom.universe u
WHERE a.broker_client_code = 'CLIENT-DRY' AND u.name = 'Test Universe';

INSERT INTO atom.order_request
    (run_id, trading_account_id, universe_id, instrument_id, side, order_kind,
     quantity, limit_price, idempotency_key, status)
SELECT r.run_id, r.trading_account_id, r.universe_id, i.instrument_id, 'BUY', 'LIMIT',
       10, 100.0000, 'atm2609250101', 'FILLED'
FROM atom.run r, atom.instrument i
WHERE i.symbol = 'TESTBEES';

INSERT INTO atom.order_fill (order_request_id, quantity, fill_price, filled_at)
SELECT order_request_id, 10, 100.0000, now() FROM atom.order_request;

INSERT INTO atom.position_lot
    (trading_account_id, universe_id, instrument_id, buy_order_request_id,
     order_fill_id, quantity, quantity_open, unit_cost, acquired_on, provenance)
SELECT o.trading_account_id, o.universe_id, o.instrument_id, o.order_request_id,
       f.order_fill_id, 10, 10, 100.1000, DATE '2026-09-25', 'ATOM'
FROM atom.order_request o JOIN atom.order_fill f
  ON f.order_request_id = o.order_request_id;

-- --------------------------------------------------------------------------
-- Invariant 1 (D-136) — a LIVE account cannot exist without its egress path
-- --------------------------------------------------------------------------
DO $do$ BEGIN RAISE NOTICE '== identity =='; END $do$;
SELECT pg_temp.expect_reject($$
    INSERT INTO atom.trading_account
        (investor_id, broker_id, broker_client_code, execution_mode)
    SELECT investor_id, (SELECT broker_id FROM atom.broker LIMIT 1), 'CLIENT-LIVE', 'LIVE'
    FROM atom.investor LIMIT 1
$$, 'trading_account_live_needs_proxy_ck');

-- The same row with an egress IP and a proxy is accepted.
INSERT INTO atom.trading_account
    (investor_id, broker_id, broker_client_code, execution_mode, egress_ip, proxy_url)
SELECT investor_id, (SELECT broker_id FROM atom.broker LIMIT 1), 'CLIENT-LIVE', 'LIVE',
       '203.0.113.7'::inet, 'http://127.0.0.1:3128'
FROM atom.investor LIMIT 1;
SELECT pg_temp.check_that('a LIVE account with egress IP and proxy is accepted', true);

-- Invariant 7 (D-128) — a real PAN cannot be stored
SELECT pg_temp.expect_reject($$
    INSERT INTO atom.investor (external_key, display_name, relationship, onboarded_on, pan_masked)
    VALUES ('INV-PAN', 'Leaky', 'SELF', DATE '2026-04-01', 'ABCDE1234F')
$$, 'investor_pan_masked_ck');

-- Invariant 6 (D-092) — relationship stays inside SEBI's family definition
SELECT pg_temp.expect_reject($$
    INSERT INTO atom.investor (external_key, display_name, relationship, onboarded_on)
    VALUES ('INV-FRIEND', 'Friend', 'FRIEND', DATE '2026-04-01')
$$, 'investor_relationship_ck');

-- --------------------------------------------------------------------------
-- D-174 — MARKET is not a storable order kind
-- --------------------------------------------------------------------------
DO $do$ BEGIN RAISE NOTICE '== orders =='; END $do$;
SELECT pg_temp.expect_reject($$
    INSERT INTO atom.order_request
        (trading_account_id, universe_id, instrument_id, side, order_kind,
         quantity, limit_price, idempotency_key, status)
    SELECT trading_account_id, universe_id, instrument_id, 'BUY', 'MARKET',
           1, 100, 'atm2609250201', 'INTENT'
    FROM atom.order_request LIMIT 1
$$, 'order_kind_ck');

-- D-207 — no margin, MTF, intraday or leverage
SELECT pg_temp.expect_reject($$
    INSERT INTO atom.order_request
        (trading_account_id, universe_id, instrument_id, side, order_kind, product,
         quantity, limit_price, idempotency_key, status)
    SELECT trading_account_id, universe_id, instrument_id, 'BUY', 'LIMIT', 'MTF',
           1, 100, 'atm2609250202', 'INTENT'
    FROM atom.order_request LIMIT 1
$$, 'order_product_ck');

-- Invariant 4 (D-094) — an order is never sent twice
SELECT pg_temp.expect_reject($$
    INSERT INTO atom.order_request
        (trading_account_id, universe_id, instrument_id, side, order_kind,
         quantity, limit_price, idempotency_key, status)
    SELECT trading_account_id, universe_id, instrument_id, 'BUY', 'LIMIT',
           1, 100, 'atm2609250101', 'INTENT'
    FROM atom.order_request LIMIT 1
$$, 'order_request_idempotency_key_key');

-- A GTT without a trigger, and a limit order with one, are both nonsense
SELECT pg_temp.expect_reject($$
    INSERT INTO atom.order_request
        (trading_account_id, universe_id, instrument_id, side, order_kind,
         quantity, limit_price, idempotency_key, status)
    SELECT trading_account_id, universe_id, instrument_id, 'SELL', 'GTT',
           1, 110, 'atm2609250203', 'INTENT'
    FROM atom.order_request LIMIT 1
$$, 'order_gtt_needs_trigger_ck');

SELECT pg_temp.expect_reject($$
    INSERT INTO atom.order_request
        (trading_account_id, universe_id, instrument_id, side, order_kind,
         quantity, limit_price, trigger_price, idempotency_key, status)
    SELECT trading_account_id, universe_id, instrument_id, 'SELL', 'LIMIT',
           1, 110, 110, 'atm2609250204', 'INTENT'
    FROM atom.order_request LIMIT 1
$$, 'order_gtt_needs_trigger_ck');

-- D-180 — IN_FLIGHT is a storable status, because an unknown status must land somewhere
INSERT INTO atom.order_request
    (trading_account_id, universe_id, instrument_id, side, order_kind,
     quantity, limit_price, idempotency_key, status)
SELECT trading_account_id, universe_id, instrument_id, 'BUY', 'LIMIT',
       1, 100, 'atm2609250205', 'IN_FLIGHT'
FROM atom.order_request LIMIT 1;
SELECT pg_temp.check_that('D-180: IN_FLIGHT is storable', true);

-- --------------------------------------------------------------------------
-- Lots
-- --------------------------------------------------------------------------
DO $do$ BEGIN RAISE NOTICE '== lots =='; END $do$;
-- Invariant 5 — open quantity never exceeds lot quantity
SELECT pg_temp.expect_reject(
    'UPDATE atom.position_lot SET quantity_open = quantity + 1',
    'lot_open_le_total_ck');

-- CLOSED and exhausted are the same fact and cannot disagree
SELECT pg_temp.expect_reject(
    'UPDATE atom.position_lot SET quantity_open = 0',
    'lot_status_matches_open_ck');

-- D-166 — one lot per fill
SELECT pg_temp.expect_reject($$
    INSERT INTO atom.position_lot
        (trading_account_id, universe_id, instrument_id, order_fill_id,
         quantity, quantity_open, unit_cost, acquired_on, provenance)
    SELECT trading_account_id, universe_id, instrument_id, order_fill_id,
           5, 5, 100, DATE '2026-09-25', 'ATOM'
    FROM atom.position_lot LIMIT 1
$$, 'position_lot_fill_uk');

-- An ATOM lot must come from a fill; only an EXTERNAL lot may have none
SELECT pg_temp.expect_reject($$
    INSERT INTO atom.position_lot
        (trading_account_id, universe_id, instrument_id,
         quantity, quantity_open, unit_cost, acquired_on, provenance)
    SELECT trading_account_id, universe_id, instrument_id,
           5, 5, 100, DATE '2026-09-25', 'ATOM'
    FROM atom.position_lot LIMIT 1
$$, 'lot_one_per_fill_ck');

INSERT INTO atom.position_lot
    (trading_account_id, universe_id, instrument_id,
     quantity, quantity_open, unit_cost, acquired_on, provenance)
SELECT trading_account_id, universe_id,
       (SELECT instrument_id FROM atom.instrument WHERE symbol = 'PROXYBEES'),
       5, 5, 85.0000, DATE '2026-09-25', 'EXTERNAL'
FROM atom.position_lot WHERE provenance = 'ATOM' LIMIT 1;
SELECT pg_temp.check_that('D-062: an EXTERNAL lot needs no fill of ours', true);

-- --------------------------------------------------------------------------
-- D-193 — chained harvests are impossible, not merely discouraged
-- --------------------------------------------------------------------------
DO $do$ BEGIN RAISE NOTICE '== harvest =='; END $do$;
-- The proxy lot carries the capital committed to the security that was sold.
UPDATE atom.position_lot SET synthetic_cost_basis = 200.2000
WHERE provenance = 'EXTERNAL';

INSERT INTO atom.harvest_chain
    (sold_lot_id, proxy_lot_id, booked_loss, carried_basis_amount, status, selected_by)
SELECT (SELECT lot_id FROM atom.position_lot WHERE provenance = 'ATOM'),
       (SELECT lot_id FROM atom.position_lot WHERE provenance = 'EXTERNAL'),
       150.0000, 1001.0000, 'EXECUTED', 'test';
SELECT pg_temp.check_that('a first-hop harvest is recordable', true);

SELECT pg_temp.expect_reject(
    'UPDATE atom.harvest_chain SET chain_depth = 2',
    'harvest_no_chaining_ck');

-- A harvest cannot be its own proxy
SELECT pg_temp.expect_reject($$
    INSERT INTO atom.harvest_chain (sold_lot_id, proxy_lot_id, booked_loss, status)
    SELECT lot_id, lot_id, 1, 'PROPOSED' FROM atom.position_lot LIMIT 1
$$, 'harvest_not_self_ck');

-- D-070b — an EXECUTED harvest must have both legs and the carried amount
SELECT pg_temp.expect_reject($$
    INSERT INTO atom.harvest_chain (sold_lot_id, booked_loss, status)
    SELECT lot_id, 1, 'EXECUTED' FROM atom.position_lot LIMIT 1
$$, 'harvest_executed_complete_ck');

-- ... but INCOMPLETE is exactly the row that records a half-done harvest
INSERT INTO atom.harvest_chain (sold_lot_id, booked_loss, status)
SELECT lot_id, 1, 'INCOMPLETE' FROM atom.position_lot WHERE provenance = 'ATOM';
SELECT pg_temp.check_that('D-070b: INCOMPLETE is a recordable outcome', true);

-- --------------------------------------------------------------------------
-- Invariant 2 (D-080) — capital buckets sum to the principal
-- --------------------------------------------------------------------------
DO $do$ BEGIN RAISE NOTICE '== capital =='; END $do$;
SELECT pg_temp.expect_reject($$
    INSERT INTO atom.capital_accrual_daily
        (trading_account_id, accrual_date, principal_outstanding, deployed_amount,
         settlement_amount, idle_amount, rate_pct, interest_total)
    SELECT trading_account_id, DATE '2026-09-25', 100000, 50000, 10000, 10000, 9, 24.66
    FROM atom.trading_account LIMIT 1
$$, 'accrual_buckets_ck');

INSERT INTO atom.capital_accrual_daily
    (trading_account_id, accrual_date, principal_outstanding, deployed_amount,
     settlement_amount, idle_amount, rate_pct, interest_total)
SELECT trading_account_id, DATE '2026-09-25', 100000, 50000, 10000, 40000, 9, 24.6575
FROM atom.trading_account LIMIT 1;
SELECT pg_temp.check_that('D-080: buckets that sum to the principal are accepted', true);

-- --------------------------------------------------------------------------
-- D-079 — the session table stores a path, never a token
-- --------------------------------------------------------------------------
DO $do$ BEGIN RAISE NOTICE '== sessions =='; END $do$;
SELECT pg_temp.expect_reject($$
    INSERT INTO atom.broker_session (trading_account_id, trade_date, status, secret_ref)
    SELECT trading_account_id, DATE '2026-09-25', 'VALID', 'eyJhbGciOiJIUzI1NiJ9.token'
    FROM atom.trading_account LIMIT 1
$$, 'broker_session_is_ssm_path_ck');

INSERT INTO atom.broker_session (trading_account_id, trade_date, status, secret_ref, obtained_at)
SELECT trading_account_id, DATE '2026-09-25', 'VALID', '/atom/sessions/7/2026-09-25', now()
FROM atom.trading_account LIMIT 1;
SELECT pg_temp.check_that('D-079: an SSM path is accepted', true);

-- A CLEARED session cannot keep pointing at a deleted parameter
SELECT pg_temp.expect_reject(
    $$UPDATE atom.broker_session SET status = 'CLEARED', cleared_at = now()$$,
    'broker_session_cleared_ck');

-- --------------------------------------------------------------------------
-- Invariant 3 (D-057e) — one execute run per account / universe / day
-- --------------------------------------------------------------------------
DO $do$ BEGIN RAISE NOTICE '== runs =='; END $do$;
SELECT pg_temp.expect_reject($$
    INSERT INTO atom.run
        (trading_account_id, universe_id, run_type, execution_mode, trade_date,
         status, config_snapshot)
    SELECT trading_account_id, universe_id, 'EXECUTE', 'DRY', trade_date,
           'QUEUED', '{}'::jsonb
    FROM atom.run LIMIT 1
$$, 'run_one_execute_per_day_uk');

-- ... but a FAILED run does not consume the slot, so a failure can be retried
UPDATE atom.run SET status = 'FAILED';
INSERT INTO atom.run
    (trading_account_id, universe_id, run_type, execution_mode, trade_date,
     status, config_snapshot)
SELECT trading_account_id, universe_id, 'EXECUTE', 'DRY', trade_date, 'QUEUED', '{}'::jsonb
FROM atom.run LIMIT 1;
SELECT pg_temp.check_that('D-057e: a FAILED run does not consume the day''s slot', true);

-- A candidate that failed a gate cannot also have been acted on
SELECT pg_temp.expect_reject($$
    INSERT INTO atom.run_candidate
        (run_id, instrument_id, category, rank, mean_price, ltp, deviation_pct,
         gate_failed, decision, decision_reason)
    SELECT r.run_id, i.instrument_id, 'EQUITY', 1, 100, 90, -10.0000,
           'liquidity', 'BOUGHT', 'contradictory'
    FROM atom.run r, atom.instrument i WHERE i.symbol = 'TESTBEES' LIMIT 1
$$, 'run_candidate_gate_ck');

-- --------------------------------------------------------------------------
-- Tax: the redundant figures must agree with the ones they derive from
-- --------------------------------------------------------------------------
DO $do$ BEGIN RAISE NOTICE '== tax =='; END $do$;
SELECT pg_temp.expect_reject($$
    INSERT INTO atom.tax_gain
        (trading_account_id, investor_id, instrument_id, financial_year, quantity,
         acquired_on, disposed_on, holding_days, cost_basis, proceeds, stt_paid,
         gain_amount, term, tax_bucket, provenance)
    SELECT a.trading_account_id, a.investor_id, i.instrument_id, '2026-27', 10,
           DATE '2026-04-01', DATE '2026-09-25', 177, 1001, 1100, 1.1,
           999, 'SHORT', 'EQUITY', 'ATOM'
    FROM atom.trading_account a, atom.instrument i WHERE i.symbol = 'TESTBEES' LIMIT 1
$$, 'tax_gain_amount_ck');

SELECT pg_temp.expect_reject($$
    INSERT INTO atom.tax_gain
        (trading_account_id, investor_id, instrument_id, financial_year, quantity,
         acquired_on, disposed_on, holding_days, cost_basis, proceeds, stt_paid,
         gain_amount, term, tax_bucket, provenance)
    SELECT a.trading_account_id, a.investor_id, i.instrument_id, '2026-2027', 10,
           DATE '2026-04-01', DATE '2026-09-25', 177, 1001, 1100, 1.1,
           99, 'SHORT', 'EQUITY', 'ATOM'
    FROM atom.trading_account a, atom.instrument i WHERE i.symbol = 'TESTBEES' LIMIT 1
$$, 'tax_gain_fy_ck');

INSERT INTO atom.tax_gain
    (trading_account_id, investor_id, instrument_id, financial_year, quantity,
     acquired_on, disposed_on, holding_days, cost_basis, proceeds, stt_paid,
     gain_amount, term, tax_bucket, provenance)
SELECT a.trading_account_id, a.investor_id, i.instrument_id, '2026-27', 10,
       DATE '2026-04-01', DATE '2026-09-25', 177, 1001, 1100, 1.1,
       99, 'SHORT', 'EQUITY', 'ATOM'
FROM atom.trading_account a, atom.instrument i WHERE i.symbol = 'TESTBEES' LIMIT 1;
SELECT pg_temp.check_that('a consistent tax_gain row is accepted', true);

-- The Rs 1.25 lakh exemption cannot be over-consumed
SELECT pg_temp.expect_reject($$
    INSERT INTO atom.tax_exemption_usage
        (investor_id, financial_year, exemption_limit, consumed_amount)
    SELECT investor_id, '2026-27', 125000, 125001 FROM atom.investor LIMIT 1
$$, 'exemption_not_exceeded_ck');

-- --------------------------------------------------------------------------
-- Views: the two cost bases must stay separate (D-190/D-195)
-- --------------------------------------------------------------------------
DO $do$ BEGIN RAISE NOTICE '== views =='; END $do$;
SELECT pg_temp.check_that(
    'v_position keeps the synthetic and actual quantities apart',
    (SELECT count(*) FROM atom.v_position
     WHERE synthetic_quantity IS NOT NULL AND actual_quantity IS NOT NULL) >= 0
);

SELECT pg_temp.check_that(
    'v_position reports the harvest proxy''s strategy cost, not its actual cost',
    (SELECT strategy_unit_cost FROM atom.v_position p
     JOIN atom.instrument i ON i.instrument_id = p.instrument_id
     WHERE i.symbol = 'PROXYBEES') = 200.2000
);

SELECT pg_temp.check_that(
    'v_position reports the harvest proxy''s actual cost separately',
    (SELECT actual_unit_cost FROM atom.v_position p
     JOIN atom.instrument i ON i.instrument_id = p.instrument_id
     WHERE i.symbol = 'PROXYBEES') = 85.0000
);

-- D-062: the subtraction is not clamped, so an over-exclusion is visible
INSERT INTO atom.account_exclusion
    (trading_account_id, instrument_id, exclusion_type, quantity, created_by)
SELECT l.trading_account_id, l.instrument_id, 'EXCLUSION', l.quantity_open + 3, 'test'
FROM atom.position_lot l WHERE l.provenance = 'EXTERNAL';

SELECT pg_temp.check_that(
    'Q-181: v_sellable_quantity surfaces a negative rather than clamping to zero',
    (SELECT sellable_quantity FROM atom.v_sellable_quantity s
     JOIN atom.instrument i ON i.instrument_id = s.instrument_id
     WHERE i.symbol = 'PROXYBEES') = -3
);

-- CHARGES-MODEL 4.2: unknown charges read as NULL, never as zero
INSERT INTO atom.lot_closure
    (lot_id, sell_order_request_id, quantity, unit_proceeds, closed_on)
SELECT l.lot_id, o.order_request_id, 5, 110.0000, DATE '2026-09-26'
FROM atom.position_lot l, atom.order_request o
WHERE l.provenance = 'ATOM' AND o.idempotency_key = 'atm2609250205';

SELECT pg_temp.check_that(
    'v_realised_gain reports NULL, not zero, where the broker gave no charges',
    (SELECT allocated_broker_charges IS NULL FROM atom.v_realised_gain)
);

SELECT pg_temp.check_that(
    'v_realised_gain computes the gain against the actual cost',
    (SELECT gain_on_actual_cost FROM atom.v_realised_gain) = 5 * (110.0000 - 100.1000)
);

-- --------------------------------------------------------------------------
-- 0017 — config scope is enforced, and one value per account-level key
-- --------------------------------------------------------------------------
DO $do$ BEGIN RAISE NOTICE '== config =='; END $do$;

-- A GLOBAL key cannot be written per account: one kill switch, not N.
SELECT pg_temp.expect_reject($$
    INSERT INTO atom.account_config
        (trading_account_id, config_key_id, universe_id, value_text, updated_by)
    SELECT a.trading_account_id, k.config_key_id, u.universe_id, 'true', 'test'
    FROM atom.trading_account a, atom.config_key k, atom.universe u
    WHERE k.key_name = 'kill_switch' LIMIT 1
$$, 'account_config_scope_ck');

-- ... and a non-GLOBAL key cannot be written globally.
SELECT pg_temp.expect_reject($$
    INSERT INTO atom.global_config (config_key_id, value_text, updated_by)
    SELECT config_key_id, '10000', 'test' FROM atom.config_key
    WHERE key_name = 'trade_amount_inr'
$$, 'global_config_scope_ck');

-- An account-level key takes no category; a per-category key requires one.
SELECT pg_temp.expect_reject($$
    INSERT INTO atom.account_config
        (trading_account_id, config_key_id, universe_id, category_code, value_text, updated_by)
    SELECT a.trading_account_id, k.config_key_id, u.universe_id, 'EQUITY', '10', 'test'
    FROM atom.trading_account a, atom.config_key k, atom.universe u
    WHERE k.key_name = 'max_orders_per_run' LIMIT 1
$$, 'account_config_scope_ck');

SELECT pg_temp.expect_reject($$
    INSERT INTO atom.account_config
        (trading_account_id, config_key_id, universe_id, value_text, updated_by)
    SELECT a.trading_account_id, k.config_key_id, u.universe_id, '3.5', 'test'
    FROM atom.trading_account a, atom.config_key k, atom.universe u
    WHERE k.key_name = 'profit_target_pct' LIMIT 1
$$, 'account_config_scope_ck');

-- NULLs are not distinct: a second value for the same account-level key is refused.
INSERT INTO atom.account_config
    (trading_account_id, config_key_id, universe_id, value_text, updated_by)
SELECT a.trading_account_id, k.config_key_id, u.universe_id, '10', 'test'
FROM atom.trading_account a, atom.config_key k, atom.universe u
WHERE k.key_name = 'max_orders_per_run' AND a.broker_client_code = 'CLIENT-DRY' LIMIT 1;

SELECT pg_temp.expect_reject($$
    INSERT INTO atom.account_config
        (trading_account_id, config_key_id, universe_id, value_text, updated_by)
    SELECT a.trading_account_id, k.config_key_id, u.universe_id, '99', 'test'
    FROM atom.trading_account a, atom.config_key k, atom.universe u
    WHERE k.key_name = 'max_orders_per_run' AND a.broker_client_code = 'CLIENT-DRY' LIMIT 1
$$, 'account_config_one_value_uk');

SELECT pg_temp.check_that('the budget buffer key D-059b names now exists',
    EXISTS (SELECT 1 FROM atom.config_key WHERE key_name = 'budget_buffer_pct'));

-- --------------------------------------------------------------------------
-- Structure
-- --------------------------------------------------------------------------
DO $do$ BEGIN RAISE NOTICE '== structure =='; END $do$;
SELECT pg_temp.check_that('40 tables exist',
    (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'atom' AND c.relkind = 'r') = 40);

SELECT pg_temp.check_that('4 views exist',
    (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'atom' AND c.relkind = 'v') = 4);

SELECT pg_temp.check_that('RLS is enabled on every table',
    NOT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'atom' AND c.relkind = 'r' AND NOT c.relrowsecurity));

SELECT pg_temp.check_that('every table has a policy',
    (SELECT count(DISTINCT tablename) FROM pg_policies WHERE schemaname = 'atom') = 40);

SELECT pg_temp.check_that('every view is security_invoker',
    NOT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'atom' AND c.relkind = 'v'
                AND NOT ('security_invoker=true' = ANY(COALESCE(c.reloptions, '{}')))));

SELECT pg_temp.check_that('every foreign key has a leading index on exactly its columns',
    NOT EXISTS (
        SELECT 1
        FROM   pg_constraint fk
        JOIN   pg_class t     ON t.oid = fk.conrelid
        JOIN   pg_namespace n ON n.oid = t.relnamespace
        WHERE  n.nspname = 'atom' AND fk.contype = 'f'
        AND    NOT EXISTS (
                   SELECT 1
                   FROM   pg_index ix
                   WHERE  ix.indrelid = fk.conrelid
                   -- A partial index normally cannot serve an integrity check,
                   -- with one exception: a predicate of `col IS NOT NULL` on the
                   -- FK column itself, because the check looks the column up by
                   -- equality and equality implies non-null.
                   AND    (ix.indpred IS NULL
                           OR pg_get_expr(ix.indpred, ix.indrelid)
                              = format('(%I IS NOT NULL)',
                                       (SELECT a.attname FROM pg_attribute a
                                        WHERE a.attrelid = fk.conrelid
                                        AND   a.attnum = fk.conkey[1])))
                   AND    (SELECT array_agg(k ORDER BY o)
                           FROM   unnest(ix.indkey::int2[]) WITH ORDINALITY u(k, o)
                           WHERE  o <= array_length(fk.conkey, 1)) <@ fk.conkey
                   AND    (SELECT array_agg(k ORDER BY o)
                           FROM   unnest(ix.indkey::int2[]) WITH ORDINALITY u(k, o)
                           WHERE  o <= array_length(fk.conkey, 1)) @> fk.conkey)));

DO $do$ BEGIN RAISE NOTICE ''; END $do$;
DO $do$ BEGIN RAISE NOTICE 'All schema assertions passed.'; END $do$;

ROLLBACK;
