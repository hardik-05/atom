-- 0016_seed_reference.sql
-- Reference data: the five brokers, and the config-key catalogue.
--
-- This is the only seed migration, and it seeds only things that are facts about
-- the world rather than choices about an account. The five brokers exist whether
-- or not ATOM runs; their capability flags are research findings from
-- docs/03-brokers/adapters/. The config KEYS exist because the engine reads them;
-- their VALUES do not, and nothing here writes one.
--
-- That distinction is D-037/D-038 and it is the whole point: `suggested_value`
-- pre-fills a form for a person, and the engine never reads the column. An
-- account with no `account_config` row for a required key halts its run. If this
-- file inserted values, the first run would trade on numbers nobody chose.
--
-- Idempotent throughout: ON CONFLICT DO NOTHING, so re-applying changes nothing.

-- ---------------------------------------------------------------------------
-- The five brokers
-- ---------------------------------------------------------------------------
-- Only the four flags the ENGINE branches on live here. The full capability
-- profile is code — atom/adapters/<broker>/capabilities.py — because it is read
-- by the adapter that implements it and belongs beside it (D-185).
--
--   supports_gtt          false for Shoonya: no GTT is documented, so the sell
--                         path falls back to same-day limits (Q-271, D-129/D-164)
--   supports_charges_api  the D-024 contrast needs per-ORDER actuals. Groww gives
--                         an aggregate and Upstox period totals; neither supports
--                         the contrast, so both are false and the report shows a
--                         dash rather than a zero
--   supports_ledger_api   Dhan alone, and it is the only broker whose cash
--                         balance can be reconstructed rather than asserted
--   auth_flow             how a token is obtained each morning
INSERT INTO atom.broker
    (broker_code, display_name, supports_gtt, supports_charges_api,
     supports_ledger_api, auth_flow)
VALUES
    ('DHAN',    'Dhan',    true,  true,  true,  'CREDENTIAL_LOGIN'),
    ('ZERODHA', 'Zerodha', true,  true,  false, 'OAUTH_REDIRECT'),
    ('GROWW',   'Groww',   true,  false, false, 'PASTE_TOKEN'),
    ('UPSTOX',  'Upstox',  true,  false, false, 'OAUTH_REDIRECT'),
    ('SHOONYA', 'Shoonya', false, false, false, 'OAUTH_REDIRECT')
ON CONFLICT (broker_code) DO NOTHING;

-- Dhan is CREDENTIAL_LOGIN because TOTP makes its morning token need no human at
-- all. Groww is PASTE_TOKEN because its key+TOTP call is headless but Groww still
-- requires a daily approval click in its own console, so the guaranteed path is
-- the operator pasting a token (D-177 pattern C). Upstox, Zerodha and Shoonya all
-- return a code through a redirect the operator carries by hand (D-183).

-- ---------------------------------------------------------------------------
-- Config-key catalogue — docs/01-architecture/CONFIGURATION-MODEL.md section 3
-- ---------------------------------------------------------------------------
-- "Every operational number in ATOM. Nothing outside this table may be a literal
-- in code." A key missing from here is a number hardcoded somewhere it should
-- not be.
INSERT INTO atom.config_key (key_name, scope, value_type, is_required, suggested_value, description)
VALUES
-- 3.1 Strategy, per (trading_account, universe, category)
('profit_target_pct',         'ACCOUNT_CATEGORY', 'NUMERIC', true,  '3.5000',
 'Sell limit = strategy cost basis x (1 + this). On a harvest proxy the basis is the synthetic one, so the target recovers the capital originally committed (D-188).'),
('depth_levels',              'ACCOUNT_CATEGORY', 'INTEGER', true,  '3',
 'How far down the ranked list to look when the top candidates are already held.'),
('trade_amount_inr',          'ACCOUNT_CATEGORY', 'NUMERIC', true,  '10000.0000',
 'Rupees per buy order. Quantity is floor(amount x buffer% / LTP) — whole units only, and the buffer leaves room for charges (D-059b).'),
('lookback_days',             'ACCOUNT_CATEGORY', 'INTEGER', true,  '50',
 'Window for the mean or median the deviation is measured against.'),
('average_method',            'ACCOUNT_CATEGORY', 'TEXT',    true,  'MEAN',
 'MEAN or MEDIAN. The ranking basis (D-026).'),
