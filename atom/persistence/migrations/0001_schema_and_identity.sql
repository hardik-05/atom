-- 0001_schema_and_identity.sql
-- Schema container, investors, brokers, trading accounts.
--
-- Everything ATOM owns lives in schema `atom`. Nothing is created in `public`,
-- which is what Supabase exposes over PostgREST — the browser holds no database
-- key at all and reaches the data only through the engine's API
-- (docs/06-web/AUTH-AND-ACCESS.md §4.1).

CREATE SCHEMA IF NOT EXISTS atom;

COMMENT ON SCHEMA atom IS
    'ATOM trading engine. Not exposed over PostgREST; reached only through the engine API.';

-- ---------------------------------------------------------------------------
-- investor — a tax identity, never a PAN (D-092, D-128)
-- ---------------------------------------------------------------------------
CREATE TABLE atom.investor (
    investor_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    external_key    text        NOT NULL UNIQUE,   -- D-128: internal key, never the PAN
    display_name    text        NOT NULL,
    pan_masked      text,                          -- 'XXXXX1234X' only, never the full PAN
    relationship    text        NOT NULL,          -- SELF | SPOUSE | DEPENDENT_CHILD | DEPENDENT_PARENT (D-092)
    status          text        NOT NULL DEFAULT 'ACTIVE',
    onboarded_on    date        NOT NULL,          -- D-138: cost-of-capital accrual starts here
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT investor_relationship_ck
        CHECK (relationship IN ('SELF','SPOUSE','DEPENDENT_CHILD','DEPENDENT_PARENT')),
    CONSTRAINT investor_status_ck
        CHECK (status IN ('ACTIVE','INACTIVE')),
    CONSTRAINT investor_pan_masked_ck
        CHECK (pan_masked IS NULL OR pan_masked ~ '^[X]{5}[0-9]{4}[X]$')
);

COMMENT ON COLUMN atom.investor.pan_masked IS
    'D-128: the masked form is the only PAN-shaped value the database may hold. '
    'The regex makes storing a real PAN impossible rather than merely discouraged.';
COMMENT ON COLUMN atom.investor.onboarded_on IS
    'D-138: cost-of-capital accrual starts on this date, not on the first trade.';

-- ---------------------------------------------------------------------------
-- broker — capability flags that drive which code path runs (D-142, D-024)
-- ---------------------------------------------------------------------------
CREATE TABLE atom.broker (
    broker_id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    broker_code          text NOT NULL UNIQUE,     -- UPSTOX | DHAN | ZERODHA | GROWW | SHOONYA
    display_name         text NOT NULL,
    supports_gtt         boolean NOT NULL,         -- D-142: drives the sell path
    supports_charges_api boolean NOT NULL,         -- D-024 contrast available?
    supports_ledger_api  boolean NOT NULL,
    auth_flow            text    NOT NULL,         -- OAUTH_REDIRECT | PASTE_TOKEN | CREDENTIAL_LOGIN
    status               text    NOT NULL DEFAULT 'ACTIVE',
    CONSTRAINT broker_auth_flow_ck
        CHECK (auth_flow IN ('OAUTH_REDIRECT','PASTE_TOKEN','CREDENTIAL_LOGIN')),
    CONSTRAINT broker_status_ck
        CHECK (status IN ('ACTIVE','DISABLED'))
);

COMMENT ON TABLE atom.broker IS
    'Capability flags are data, not code branches. The adapter reports them; the engine reads '
    'them (BrokerCapabilities in atom/domain/models.py).';

-- ---------------------------------------------------------------------------
-- trading_account — (investor, broker, mode). Paper and live never mix (D-041)
-- ---------------------------------------------------------------------------
CREATE TABLE atom.trading_account (
    trading_account_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    investor_id        bigint NOT NULL REFERENCES atom.investor,
    broker_id          bigint NOT NULL REFERENCES atom.broker,
    broker_client_code text   NOT NULL,
    execution_mode     text   NOT NULL,            -- LIVE | DRY   (D-041)
    egress_ip          inet,                       -- the investor's whitelisted IPv4 (D-007)
    proxy_url          text,                       -- per-account forward proxy (D-005/D-136)
    status             text   NOT NULL DEFAULT 'PENDING',
    onboarded_at       timestamptz,
    created_at         timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT trading_account_uk UNIQUE (broker_id, broker_client_code, execution_mode),
    CONSTRAINT trading_account_mode_ck CHECK (execution_mode IN ('LIVE','DRY')),
    CONSTRAINT trading_account_status_ck
        CHECK (status IN ('PENDING','ACTIVE','SUSPENDED','CLOSED')),
    -- Invariant 1: a LIVE account cannot exist without its static-IP egress path.
    CONSTRAINT trading_account_live_needs_proxy_ck
        CHECK (execution_mode = 'DRY' OR (egress_ip IS NOT NULL AND proxy_url IS NOT NULL))
);

COMMENT ON CONSTRAINT trading_account_live_needs_proxy_ck ON atom.trading_account IS
    'D-136: static IP is mandatory for order placement from 1 Apr 2026. A LIVE account with no '
    'egress IP or no proxy would place orders from the wrong source address, so it cannot be '
    'stored at all.';
COMMENT ON COLUMN atom.trading_account.execution_mode IS
    'D-041: frozen on the account and inherited by every row that references it. Invariant 8.';
