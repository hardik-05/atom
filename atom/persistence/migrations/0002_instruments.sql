-- 0002_instruments.sql
-- Instruments in three layers: ATOM's own reference row, each broker's token for
-- it, and the strategy classification.
--
-- The split exists because no two brokers identify an instrument the same way —
-- Upstox uses `NSE_EQ|<ISIN>`, Dhan a numeric securityId, Zerodha an
-- instrument_token, Groww a trading symbol. Only `broker_instrument` knows about
-- any of that (D-185).

-- ---------------------------------------------------------------------------
-- instrument — ATOM's own reference data, the single source of truth
-- ---------------------------------------------------------------------------
CREATE TABLE atom.instrument (
    instrument_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    isin              text NOT NULL,
    symbol            text NOT NULL,
    exchange          text NOT NULL DEFAULT 'NSE',
    name              text NOT NULL,
    instrument_type   text NOT NULL,                 -- ETF | EQUITY | INDEX
    asset_class       text NOT NULL,                 -- EQUITY | COMMODITY | GLOBAL | DEBT | HYBRID
    country           text NOT NULL DEFAULT 'IN',    -- room for future non-Indian universes
    currency          text NOT NULL DEFAULT 'INR',
    lot_size          integer NOT NULL DEFAULT 1,
    tick_size         numeric(18,4),
    status            text NOT NULL DEFAULT 'ACTIVE', -- ACTIVE | BLOCKED | REVIEW (D-091)
    status_reason     text,
    status_changed_at timestamptz,
    CONSTRAINT instrument_uk UNIQUE (isin, exchange),
    CONSTRAINT instrument_status_ck CHECK (status IN ('ACTIVE','BLOCKED','REVIEW')),
    CONSTRAINT instrument_type_ck CHECK (instrument_type IN ('ETF','EQUITY','INDEX')),
    CONSTRAINT instrument_asset_class_ck
        CHECK (asset_class IN ('EQUITY','COMMODITY','GLOBAL','DEBT','HYBRID')),
    CONSTRAINT instrument_lot_size_ck CHECK (lot_size > 0),
    CONSTRAINT instrument_tick_size_ck CHECK (tick_size IS NULL OR tick_size > 0)
);

COMMENT ON COLUMN atom.instrument.tick_size IS
    'Q-300: ATOM prices against THIS value, never a broker''s. Upstox reports tick size in paise '
    'in JSON and in rupees in CSV; a broker value is cross-checked and warned about, never used.';
COMMENT ON COLUMN atom.instrument.asset_class IS
    'Drives the tax bucket: equity STCG is a flat 20%, commodity and global STCG is at slab, all '
    'LTCG is 12.5%, and the Rs 1.25 lakh exemption is equity-only.';

-- ---------------------------------------------------------------------------
-- broker_instrument — the ONLY place a broker's identifier for an instrument lives
-- ---------------------------------------------------------------------------
CREATE TABLE atom.broker_instrument (
    broker_instrument_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    broker_id     bigint NOT NULL REFERENCES atom.broker,
    instrument_id bigint NOT NULL REFERENCES atom.instrument,
    broker_token  text   NOT NULL,   -- Upstox NSE_EQ|ISIN · Dhan securityId · Zerodha token
    broker_symbol text   NOT NULL,
    tradable      boolean NOT NULL DEFAULT true,
    synced_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT broker_instrument_uk UNIQUE (broker_id, instrument_id),
    CONSTRAINT broker_instrument_token_uk UNIQUE (broker_id, broker_token)
);

COMMENT ON COLUMN atom.broker_instrument.tradable IS
    'Upstox publishes a suspended-instruments file and Dhan an ASM_GSM_FLAG. Both land here, so '
    'the tradability gate reads one column rather than five broker quirks.';

-- ---------------------------------------------------------------------------
-- instrument_classification — the strategy's own taxonomy (D-103, D-108)
-- ---------------------------------------------------------------------------
CREATE TABLE atom.instrument_classification (
    instrument_id     bigint PRIMARY KEY REFERENCES atom.instrument,
    bucket            text NOT NULL,   -- INDEX | SECTOR | FACTOR | COMMODITY | GLOBAL | EXCLUDED
    tier2_group       text NOT NULL,   -- BANKING | LARGECAP_50 | GOLD …   (D-103)
    tier1_index       text NOT NULL,   -- exact tracked index               (D-103)
    assignment_status text NOT NULL,   -- AUTO | MANUAL | UNASSIGNED        (D-108)
    assigned_by       text,
    assigned_at       timestamptz,
    CONSTRAINT classification_status_ck
        CHECK (assignment_status IN ('AUTO','MANUAL','UNASSIGNED')),
    CONSTRAINT classification_bucket_ck
        CHECK (bucket IN ('INDEX','SECTOR','FACTOR','COMMODITY','GLOBAL','EXCLUDED'))
);

COMMENT ON TABLE atom.instrument_classification IS
    'D-108: UNASSIGNED is a real state that blocks trading, not a placeholder to be guessed past.';
