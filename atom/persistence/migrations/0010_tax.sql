-- 0010_tax.sql
-- The tax ledger (D-171).
--
-- Matching here is TAX FIFO, which is NOT the universe FIFO used for strategy
-- P&L (D-167). Two universes holding the same instrument on one demat account
-- have one tax history between them, because the tax authority sees one holding
-- — so tax_gain has no universe_id, and that omission is deliberate.
--
-- Rates for reference: equity STCG is a flat 20%, commodity and global STCG is
-- at slab, all LTCG is 12.5%, and the Rs 1.25 lakh exemption is equity-only and
-- per PAN per financial year.

-- One row per taxable disposal, matched under TAX FIFO — not universe FIFO
CREATE TABLE atom.tax_gain (
    tax_gain_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trading_account_id bigint NOT NULL REFERENCES atom.trading_account,
    investor_id        bigint NOT NULL REFERENCES atom.investor,
    instrument_id      bigint NOT NULL REFERENCES atom.instrument,
    financial_year text NOT NULL,          -- '2026-27'
    quantity     integer NOT NULL,
    acquired_on  date NOT NULL,
    disposed_on  date NOT NULL,
    holding_days integer NOT NULL,
    cost_basis   numeric(18,4) NOT NULL,   -- incl. deductible buy charges
    proceeds     numeric(18,4) NOT NULL,   -- net of deductible sell charges
    stt_paid     numeric(18,4) NOT NULL,   -- recorded but NOT deducted (D-127)
    gain_amount  numeric(18,4) NOT NULL,
    term         text NOT NULL,            -- SHORT | LONG
    tax_bucket   text NOT NULL,            -- EQUITY | COMMODITY | GLOBAL
    provenance   text NOT NULL,            -- ATOM | EXTERNAL   (D-123)
    computed_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT tax_gain_term_ck CHECK (term IN ('SHORT','LONG')),
    CONSTRAINT tax_gain_bucket_ck CHECK (tax_bucket IN ('EQUITY','COMMODITY','GLOBAL')),
    CONSTRAINT tax_gain_provenance_ck CHECK (provenance IN ('ATOM','EXTERNAL')),
    CONSTRAINT tax_gain_quantity_ck CHECK (quantity > 0),
    CONSTRAINT tax_gain_fy_ck CHECK (financial_year ~ '^[0-9]{4}-[0-9]{2}$'),
    CONSTRAINT tax_gain_disposed_after_acquired_ck CHECK (disposed_on >= acquired_on),
    CONSTRAINT tax_gain_holding_days_ck
        CHECK (holding_days = (disposed_on - acquired_on)),
    CONSTRAINT tax_gain_amount_ck CHECK (gain_amount = proceeds - cost_basis)
);

COMMENT ON TABLE atom.tax_gain IS
    'D-167: matched under TAX FIFO. There is no universe_id and there must not be one - the tax '
    'authority sees one demat holding however many universes ATOM runs against it.';
COMMENT ON COLUMN atom.tax_gain.stt_paid IS
    'D-127: recorded for the audit trail and NOT deducted from proceeds. STT is not a deductible '
    'expense against capital gains.';
COMMENT ON CONSTRAINT tax_gain_amount_ck ON atom.tax_gain IS
    'The gain is redundant with proceeds and cost_basis, and stored anyway so a computation bug '
    'fails at write time rather than appearing in a filing.';

-- Losses available to offset, by type and vintage; 8-year carry-forward window
CREATE TABLE atom.tax_loss_pool (
    tax_loss_pool_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    investor_id      bigint NOT NULL REFERENCES atom.investor,
    financial_year   text NOT NULL,          -- year the loss AROSE
    term             text NOT NULL,          -- SHORT | LONG
    amount_original  numeric(18,4) NOT NULL,
    amount_remaining numeric(18,4) NOT NULL,
    expires_after_fy text NOT NULL,          -- 8 assessment years
    CONSTRAINT tax_loss_term_ck CHECK (term IN ('SHORT','LONG')),
    CONSTRAINT tax_loss_remaining_ck CHECK (amount_remaining >= 0),
    CONSTRAINT tax_loss_le_original_ck CHECK (amount_remaining <= amount_original),
    CONSTRAINT tax_loss_original_positive_ck CHECK (amount_original > 0),
    CONSTRAINT tax_loss_fy_ck CHECK (financial_year ~ '^[0-9]{4}-[0-9]{2}$'),
    CONSTRAINT tax_loss_expiry_fy_ck CHECK (expires_after_fy ~ '^[0-9]{4}-[0-9]{2}$')
);

