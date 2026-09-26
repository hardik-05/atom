-- 0008_cash_capital_charges.sql
-- Cash ledger, cost of capital, and charges.
--
-- Cost of capital is charged on the WHOLE principal every day, split across
-- three buckets (D-080). Deployed and settlement capital is attributable to a
-- universe via the lot; idle capital is not, because it belongs to the account
-- and to no universe (D-169). That asymmetry is why there are two accrual
-- tables rather than one with a nullable universe.

CREATE TABLE atom.cash_ledger (
    cash_ledger_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trading_account_id bigint NOT NULL REFERENCES atom.trading_account,
    entry_type text NOT NULL,   -- CAPITAL_IN | CAPITAL_OUT | PROFIT_WITHDRAWAL
                                -- | TRADE_BUY | TRADE_SELL | CHARGES | UNCLASSIFIED
    amount     numeric(18,4) NOT NULL,
    entry_date date NOT NULL,
    order_request_id bigint REFERENCES atom.order_request,
    source     text NOT NULL,   -- ATOM | BROKER_LEDGER | OPERATOR
    narration  text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT cash_entry_type_ck CHECK (entry_type IN
        ('CAPITAL_IN','CAPITAL_OUT','PROFIT_WITHDRAWAL','TRADE_BUY','TRADE_SELL',
         'CHARGES','UNCLASSIFIED')),
    CONSTRAINT cash_source_ck CHECK (source IN ('ATOM','BROKER_LEDGER','OPERATOR')),
    CONSTRAINT cash_amount_nonzero_ck CHECK (amount <> 0)
);

COMMENT ON COLUMN atom.cash_ledger.entry_type IS
    'UNCLASSIFIED is deliberate: a broker ledger line ATOM cannot map is stored as-is and '
    'surfaced for the operator, never dropped and never guessed into a category.';
COMMENT ON COLUMN atom.cash_ledger.amount IS
    'Signed. Credits positive, debits negative. Zero is rejected because a zero-amount ledger '
    'line carries no information and would silently pass reconciliation.';

-- ---------------------------------------------------------------------------
-- Cost of capital (D-053, D-080, D-169)
-- ---------------------------------------------------------------------------
CREATE TABLE atom.capital_rate (
    capital_rate_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trading_account_id bigint NOT NULL REFERENCES atom.trading_account,  -- D-053
    annual_rate_pct    numeric(18,4) NOT NULL,
    effective_from     date NOT NULL,
    CONSTRAINT capital_rate_uk UNIQUE (trading_account_id, effective_from),
    CONSTRAINT capital_rate_nonneg_ck CHECK (annual_rate_pct >= 0)
);

CREATE TABLE atom.capital_accrual_daily (
    trading_account_id    bigint NOT NULL REFERENCES atom.trading_account,
    accrual_date          date NOT NULL,
    principal_outstanding numeric(18,4) NOT NULL,
    deployed_amount       numeric(18,4) NOT NULL,
    settlement_amount     numeric(18,4) NOT NULL,
    idle_amount           numeric(18,4) NOT NULL,
    rate_pct              numeric(18,4) NOT NULL,
    interest_total        numeric(18,4) NOT NULL,
    PRIMARY KEY (trading_account_id, accrual_date),
    -- Invariant 2: the three buckets sum to the principal, every day.
    CONSTRAINT accrual_buckets_ck
        CHECK (deployed_amount + settlement_amount + idle_amount = principal_outstanding)
);

COMMENT ON CONSTRAINT accrual_buckets_ck ON atom.capital_accrual_daily IS
    'D-080: idle capital is charged too. If the buckets did not have to sum to the principal, a '
    'bug that lost track of settlement money would quietly under-charge the strategy and flatter '
    'every return figure downstream.';

-- D-169: deployed and settlement capital ARE attributable to a universe (via the lot).
-- Idle capital is NOT — it belongs to the account and to no universe.
CREATE TABLE atom.capital_accrual_universe_daily (
    trading_account_id bigint NOT NULL REFERENCES atom.trading_account,
    universe_id        bigint NOT NULL REFERENCES atom.universe,
    accrual_date       date NOT NULL,
    deployed_amount    numeric(18,4) NOT NULL,
    settlement_amount  numeric(18,4) NOT NULL,
    interest_amount    numeric(18,4) NOT NULL,
    PRIMARY KEY (trading_account_id, universe_id, accrual_date)
);

COMMENT ON TABLE atom.capital_accrual_universe_daily IS
    'D-169: has no idle_amount column, and that omission is the point. Idle capital cannot be '
    'attributed to a universe, so per-universe interest never sums to the account total - the '
    'difference is the idle charge, and reporting shows it as its own line.';

-- ---------------------------------------------------------------------------
-- charge — computed AND broker rows coexist; the contrast is the feature (D-024)
-- ---------------------------------------------------------------------------
CREATE TABLE atom.charge (
    charge_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_request_id   bigint REFERENCES atom.order_request,
    trading_account_id bigint NOT NULL REFERENCES atom.trading_account,
    charge_type text NOT NULL,   -- BROKERAGE | STT | EXCHANGE | SEBI | STAMP | GST | DP
    amount      numeric(18,4) NOT NULL,
    source      text NOT NULL,   -- COMPUTED | BROKER   (D-024 contrast)
    charge_date date NOT NULL,
    CONSTRAINT charge_source_ck CHECK (source IN ('COMPUTED','BROKER')),
    CONSTRAINT charge_type_ck CHECK (charge_type IN
        ('BROKERAGE','STT','EXCHANGE','SEBI','STAMP','GST','DP')),
    CONSTRAINT charge_amount_nonneg_ck CHECK (amount >= 0)
);

COMMENT ON TABLE atom.charge IS
    'D-024: two rows per component per order - what ATOM computed, and what the broker actually '
    'levied. Where a broker supplies nothing, NO row is written. Reporting then shows a dash, '
    'not Rs 0.00: "we cannot know" and "no charge was levied" are different facts.';
COMMENT ON COLUMN atom.charge.charge_type IS
    'Q-313 is OPEN and material: STT on ETF units may be 0.001% sell-side only rather than the '
    '0.1% both-sides equity rate - a 100x difference that feeds unit_cost. Rates live in config, '
    'not here, so closing Q-313 is a config change and a recomputation, not a migration.';
