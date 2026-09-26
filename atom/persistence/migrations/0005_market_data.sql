-- 0005_market_data.sql
-- Daily prices and NAV. Both are append-only observations, keyed by
-- (instrument, trade_date), with the source recorded so a bad feed is traceable
-- to the feed rather than to the strategy (D-017).

CREATE TABLE atom.price_daily (
    instrument_id bigint NOT NULL REFERENCES atom.instrument,
    trade_date    date   NOT NULL,
    open_px  numeric(18,4),
    high_px  numeric(18,4),
    low_px   numeric(18,4),
    close_px numeric(18,4) NOT NULL,
    volume        bigint,
    source        text NOT NULL,          -- UPSTOX | DHAN | YAHOO | NSE   (D-017)
    ingested_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, trade_date),
    CONSTRAINT price_daily_close_ck CHECK (close_px > 0),
    CONSTRAINT price_daily_volume_ck CHECK (volume IS NULL OR volume >= 0)
);

CREATE INDEX price_daily_date_idx ON atom.price_daily (trade_date DESC);

COMMENT ON COLUMN atom.price_daily.close_px IS
    'The only NOT NULL price. The mean-reversion computation needs closes; OHLC is for display '
    'and for the implausible-move sanity gate (Q-183).';

CREATE TABLE atom.nav_daily (
    instrument_id bigint NOT NULL REFERENCES atom.instrument,
    trade_date    date   NOT NULL,
    nav  numeric(18,4),
    inav numeric(18,4),
    is_interpolated boolean NOT NULL DEFAULT false,  -- D-058f: single-day gap filled
    PRIMARY KEY (instrument_id, trade_date),
    CONSTRAINT nav_daily_nav_ck  CHECK (nav  IS NULL OR nav  > 0),
    CONSTRAINT nav_daily_inav_ck CHECK (inav IS NULL OR inav > 0)
);

COMMENT ON COLUMN atom.nav_daily.is_interpolated IS
    'D-058f: a single-day gap may be filled, and the fill is flagged. A premium computed against '
    'an interpolated NAV is reported as such rather than presented as observed.';
