-- 0004_configuration.sql
-- Configuration: no defaults anywhere (D-037, D-038, D-039).
--
-- `config_key.suggested_value` pre-fills the UI and is NEVER read by the engine.
-- An unconfigured key halts the run. `account_config.value_text = NULL` with
-- `is_configured = true` means an explicit NULL, which is different from absent
-- (D-039) — that is why absence is modelled as a missing row rather than a null.

CREATE TABLE atom.config_key (
    config_key_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key_name        text NOT NULL UNIQUE,
    scope           text NOT NULL,        -- ACCOUNT_CATEGORY | ACCOUNT | GLOBAL
    value_type      text NOT NULL,        -- NUMERIC | INTEGER | BOOLEAN | TEXT | ARRAY
    is_required     boolean NOT NULL DEFAULT true,
    suggested_value text,                 -- UI pre-fill ONLY — never applied by the engine (D-038)
    description     text NOT NULL,
    CONSTRAINT config_key_scope_ck
        CHECK (scope IN ('ACCOUNT_CATEGORY','ACCOUNT','GLOBAL')),
    CONSTRAINT config_key_value_type_ck
        CHECK (value_type IN ('NUMERIC','INTEGER','BOOLEAN','TEXT','ARRAY'))
);

COMMENT ON COLUMN atom.config_key.suggested_value IS
    'D-038: a UI pre-fill and nothing else. The engine never reads this column. If it did, an '
    'unconfigured key would silently acquire a value, which is the exact failure D-037 forbids.';

CREATE TABLE atom.account_config (
    account_config_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trading_account_id bigint NOT NULL REFERENCES atom.trading_account,
    config_key_id      bigint NOT NULL REFERENCES atom.config_key,
    universe_id        bigint NOT NULL REFERENCES atom.universe,   -- D-155: config is per universe
    category_code      text,              -- a universe_category; NULL for account-level keys
    value_text         text,              -- NULL here means an explicit NULL (D-039)
    is_configured      boolean NOT NULL DEFAULT true,
    version            integer NOT NULL DEFAULT 1,
    updated_by         text NOT NULL,
    updated_at         timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT account_config_uk
        UNIQUE (trading_account_id, universe_id, config_key_id, category_code)
);

COMMENT ON COLUMN atom.account_config.value_text IS
    'D-039: NULL with is_configured = true is an explicit NULL. Absence is a missing row, not a '
    'null value. The engine distinguishes the two and halts only on the second.';
COMMENT ON CONSTRAINT account_config_uk ON atom.account_config IS
    'NULL category_code does not collide under a UNIQUE constraint in Postgres, so an '
    'account-level key and a category-level key of the same name coexist. That is intended: the '
    'resolver prefers the category row and falls back to the account row.';

CREATE TABLE atom.config_history (
    config_history_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_config_id bigint NOT NULL REFERENCES atom.account_config,
    old_value  text,
    new_value  text,
    changed_by text NOT NULL,
    changed_at timestamptz NOT NULL DEFAULT now()
);
