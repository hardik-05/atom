-- 0013_indexes.sql
-- Indexes for the access paths the engine and console actually use.
--
-- Postgres indexes a UNIQUE or PRIMARY KEY constraint automatically but does NOT
-- index a foreign key. Every index here backs either a run-time lookup or a
-- cascade/join that would otherwise be a sequential scan.

-- Identity and accounts
CREATE INDEX trading_account_investor_idx ON atom.trading_account (investor_id);
CREATE INDEX trading_account_broker_idx   ON atom.trading_account (broker_id);

-- Instruments: the adapter resolves ATOM instrument -> broker token on every order
CREATE INDEX broker_instrument_instrument_idx ON atom.broker_instrument (instrument_id);
CREATE INDEX instrument_symbol_idx            ON atom.instrument (symbol);
CREATE INDEX instrument_isin_idx              ON atom.instrument (isin);

-- Universes
CREATE INDEX universe_member_instrument_idx  ON atom.universe_member (instrument_id);
CREATE INDEX universe_snapshot_universe_idx  ON atom.universe_snapshot (universe_id, effective_from DESC);
CREATE INDEX universe_snapshot_member_instrument_idx
    ON atom.universe_snapshot_member (instrument_id);

-- Config: the resolver reads every key for one (account, universe) at run start
CREATE INDEX account_config_lookup_idx ON atom.account_config (trading_account_id, universe_id);
CREATE INDEX account_config_key_idx    ON atom.account_config (config_key_id);
CREATE INDEX config_history_config_idx ON atom.config_history (account_config_id, changed_at DESC);

-- Runs
CREATE INDEX run_account_date_idx  ON atom.run (trading_account_id, trade_date DESC);
CREATE INDEX run_universe_date_idx ON atom.run (universe_id, trade_date DESC);
CREATE INDEX run_batch_idx         ON atom.run (run_batch_id);
CREATE INDEX run_snapshot_idx      ON atom.run (snapshot_id);
CREATE INDEX run_candidate_instrument_idx ON atom.run_candidate (instrument_id);

-- Orders: the reconcile phase reads open orders for an account, and looks up an
-- order by the broker's own id when a status poll comes back
CREATE INDEX order_request_account_idx ON atom.order_request (trading_account_id, placed_at DESC);
CREATE INDEX order_request_run_idx     ON atom.order_request (run_id);
CREATE INDEX order_request_instrument_idx ON atom.order_request (instrument_id);
CREATE INDEX order_request_universe_idx   ON atom.order_request (universe_id);
CREATE INDEX order_request_broker_order_idx
    ON atom.order_request (trading_account_id, broker_order_id)
    WHERE broker_order_id IS NOT NULL;
-- Non-terminal orders only: this is the set the reconcile phase chases (D-180).
CREATE INDEX order_request_unsettled_idx
    ON atom.order_request (trading_account_id, status)
    WHERE status IN ('INTENT','PLACED','PARTIAL','IN_FLIGHT');

CREATE INDEX order_fill_order_idx ON atom.order_fill (order_request_id);

-- Lots: the hot path. Open lots for one (account, universe, instrument).
CREATE INDEX position_lot_open_idx
    ON atom.position_lot (trading_account_id, universe_id, instrument_id)
    WHERE quantity_open > 0;
-- Universe FIFO order (D-167), and tax FIFO reads the same column at account scope.
CREATE INDEX position_lot_fifo_idx
    ON atom.position_lot (trading_account_id, instrument_id, acquired_on, lot_id)
    WHERE quantity_open > 0;
-- Harvest proxies are a small subset that gets its own sell tranche (D-195).
CREATE INDEX position_lot_synthetic_idx
    ON atom.position_lot (trading_account_id, instrument_id)
    WHERE synthetic_cost_basis IS NOT NULL AND quantity_open > 0;
CREATE INDEX position_lot_buy_order_idx ON atom.position_lot (buy_order_request_id);

CREATE INDEX lot_closure_sell_order_idx ON atom.lot_closure (sell_order_request_id);
CREATE INDEX lot_closure_closed_on_idx  ON atom.lot_closure (closed_on);
-- Settlement tracking: closures whose funds have not been observed yet (D-050/D-080).
CREATE INDEX lot_closure_awaiting_funds_idx
    ON atom.lot_closure (closed_on)
    WHERE funds_credited_on IS NULL;

