-- 0021_shortlist.sql
-- Volume decides WHICH instruments may be traded; it plays no part in a day's run.
--
-- A sync builds, per account / universe / category, a shortlist: the top `shortlist_size`
-- instruments by average daily volume over `volume_window_days`, at or above
-- `volume_threshold_units`. A run only looks at that shortlist, fetches its last
-- `lookback_days` prices from the broker, and decides on price and NAV alone.
--
-- Sells and buys are released separately: the day's sells go out as soon as the plan is made
-- (`sells_released_at`); the buys wait for the operator and keep the one-release-per-day rule
-- (`released_at`, 0020).

ALTER TABLE atom.run ADD COLUMN IF NOT EXISTS sells_released_at timestamptz;
UPDATE atom.run SET sells_released_at = released_at
WHERE released_at IS NOT NULL AND sells_released_at IS NULL;

CREATE TABLE IF NOT EXISTS atom.universe_shortlist (
    trading_account_id bigint  NOT NULL REFERENCES atom.trading_account,
    universe_id        bigint  NOT NULL REFERENCES atom.universe,
    category_code      text    NOT NULL,
    instrument_id      bigint  NOT NULL REFERENCES atom.instrument,
    rank               integer NOT NULL,
    avg_volume         numeric(20,2) NOT NULL,
    volume_days        integer NOT NULL,
    built_at           timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (trading_account_id, universe_id, category_code, instrument_id),
    CONSTRAINT universe_shortlist_rank_ck CHECK (rank >= 1)
);
ALTER TABLE atom.universe_shortlist ENABLE ROW LEVEL SECURITY;
CREATE POLICY atom_engine_all ON atom.universe_shortlist FOR ALL TO atom_engine
    USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, UPDATE, DELETE ON atom.universe_shortlist TO atom_engine;

INSERT INTO atom.config_key (key_name, scope, value_type, is_required, suggested_value, description)
VALUES ('shortlist_size', 'ACCOUNT_CATEGORY', 'INTEGER', true, '10',
        'How many instruments of this category make the viable universe: the top N by average '
        'volume, chosen when market data is synced. Buys are picked from this list only.')
ON CONFLICT (key_name) DO NOTHING;

UPDATE atom.config_key SET description =
    'Buy up to this many instruments per category per run: the most-below-average candidates that '
    'pass the NAV check and are not already held. Failed or held ones are skipped, not counted.'
WHERE key_name = 'depth_levels';
UPDATE atom.config_key SET description =
    'Days of history whose average volume ranks instruments when the shortlist is built at sync. '
    'Not used by a run.'
WHERE key_name = 'volume_window_days';
UPDATE atom.config_key SET description =
    'Liquidity floor in UNITS (D-027), applied when the shortlist is built at sync. '
    'Not used by a run.'
WHERE key_name = 'volume_threshold_units';
UPDATE atom.config_key SET description =
    'Days of closing prices the run averages (mean or median) to find how far a price has fallen. '
    'Fetched from the broker at each run.'
WHERE key_name = 'lookback_days';

-- Existing accounts: equity 50, commodity 25, global 3 (anything else 10).
INSERT INTO atom.account_config
    (trading_account_id, config_key_id, universe_id, category_code, value_text, is_configured,
     updated_by)
SELECT ac.trading_account_id, k.config_key_id, ac.universe_id, ac.category_code,
       CASE ac.category_code WHEN 'EQUITY' THEN '50' WHEN 'COMMODITY' THEN '25'
                             WHEN 'GLOBAL' THEN '3' ELSE '10' END,
       true, 'migration 0021'
FROM atom.account_config ac
JOIN atom.config_key src ON src.config_key_id = ac.config_key_id AND src.key_name = 'volume_window_days'
CROSS JOIN (SELECT config_key_id FROM atom.config_key WHERE key_name = 'shortlist_size') k
WHERE ac.category_code IS NOT NULL
ON CONFLICT ON CONSTRAINT account_config_uk DO NOTHING;