COMMENT ON COLUMN atom.tax_loss_pool.term IS
    'A SHORT-term loss offsets either term; a LONG-term loss offsets long-term gains only. The '
    'asymmetry lives in the set-off engine, and tax_setoff records which rule was applied.';

-- How each loss was applied; the audit trail of the set-off ordering (D-127)
CREATE TABLE atom.tax_setoff (
    tax_setoff_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    investor_id      bigint NOT NULL REFERENCES atom.investor,
    financial_year   text NOT NULL,          -- year the set-off was APPLIED
    tax_loss_pool_id bigint REFERENCES atom.tax_loss_pool,
    tax_gain_id      bigint REFERENCES atom.tax_gain,
    amount           numeric(18,4) NOT NULL CHECK (amount > 0),
    sequence_no      integer NOT NULL,       -- current-year first, then oldest vintage
    applied_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT tax_setoff_fy_ck CHECK (financial_year ~ '^[0-9]{4}-[0-9]{2}$')
);

COMMENT ON COLUMN atom.tax_setoff.sequence_no IS
    'D-127: the set-off ORDER changes the liability, so it is recorded rather than re-derived. '
    'Current-year losses first, then carried-forward by oldest vintage.';

-- Rs 1.25 lakh equity LTCG exemption — once per PAN per FY (D-127)
CREATE TABLE atom.tax_exemption_usage (
    investor_id     bigint NOT NULL REFERENCES atom.investor,
    financial_year  text NOT NULL,
    exemption_limit numeric(18,4) NOT NULL,   -- config-driven (D-122)
    consumed_amount numeric(18,4) NOT NULL DEFAULT 0,
    PRIMARY KEY (investor_id, financial_year),
    CONSTRAINT exemption_not_exceeded_ck CHECK (consumed_amount <= exemption_limit),
    CONSTRAINT exemption_nonneg_ck CHECK (consumed_amount >= 0),
    CONSTRAINT exemption_fy_ck CHECK (financial_year ~ '^[0-9]{4}-[0-9]{2}$')
);

COMMENT ON TABLE atom.tax_exemption_usage IS
    'Keyed on investor, not on trading_account. The exemption is per PAN, so two brokers under '
    'one PAN share one allowance - which is why an investor is a tax identity in this schema.';
COMMENT ON COLUMN atom.tax_exemption_usage.exemption_limit IS
    'D-122: config-driven, not hardcoded at 125000. The figure is a budget line and will change.';

-- The computed liability, per PAN per FY — the output of the whole engine
CREATE TABLE atom.tax_computation (
    tax_computation_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    investor_id       bigint NOT NULL REFERENCES atom.investor,
    financial_year    text NOT NULL,
    stcg_equity       numeric(18,4) NOT NULL DEFAULT 0,
    stcg_commodity    numeric(18,4) NOT NULL DEFAULT 0,
    stcg_global       numeric(18,4) NOT NULL DEFAULT 0,
    ltcg_equity       numeric(18,4) NOT NULL DEFAULT 0,
    ltcg_commodity    numeric(18,4) NOT NULL DEFAULT 0,
    ltcg_global       numeric(18,4) NOT NULL DEFAULT 0,
    exemption_applied numeric(18,4) NOT NULL DEFAULT 0,
    setoff_applied    numeric(18,4) NOT NULL DEFAULT 0,
    tax_before_surcharge numeric(18,4) NOT NULL,
    surcharge         numeric(18,4) NOT NULL DEFAULT 0,
    cess              numeric(18,4) NOT NULL,
    total_liability   numeric(18,4) NOT NULL,
    computed_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT tax_computation_uk UNIQUE (investor_id, financial_year, computed_at),
    CONSTRAINT tax_computation_fy_ck CHECK (financial_year ~ '^[0-9]{4}-[0-9]{2}$'),
    CONSTRAINT tax_computation_total_ck
        CHECK (total_liability = tax_before_surcharge + surcharge + cess)
);

COMMENT ON TABLE atom.tax_computation IS
    'Append-only: computed_at is part of the key, so re-running the engine adds a row rather than '
    'overwriting one. What was filed stays visible next to what the engine says today.';
