# Migrations

Sixteen numbered files, applied in filename order. Every one of them has been
applied to the **AtomX** Supabase project and to a local PostgreSQL 16.

| File | What it adds |
|---|---|
| `0001_schema_and_identity.sql` | schema `atom`, `investor`, `broker`, `trading_account` |
| `0002_instruments.sql` | `instrument`, `broker_instrument`, `instrument_classification` |
| `0003_universes.sql` | `universe`, categories, SCD-2 membership, snapshots |
| `0004_configuration.sql` | `config_key`, `account_config`, `config_history` |
| `0005_market_data.sql` | `price_daily`, `nav_daily` |
| `0006_runs.sql` | `run_batch`, `run`, `run_candidate` — the decision record |
| `0007_orders_and_lots.sql` | `order_request`, `order_fill`, `position_lot`, `lot_closure` |
| `0008_cash_capital_charges.sql` | `cash_ledger`, capital accrual, `charge` |
| `0009_broker_sessions.sql` | `broker_session` — SSM paths, never tokens |
| `0010_tax.sql` | `tax_gain`, loss pool, set-off, exemption, computation |
| `0011_exclusions_harvest_audit.sql` | exclusions, `harvest_chain`, `action_audit`, `run_log` |
| `0012_views.sql` | the four derived views, `security_invoker` |
| `0013_indexes.sql` | 121 indexes, including every foreign key |
| `0014_roles_and_rls.sql` | `atom_engine`, narrow grants, RLS on all 38 tables |
| `0015_view_grants.sql` | correction to 0014 — views are read-only to the engine |
| `0016_seed_reference.sql` | the five brokers and the 24-key config catalogue |

## Applying them

```bash
export ATOM_DATABASE_URL='postgresql://user:pass%40word@host:5432/postgres'
for f in atom/persistence/migrations/0*.sql; do
    psql "$ATOM_DATABASE_URL" -v ON_ERROR_STOP=1 -f "$f" || break
done
```

**The password must be percent-encoded.** `@` is `%40`. A password containing `@`
in an un-encoded URL parses as a hostname and fails as an authentication error,
which reads exactly like a revoked credential.

## Verifying them

```bash
ATOM_DATABASE_URL=... make db-verify
```

Drops the `atom` schema, re-applies all sixteen, then runs
[`verify_constraints.sql`](verify_constraints.sql): 23 statements that **must be
rejected**, each asserted against the constraint that should refuse it, and 21
positive assertions. It runs in a transaction and rolls back, and it is pure SQL
with no psql meta-commands, so the same file works through a SQL API.

A constraint asserted against its *name* matters more than it looks: a row
refused for the wrong reason would otherwise pass the test. If `order_kind_ck`
ever stops existing and a `NOT NULL` refuses the same row, the test fails.

> ⚠️ `db-verify` **drops the schema**. Point it at a throwaway database. The
> integration tests read a separate variable, `ATOM_TEST_DATABASE_URL`, for the
> same reason — so a copy-pasted export cannot destroy live data.

## Two things that are deliberately not here

**No `DOWN` migrations.** A down migration for a schema holding trade history is
a way to lose it. Rolling back means restoring a backup, which is the operation
that actually works.

**No migration runner.** Sixteen files applied in filename order do not need a
framework, and the Supabase migration history already records what ran. When the
count grows past what `ls` makes obvious, that is the time to add one.

## Adding one

1. Next number, descriptive name, and a header comment saying **why** — the
   constraint is the easy part to read from the SQL, the reasoning is not.
2. New table → add its grant and its append-only status explicitly. RLS is
   generated from `pg_class` in 0014 so it cannot be forgotten, but a grant is
   not, and `ALTER DEFAULT PRIVILEGES` gives the baseline and nothing narrower.
3. Add the rejection case to `verify_constraints.sql`. An untested constraint is
   a comment.
4. `make db-verify`, then apply to Supabase.
5. **Never edit an applied migration.** 0015 exists because 0014 had a mistake:
   a migration that has run on a real database is history, and history gets a
   correction, not a rewrite.
