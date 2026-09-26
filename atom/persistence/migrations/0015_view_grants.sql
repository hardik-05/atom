-- 0015_view_grants.sql
-- Correction to 0014.
--
-- `GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA atom` includes VIEWS in
-- Postgres, and 0012 had already created the four. So the engine role came away
-- with INSERT and UPDATE on them, which contradicts the explicit
-- `GRANT SELECT ON ... TO atom_engine` two dozen lines further down the same file.
--
-- Nothing could have gone wrong through it: all four views aggregate or join, so
-- none is auto-updatable and any write would have failed at parse time. It is
-- corrected anyway, because a privilege listing is read as a statement of intent
-- and this one said something the design does not mean.
--
-- 0014 is left as applied rather than edited: a migration that has run on a real
-- database is history, and history gets a correction, not a rewrite.

REVOKE INSERT, UPDATE ON
    atom.v_position,
    atom.v_sellable_quantity,
    atom.v_cash_balance,
    atom.v_realised_gain
FROM atom_engine;

-- The four views are derived figures, and the tables under them are where writes
-- belong. Reading is all the engine ever needs from them.
