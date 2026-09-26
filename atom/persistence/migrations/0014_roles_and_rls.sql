-- 0014_roles_and_rls.sql
-- The engine role, privilege grants, and row-level security on every table.
--
-- Three things this file does, and one it deliberately does not:
--
--   1. Creates `atom_engine` as a NOLOGIN role. No password appears in this
--      repository, ever. A login role is created out-of-band and granted
--      membership: CREATE ROLE atom_api LOGIN PASSWORD '...' IN ROLE atom_engine;
--   2. Grants privileges narrowly. Several tables are append-only to the engine,
--      so a bug cannot rewrite history it has already written.
--   3. Enables RLS on every table with one permissive policy for `atom_engine`.
--
-- What it does NOT do is pretend RLS is isolating investors today. v1 is
-- admin-only (D-040) and the policy is `USING (true)`. The value of enabling RLS
-- now is that every table already denies by default to any role without a
-- policy, so V2-5's investor-scoped read access is a policy to add rather than a
-- migration that has to touch 38 tables and hope none was missed (Q-074).

-- ---------------------------------------------------------------------------
-- 1. The engine role
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'atom_engine') THEN
        CREATE ROLE atom_engine NOLOGIN;
    END IF;
END
$$;

COMMENT ON ROLE atom_engine IS
    'ATOM engine and API. NOLOGIN by design: a login role is granted membership out-of-band so '
    'no credential lives in the repository. Never `postgres`, and never used from a browser.';

-- Nothing is public. The browser holds no database key at all, and Supabase's
-- PostgREST roles have no business in this schema.
REVOKE ALL ON SCHEMA atom FROM PUBLIC;
GRANT USAGE ON SCHEMA atom TO atom_engine;

-- ---------------------------------------------------------------------------
-- 2. Privileges — read/write by default, append-only where history must not move
-- ---------------------------------------------------------------------------
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA atom TO atom_engine;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA atom TO atom_engine;

-- Append-only: written once, never amended. An UPDATE here would rewrite the
-- record that explains a past decision or a past filing.
REVOKE UPDATE ON
    atom.run_candidate,      -- the decision record (D-052)
    atom.order_fill,         -- an observed fill
    atom.lot_closure,        -- except funds_credited_on, re-granted below (D-050)
    atom.charge,             -- what was computed and what was levied (D-024)
    atom.config_history,
    atom.action_audit,
    atom.tax_gain,
    atom.tax_setoff,
    atom.tax_computation
FROM atom_engine;

-- The one field on a closure that is legitimately filled in later: settlement is
-- OBSERVED when the broker ledger shows it, not known when the lot closes (D-080).
GRANT UPDATE (funds_credited_on) ON atom.lot_closure TO atom_engine;

-- run_log is the only table the engine may delete from, because it is the only
-- table that holds no decision record (docs/07-logging/ARCHIVAL.md).
GRANT DELETE ON atom.run_log TO atom_engine;

-- Future tables in this schema inherit the baseline. Append-only status is not
-- inheritable and must be declared per table in the migration that adds it.
ALTER DEFAULT PRIVILEGES IN SCHEMA atom
    GRANT SELECT, INSERT, UPDATE ON TABLES TO atom_engine;
ALTER DEFAULT PRIVILEGES IN SCHEMA atom
    GRANT USAGE, SELECT ON SEQUENCES TO atom_engine;

-- ---------------------------------------------------------------------------
-- 3. Row-level security on every table, driven off the catalogue
-- ---------------------------------------------------------------------------
-- Generated from pg_class rather than a hand-written list of 38 names, so a
-- table added in a later migration cannot be forgotten here by a typo.
DO $$
DECLARE
    t record;
BEGIN
    FOR t IN
        SELECT c.relname
        FROM   pg_class c
        JOIN   pg_namespace n ON n.oid = c.relnamespace
        WHERE  n.nspname = 'atom'
        AND    c.relkind = 'r'
        ORDER  BY c.relname
    LOOP
        EXECUTE format('ALTER TABLE atom.%I ENABLE ROW LEVEL SECURITY', t.relname);
        EXECUTE format(
            'CREATE POLICY atom_engine_all ON atom.%I FOR ALL TO atom_engine '
            'USING (true) WITH CHECK (true)', t.relname);
    END LOOP;
END
$$;

-- The views are `security_invoker = true` (0012), so reading one applies the
-- policies above to the calling role rather than the view owner's bypass.
GRANT SELECT ON
    atom.v_position,
    atom.v_sellable_quantity,
    atom.v_cash_balance,
    atom.v_realised_gain
TO atom_engine;
