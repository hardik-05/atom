-- 0018_depository_authorisation.sql
-- How the demat account authorises sells, recorded as a FACT about the account.
--
-- The sell pass needs to know whether a sell will be accepted without a
-- per-order depository authorisation (RUN-LIFECYCLE.md 3.4). Until now the engine
-- inferred it from the broker's profile flags — which is guessing from a field
-- whose presence on Upstox's profile response has never been observed. The
-- operator confirmed on 2026-09-26 that every account has DDPI; that belongs in
-- the database, not in an inference.
--
--   DDPI     Demat Debit and Pledge Instruction — sells go through unaided
--   POA      the older Power of Attorney — same effect
--   EDIS     neither; each sell needs an electronic authorisation first
--   UNKNOWN  not yet recorded — the engine falls back to the broker's flags
--
-- UNKNOWN is the default for existing rows because it is the honest state, not a
-- permissive one: an UNKNOWN account whose broker flags show neither DDPI nor
-- POA still has its sell pass skipped.
ALTER TABLE atom.trading_account
    ADD COLUMN depository_authorisation text NOT NULL DEFAULT 'UNKNOWN',
    ADD CONSTRAINT trading_account_depository_ck
        CHECK (depository_authorisation IN ('DDPI', 'POA', 'EDIS', 'UNKNOWN'));

COMMENT ON COLUMN atom.trading_account.depository_authorisation IS
    'DDPI | POA | EDIS | UNKNOWN. Operator-recorded. Decides whether the sell pass may '
    'place sells without a per-order depository authorisation (RUN-LIFECYCLE.md 3.4).';
