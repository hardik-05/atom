-- 0009_broker_sessions.sql
-- Daily broker tokens (D-170, D-178).
--
-- The table stores an SSM Parameter Store PATH and never a token (D-079). The
-- path shape is constrained positively — it must start with `/atom/sessions/` —
-- rather than by excluding token-looking strings, because a whitelist of one
-- shape cannot be got round by a token format nobody anticipated.
--
-- Validity is PROBED, never computed (D-170/D-178): `verified_at` is the last
-- time a holdings read actually succeeded. No broker's stated expiry is trusted
-- as a substitute, because the run starts after 6 a.m. and a token that "should"
-- be valid until midnight can still be revoked at 9.

CREATE TABLE atom.broker_session (
    broker_session_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trading_account_id bigint NOT NULL REFERENCES atom.trading_account,
    trade_date   date NOT NULL,
    status       text NOT NULL,      -- PENDING | VALID | INVALID | CLEARED
    secret_ref   text,               -- SSM Parameter Store path — NEVER the token itself (D-079)
    obtained_at  timestamptz,
    verified_at  timestamptz,        -- last successful holdings probe
    cleared_at   timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT broker_session_uk UNIQUE (trading_account_id, trade_date),
    CONSTRAINT broker_session_status_ck
        CHECK (status IN ('PENDING','VALID','INVALID','CLEARED')),
    -- A path, not a secret. Positively constrained to the documented prefix.
    CONSTRAINT broker_session_is_ssm_path_ck
        CHECK (secret_ref IS NULL OR secret_ref ~ '^/atom/sessions/[A-Za-z0-9_.:/-]+$'),
    CONSTRAINT broker_session_no_secret_ck
        CHECK (secret_ref IS NULL OR secret_ref NOT LIKE '%Bearer%'),
    -- CLEARED means the parameter was deleted after the run; the reference must go with it.
    CONSTRAINT broker_session_cleared_ck
        CHECK (status <> 'CLEARED' OR (cleared_at IS NOT NULL AND secret_ref IS NULL)),
    CONSTRAINT broker_session_valid_needs_ref_ck
        CHECK (status <> 'VALID' OR secret_ref IS NOT NULL)
);

COMMENT ON COLUMN atom.broker_session.secret_ref IS
    'D-079: an SSM path such as /atom/sessions/{account}/{trade_date}. Never a token value. Two '
    'constraints guard it - a positive path-shape regex and a legacy Bearer exclusion.';
COMMENT ON COLUMN atom.broker_session.verified_at IS
    'D-170/D-178: set only by a successful probe against the broker. Token validity is observed, '
    'never derived from a documented expiry.';
COMMENT ON CONSTRAINT broker_session_cleared_ck ON atom.broker_session IS
    'The token is deleted from SSM after every run. A CLEARED row keeping a secret_ref would '
    'point at a parameter that no longer exists, which reads as "we have a token" and is worse '
    'than reading as "we have none".';