('category_enabled',          'ACCOUNT_CATEGORY', 'BOOLEAN', true,  'true',
 'Suppresses BUYING only. Sells always run — a disabled category must still be able to exit.'),
('nav_check_enabled',         'ACCOUNT_CATEGORY', 'BOOLEAN', true,  'true',
 'Master toggle for the NAV premium veto gate.'),
('nav_premium_tolerance_pct', 'ACCOUNT_CATEGORY', 'NUMERIC', true,  '2.0000',
 'Maximum premium over NAV permitted on a buy. Zero demands parity; negative would demand a discount, so use zero.'),
('volume_threshold_units',    'ACCOUNT_CATEGORY', 'NUMERIC', true,  '100000.0000',
 'Liquidity floor in UNITS, not rupees (D-027). A rupee floor would mean different things for instruments 83x apart in price.'),
('volume_window_days',        'ACCOUNT_CATEGORY', 'INTEGER', true,  '25',
 'Window for the average volume the liquidity gate uses. Configurable, deliberately not fixed at 25 or 60 (D-016).'),

-- 3.2 Strategy, per trading_account
('category_priority',         'ACCOUNT', 'ARRAY',   true,  'EQUITY,COMMODITY,GLOBAL',
 'The order categories are funded in when cash runs short. A permutation of the universe categories: no duplicates, no omissions.'),
('daily_spend_cap_inr',       'ACCOUNT', 'NUMERIC', true,  NULL,
 'Hard stop; a breach aborts the run. No suggested value: the sensible figure is derived from this account''s own trade amounts (about twice their sum), so a pre-filled number would be wrong for every account but one.'),
('max_orders_per_run',        'ACCOUNT', 'INTEGER', true,  '10',
 'A guard against a logic bug, not a strategy parameter. If a run wants more orders than this, something is wrong.'),
('dry_run',                   'ACCOUNT', 'BOOLEAN', true,  'false',
 'Compute and log everything, send nothing. Dry and live share every line of code and differ only at the OrderGateway seam (D-045).'),

-- 3.3 Harvesting, per trading_account
('stcg_rate_pct',             'ACCOUNT', 'NUMERIC', true,  '20.0000',
 'The rate used to value a booked short-term loss when judging whether a harvest is worth it. Equity STCG is a flat 20%; commodity and global STCG is at slab, so this single key is an approximation for those two buckets.'),
('correlation_window_days',   'ACCOUNT', 'INTEGER', false, '250',
 'Window for proxy correlation. NOT REQUIRED in v1: D-163 made proxy selection manual, with no correlation floor and no automatic matching. Kept for V2-14.'),
('min_correlation',           'ACCOUNT', 'NUMERIC', false, '0.8500',
 'Floor below which a proxy is rejected. Not required in v1, for the same reason as correlation_window_days.'),
('harvest_requires_approval', 'ACCOUNT', 'BOOLEAN', true,  'true',
 'Human approval gate on a harvest pairing. A harvest sells at a loss on purpose, which is not a thing to do unattended.'),

-- 3.4 Operational, global
('market_open_gate_time',     'GLOBAL', 'TEXT',    true,  '09:30',
 'Earliest a run may execute, IST. The market opens at 09:15; the gap lets opening volatility settle before a limit price is chosen.'),
('order_poll_interval_sec',   'GLOBAL', 'INTEGER', true,  '60',
 'Fill-polling cadence.'),
('order_poll_timeout_sec',    'GLOBAL', 'INTEGER', true,  '300',
 'When to stop waiting. The order is LEFT RESTING, never cancelled on timeout, and its status becomes IN_FLIGHT rather than anything terminal (D-180).'),
('log_purge_days',            'GLOBAL', 'INTEGER', true,  '90',
 'Retention for atom.run_log (D-030). Safe to purge because the decision record lives in run_candidate, not in a log.'),
('local_log_retention_days',  'GLOBAL', 'INTEGER', true,  '30',
 'Retention for the EC2 and S3 copies (D-025).'),
('kill_switch',               'GLOBAL', 'BOOLEAN', true,  'false',
 'Blocks all order placement everywhere, for every account and every universe at once.')
ON CONFLICT (key_name) DO NOTHING;

COMMENT ON TABLE atom.config_key IS
    'The catalogue of every operational number in ATOM. Nothing outside this table may be a '
    'literal in code. Seeded by 0016; a key absent from here is a number hardcoded somewhere '
    'it should not be.';