-- Cash, capital, charges
CREATE INDEX cash_ledger_account_date_idx ON atom.cash_ledger (trading_account_id, entry_date DESC);
CREATE INDEX cash_ledger_order_idx        ON atom.cash_ledger (order_request_id);
CREATE INDEX cash_ledger_unclassified_idx
    ON atom.cash_ledger (trading_account_id, entry_date)
    WHERE entry_type = 'UNCLASSIFIED';
CREATE INDEX capital_rate_account_idx ON atom.capital_rate (trading_account_id, effective_from DESC);
CREATE INDEX charge_order_idx   ON atom.charge (order_request_id);
CREATE INDEX charge_account_idx ON atom.charge (trading_account_id, charge_date DESC);

-- Broker sessions: "is today's token valid for this account" is asked constantly
CREATE INDEX broker_session_account_date_idx
    ON atom.broker_session (trading_account_id, trade_date DESC);

-- Tax
CREATE INDEX tax_gain_investor_fy_idx   ON atom.tax_gain (investor_id, financial_year);
CREATE INDEX tax_gain_account_idx       ON atom.tax_gain (trading_account_id, disposed_on);
CREATE INDEX tax_gain_instrument_idx    ON atom.tax_gain (instrument_id);
CREATE INDEX tax_loss_pool_investor_idx ON atom.tax_loss_pool (investor_id, financial_year);
-- The set-off engine wants pools with something left in them, oldest vintage first.
CREATE INDEX tax_loss_pool_available_idx
    ON atom.tax_loss_pool (investor_id, term, financial_year)
    WHERE amount_remaining > 0;
CREATE INDEX tax_setoff_investor_idx ON atom.tax_setoff (investor_id, financial_year, sequence_no);
CREATE INDEX tax_setoff_pool_idx     ON atom.tax_setoff (tax_loss_pool_id);
CREATE INDEX tax_setoff_gain_idx     ON atom.tax_setoff (tax_gain_id);
CREATE INDEX tax_computation_investor_idx
    ON atom.tax_computation (investor_id, financial_year, computed_at DESC);

-- Exclusions, harvests, audit
CREATE INDEX account_exclusion_lookup_idx
    ON atom.account_exclusion (trading_account_id, instrument_id)
    WHERE released_at IS NULL;
CREATE INDEX harvest_chain_sold_lot_idx  ON atom.harvest_chain (sold_lot_id);
CREATE INDEX harvest_chain_proxy_lot_idx ON atom.harvest_chain (proxy_lot_id);
CREATE INDEX harvest_chain_status_idx    ON atom.harvest_chain (status, created_at DESC);
CREATE INDEX action_audit_entity_idx     ON atom.action_audit (entity, entity_id, occurred_at DESC);
CREATE INDEX action_audit_actor_idx      ON atom.action_audit (actor, occurred_at DESC);
CREATE INDEX run_log_run_idx             ON atom.run_log (run_id, logged_at);

-- --------------------------------------------------------------------------
-- Foreign keys not already covered above.
--
-- A partial or composite index does not serve a foreign key: Postgres checks
-- referential integrity on the parent's DELETE or UPDATE, which needs the child
-- column indexed unconditionally and leading. `account_exclusion` and
-- `position_lot` both have partial indexes on these columns for the hot path;
-- these unconditional ones are for the integrity check.
-- --------------------------------------------------------------------------
CREATE INDEX account_config_universe_fk_idx    ON atom.account_config (universe_id);
CREATE INDEX account_exclusion_instrument_fk_idx ON atom.account_exclusion (instrument_id);
CREATE INDEX capital_accrual_universe_fk_idx   ON atom.capital_accrual_universe_daily (universe_id);
CREATE INDEX position_lot_instrument_fk_idx    ON atom.position_lot (instrument_id);
CREATE INDEX position_lot_universe_fk_idx      ON atom.position_lot (universe_id);
CREATE INDEX position_lot_account_fk_idx       ON atom.position_lot (trading_account_id);
CREATE INDEX account_exclusion_account_fk_idx  ON atom.account_exclusion (trading_account_id);

-- position_lot.order_fill_id needs no index of its own: position_lot_fill_uk is
-- partial on `order_fill_id IS NOT NULL`, and the integrity check looks the
-- column up by equality, which implies non-null, so the planner can use it.
