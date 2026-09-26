# Database Schema

**Status:** 🟢 **Built and applied.** PostgreSQL 17 (Supabase project *AtomX*)
**Implements:** D-150 · the gate for all application code
**Convention:** schema `atom`, snake_case, `NUMERIC(18,4)` money, `timestamptz` UTC (D-073c)
**Code:** [`atom/persistence/migrations/`](../../atom/persistence/migrations/) — 15 numbered files

> The DDL below is the design. The migrations are the truth, and they now agree:
> 38 tables, 4 views, 121 indexes, 101 CHECK constraints, 58 foreign keys, RLS
> and a policy on every table. `make db-verify` applies all 15 to a throwaway
> database and asserts that each constraint rejects the row it exists to refuse.
>
> Three places where the implementation added something this document did not
> have, each flagged inline below: `order_request.product` / `.validity`
> (§9), `IN_FLIGHT` in the order status set (§9), and the D-193 constraint on
> `harvest_chain` (§11).

---

## 1. Design principles

1. **Third normal form, with two deliberate exceptions** (§12) — both documented, both for
   auditability rather than performance.
2. **Nothing derivable is stored** — positions derive from lots, balances from the ledger,
   P&L from lots plus charges. The only stored aggregates are immutable historical snapshots.
3. **Surrogate keys everywhere** (`bigint generated always as identity`), with natural keys as
   unique constraints. Broker codes and ISINs change; row identity should not.
4. **Every operational fact is attributable** — which run, which config version, which operator.
5. **Invariants live in constraints**, not conventions. If a rule matters, the database enforces
   it (§11).
6. **Soft-delete via status columns.** Trading and audit rows are never hard-deleted (D-073d).

---

## 2. Entity overview

```
investor ──< trading_account >── broker
                  │
                  ├──< account_config >── config_key
                  ├──< cash_ledger
                  ├──< capital_rate
                  ├──< position_lot >──< lot_closure
                  ├──< order_request >──< order_fill
                  ├──< account_exclusion
                  └──< run >──< run_candidate
                               └──< run_log

instrument ──< broker_instrument >── broker
     │
     ├──< instrument_classification      (bucket / tier1 / tier2)
     ├──< price_daily
     ├──< nav_daily
     └──< universe_member >── universe
                                  └──< universe_snapshot >──< universe_snapshot_member
```

---

## 3. Identity and access

```sql
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
    CONSTRAINT investor_pan_masked_ck
        CHECK (pan_masked IS NULL OR pan_masked ~ '^[X]{5}[0-9]{4}[X]$')
);
```

*`relationship` is constrained to SEBI's family definition (D-092). A value outside it cannot be
stored, so the compliance boundary is enforced by the database rather than remembered.*

```sql
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
        CHECK (auth_flow IN ('OAUTH_REDIRECT','PASTE_TOKEN','CREDENTIAL_LOGIN'))
);

CREATE TABLE atom.trading_account (
    trading_account_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    investor_id     bigint NOT NULL REFERENCES atom.investor,
    broker_id       bigint NOT NULL REFERENCES atom.broker,
    broker_client_code text NOT NULL,
    execution_mode  text   NOT NULL,               -- LIVE | DRY   (D-041)
    egress_ip       inet,                          -- the investor's whitelisted IPv4 (D-007)
    proxy_url       text,                          -- per-account forward proxy (D-005/D-136)
    status          text   NOT NULL DEFAULT 'PENDING',
    onboarded_at    timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT trading_account_uk UNIQUE (broker_id, broker_client_code, execution_mode),
    CONSTRAINT trading_account_mode_ck CHECK (execution_mode IN ('LIVE','DRY')),
    CONSTRAINT trading_account_live_needs_proxy_ck
        CHECK (execution_mode = 'DRY' OR (egress_ip IS NOT NULL AND proxy_url IS NOT NULL))
);
```

> **`trading_account_live_needs_proxy_ck` is D-136 as a constraint.** A LIVE account cannot exist
> without an egress IP and a proxy. The "missing proxy raises rather than defaults" rule is
> therefore impossible to violate, not merely discouraged.

`execution_mode` sits on the **account**, so a paper account and a live account are different
rows. Every child table inherits the mode through the FK, which is how D-041's isolation is
achieved without a discriminator on thirty tables.

---

## 4. Instruments — three layers

```sql
CREATE TABLE atom.instrument (
    instrument_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    isin           text NOT NULL,
    symbol         text NOT NULL,
    exchange       text NOT NULL DEFAULT 'NSE',
    name           text NOT NULL,
    instrument_type text NOT NULL,                 -- ETF | EQUITY | INDEX
    asset_class    text NOT NULL,                  -- EQUITY | COMMODITY | GLOBAL | DEBT | HYBRID
    country        text NOT NULL DEFAULT 'IN',     -- room for future non-Indian universes
    currency       text NOT NULL DEFAULT 'INR',
    lot_size       integer NOT NULL DEFAULT 1,
    tick_size      numeric(18,4),
    status         text NOT NULL DEFAULT 'ACTIVE', -- ACTIVE | BLOCKED | REVIEW (D-091)
    status_reason  text,
    status_changed_at timestamptz,
    CONSTRAINT instrument_uk UNIQUE (isin, exchange),
    CONSTRAINT instrument_status_ck CHECK (status IN ('ACTIVE','BLOCKED','REVIEW'))
);
```

*`status` carries the three-stage corporate-action lifecycle (D-091). `country` and `currency`
exist so a future US or other-market universe is a data change, not a migration.*

```sql
CREATE TABLE atom.broker_instrument (
    broker_instrument_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    broker_id      bigint NOT NULL REFERENCES atom.broker,
    instrument_id  bigint NOT NULL REFERENCES atom.instrument,
    broker_token   text   NOT NULL,   -- Upstox NSE_EQ|ISIN · Dhan securityId · Zerodha token
    broker_symbol  text   NOT NULL,
    tradable       boolean NOT NULL DEFAULT true,
    synced_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT broker_instrument_uk UNIQUE (broker_id, instrument_id),
    CONSTRAINT broker_instrument_token_uk UNIQUE (broker_id, broker_token)
);
```

> **This table is why five brokers are tractable.** Each broker identifies the same security
> differently — `NSE_EQ|INE002A01018`, a numeric security id, an instrument token. Resolution
> happens once, here, and the strategy engine only ever sees `instrument_id`.

```sql
CREATE TABLE atom.instrument_classification (
    instrument_id   bigint PRIMARY KEY REFERENCES atom.instrument,
    bucket          text NOT NULL,                 -- INDEX | SECTOR | FACTOR | COMMODITY | GLOBAL | EXCLUDED
    tier2_group     text NOT NULL,                 -- BANKING | LARGECAP_50 | GOLD …   (D-103)
    tier1_index     text NOT NULL,                 -- exact tracked index               (D-103)
    assignment_status text NOT NULL,               -- AUTO | MANUAL | UNASSIGNED        (D-108)
    assigned_by     text,
    assigned_at     timestamptz,
    CONSTRAINT classification_status_ck
        CHECK (assignment_status IN ('AUTO','MANUAL','UNASSIGNED'))
);
```

---

## 5. 🆕 Trading universes — a first-class entity (D-151)

> "There should be a trading-universe concept which has these securities, and at individual level
> you can run the model on one of the universes — or multiple, so you can compare which universe
> is working best."

This generalises what was previously a fixed ETF list. **The weekly volume-filtered ETF list
becomes one universe among several**, produced by an automated generator rather than being the
only thing the engine can trade.

```sql
CREATE TABLE atom.universe (
    universe_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name          text NOT NULL UNIQUE,
    description   text,
    source        text NOT NULL,        -- MANUAL | VOLUME_FILTER | IMPORTED     (D-151)
    country       text NOT NULL DEFAULT 'IN',
    status        text NOT NULL DEFAULT 'ACTIVE',
    created_by    text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT universe_source_ck CHECK (source IN ('MANUAL','VOLUME_FILTER','IMPORTED'))
);

CREATE TABLE atom.universe_category (
    universe_category_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    universe_id   bigint NOT NULL REFERENCES atom.universe ON DELETE CASCADE,
    category_code text NOT NULL,      -- EQUITY|COMMODITY|GLOBAL for the ETF universe;
                                      -- one row equal to the universe name for a manual one
    display_order integer NOT NULL,   -- the buy priority ordering (D-042)
    CONSTRAINT universe_category_uk UNIQUE (universe_id, category_code)
);
```

> **D-153 — a universe declares its own categories.** The ETF universe has three
> (EQUITY, COMMODITY, GLOBAL). A manually created universe has **exactly one — itself**. So
> "category" stops being a global enum and becomes a property of the universe, which is what
> lets a Nifty-50-stocks universe exist without inventing a bucket taxonomy for it.

```sql
-- SCD Type 2 membership: every change is a new row, nothing is updated in place (D-154)
CREATE TABLE atom.universe_member (
    universe_member_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    universe_id   bigint NOT NULL REFERENCES atom.universe ON DELETE CASCADE,
    instrument_id bigint NOT NULL REFERENCES atom.instrument,
    member_status text NOT NULL,                   -- ACTIVE | FROZEN
    valid_from    timestamptz NOT NULL DEFAULT now(),
    valid_to      timestamptz NOT NULL DEFAULT '9999-12-31 00:00:00+00',
    change_reason text,
    changed_by    text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT universe_member_status_ck CHECK (member_status IN ('ACTIVE','FROZEN')),
    CONSTRAINT universe_member_period_ck  CHECK (valid_to > valid_from)
);

-- at most one open row per (universe, instrument)
CREATE UNIQUE INDEX universe_member_current_uk
    ON atom.universe_member (universe_id, instrument_id)
    WHERE valid_to = '9999-12-31 00:00:00+00';

CREATE INDEX universe_member_asof_idx
    ON atom.universe_member (universe_id, valid_from, valid_to);
```

**Universe-level freeze is distinct from holdings-level freeze (D-062).**

| | Universe freeze | Holdings freeze |
|---|---|---|
| Object | An instrument's membership | A quantity you own |
| Meaning | "Don't consider this for new buys" | "Don't sell what I hold" |
| Effect | Excluded from ranking | Reduces sellable quantity |
| Typical use | Pause a sector for a quarter | Conviction hold |

Both are reversible **only by the operator** (D-084).

**Membership is SCD Type 2 (D-154).** Adding, freezing, unfreezing or removing an instrument
closes the current row (`valid_to = now()`) and opens a new one. Nothing is updated in place and
nothing is deleted, so:

```sql
-- what did this universe look like on 12 March?
SELECT instrument_id, member_status
FROM   atom.universe_member
WHERE  universe_id = :u
AND    :as_of >= valid_from AND :as_of < valid_to;
```

The open row carries `valid_to = '9999-12-31'`, so "currently active" is a plain predicate rather
than a special case. Freezing for a quarter and resuming afterwards leaves a complete, queryable
trail of exactly when and why.

### Snapshots — reproducibility

```sql
CREATE TABLE atom.universe_snapshot (
    snapshot_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    universe_id   bigint NOT NULL REFERENCES atom.universe,
    effective_from date NOT NULL,
    effective_to   date,
    generated_by  text NOT NULL,
    generated_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT universe_snapshot_uk UNIQUE (universe_id, effective_from)
);

CREATE TABLE atom.universe_snapshot_member (
    snapshot_id   bigint NOT NULL REFERENCES atom.universe_snapshot ON DELETE CASCADE,
    instrument_id bigint NOT NULL REFERENCES atom.instrument,
    avg_volume    numeric(18,4),
    PRIMARY KEY (snapshot_id, instrument_id)
);
```

*Every run records the snapshot it used (§8), so a decision from six months ago can be replayed
against exactly the universe that existed then — even after members have been added, frozen or
removed (D-058e).*

---

## 6. Configuration

```sql
CREATE TABLE atom.config_key (
    config_key_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key_name      text NOT NULL UNIQUE,
    scope         text NOT NULL,        -- ACCOUNT_CATEGORY | ACCOUNT | GLOBAL
    value_type    text NOT NULL,        -- NUMERIC | INTEGER | BOOLEAN | TEXT | ARRAY
    is_required   boolean NOT NULL DEFAULT true,
    suggested_value text,               -- UI pre-fill ONLY — never applied by the engine (D-038)
    description   text NOT NULL
);

CREATE TABLE atom.account_config (
    account_config_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trading_account_id bigint NOT NULL REFERENCES atom.trading_account,
    config_key_id  bigint NOT NULL REFERENCES atom.config_key,
    universe_id    bigint NOT NULL REFERENCES atom.universe,   -- D-155: config is per universe
    category_code  text,                -- a universe_category; NULL for account-level keys
    value_text     text,                -- NULL here means an explicit NULL (D-039)
    is_configured  boolean NOT NULL DEFAULT true,
    version        integer NOT NULL DEFAULT 1,
    updated_by     text NOT NULL,
    updated_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT account_config_uk
        UNIQUE (trading_account_id, universe_id, config_key_id, category_code)
);

CREATE TABLE atom.config_history (
    config_history_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_config_id bigint NOT NULL REFERENCES atom.account_config,
    old_value  text,
    new_value  text,
    changed_by text NOT NULL,
    changed_at timestamptz NOT NULL DEFAULT now()
);
```

> **D-155 — config is keyed by `(trading_account × universe × category)`.** One broker account
> can trade several universes, and each needs its own volume threshold, trade amount, profit
> target, depth and lookback. A ₹10,000 order size in the ETF universe and ₹1,00,000 in another
> is a normal configuration, not an exception.

> **`is_configured` is how D-039 becomes storable.** A row's *existence* means configured; its
> `value_text` may legitimately be NULL meaning "do not trade this". A missing row means
> unknown, and blocks the run. Those are three distinct states and the schema keeps them distinct.

---

## 7. Market data

```sql
CREATE TABLE atom.price_daily (
    instrument_id bigint NOT NULL REFERENCES atom.instrument,
    trade_date    date   NOT NULL,
    open_px  numeric(18,4), high_px numeric(18,4),
    low_px   numeric(18,4), close_px numeric(18,4) NOT NULL,
    volume        bigint,
    source        text NOT NULL,          -- UPSTOX | DHAN | YAHOO | NSE   (D-017)
    ingested_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, trade_date)
);
CREATE INDEX price_daily_date_idx ON atom.price_daily (trade_date DESC);

CREATE TABLE atom.nav_daily (
    instrument_id bigint NOT NULL REFERENCES atom.instrument,
    trade_date    date   NOT NULL,
    nav  numeric(18,4),
    inav numeric(18,4),
    is_interpolated boolean NOT NULL DEFAULT false,  -- D-058f: single-day gap filled
    PRIMARY KEY (instrument_id, trade_date)
);
```

*8 quarters retained on a rolling window (D-058a) — enforced by a scheduled purge, not a
constraint.*

---

## 8. Runs and decisions

```sql
-- D-172: a batch groups the runs created by one "execute all universes" click.
-- Selecting a single universe simply creates a batch of one.
CREATE TABLE atom.run_batch (
    run_batch_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    triggered_by text NOT NULL,
    triggered_at timestamptz NOT NULL DEFAULT now(),
    trade_date   date NOT NULL
);

CREATE TABLE atom.run (
    run_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_batch_id  bigint REFERENCES atom.run_batch,
    trading_account_id bigint NOT NULL REFERENCES atom.trading_account,
    universe_id   bigint NOT NULL REFERENCES atom.universe,
    snapshot_id   bigint REFERENCES atom.universe_snapshot,
    run_type      text NOT NULL,      -- EXECUTE | UNIVERSE_JOB | HARVEST | AVERAGE
    execution_mode text NOT NULL,     -- copied from the account, frozen at run start
    trade_date    date NOT NULL,
    status        text NOT NULL,      -- QUEUED | EXECUTING | COMPLETED | FAILED   (D-057f)
    config_snapshot jsonb NOT NULL,   -- fully resolved config, frozen (D-061)
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz,
    CONSTRAINT run_status_ck CHECK (status IN ('QUEUED','EXECUTING','COMPLETED','FAILED'))
);
CREATE UNIQUE INDEX run_one_execute_per_day_uk
    ON atom.run (trading_account_id, universe_id, trade_date)
    WHERE run_type = 'EXECUTE' AND status <> 'FAILED';
```

> **D-172 — one run per universe, batched when several are triggered together.** The partial
> unique index enforces one execute run per **(account, universe, day)**, so a day where only
> universe 1 runs and a day where universes 1 and 2 both run are both natural.
>
> "Execute all universes" creates a **`run_batch`** containing one run per selected universe;
> selecting a single universe creates a batch of one. Per-universe logs, status and P&L stay
> separate — the batch only groups them for the console, which shows the four states
> (QUEUED / EXECUTING / COMPLETED / FAILED, D-057f) **per run**, and rolls them up per batch.
>
> Runs within a batch execute **linearly**, not in parallel (D-057f).

```sql
CREATE TABLE atom.run_candidate (
    run_candidate_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id        bigint NOT NULL REFERENCES atom.run ON DELETE CASCADE,
    instrument_id bigint NOT NULL REFERENCES atom.instrument,
    category      text NOT NULL,
    rank          integer NOT NULL,
    mean_price    numeric(18,4) NOT NULL,
    median_price  numeric(18,4),
    ltp           numeric(18,4) NOT NULL,      -- snapshotted (D-052)
    deviation_pct numeric(18,4) NOT NULL,      -- percentage, 4dp (D-026/D-149)
    nav           numeric(18,4),
    nav_premium_pct numeric(18,4),
    holdings_status text,                      -- HELD | NOT_HELD | EXCLUDED
    gate_failed   text,                        -- NULL if it passed every gate
    decision      text NOT NULL,               -- BOUGHT | SKIPPED | NOT_CONSIDERED
    decision_reason text NOT NULL,
    CONSTRAINT run_candidate_uk UNIQUE (run_id, instrument_id)
);
```

*This is D-035 as a table: every gate's inputs and verdict, per candidate, so the decision is
reconstructible from SQL alone.*

---

## 9. Orders, fills and lots

```sql
CREATE TABLE atom.order_request (
    order_request_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id        bigint REFERENCES atom.run,
    trading_account_id bigint NOT NULL REFERENCES atom.trading_account,
    universe_id   bigint NOT NULL REFERENCES atom.universe,   -- D-156
    instrument_id bigint NOT NULL REFERENCES atom.instrument,
    side          text NOT NULL,        -- BUY | SELL
    order_kind    text NOT NULL,        -- LIMIT | GTT     (never MARKET — D-174)
    product       text NOT NULL DEFAULT 'DELIVERY',  -- 🆕 D-207: the only permitted value
    validity      text NOT NULL DEFAULT 'DAY',       -- 🆕
    quantity      integer NOT NULL CHECK (quantity > 0),
    limit_price   numeric(18,4) NOT NULL,
    trigger_price numeric(18,4),
    idempotency_key text NOT NULL UNIQUE,   -- written BEFORE sending (D-094)
    broker_order_id text,
    algo_id       text,                     -- unused, reserved (D-181)
    status        text NOT NULL,        -- INTENT | PLACED | PARTIAL | FILLED
                                        -- | CANCELLED | REJECTED | IN_FLIGHT  🆕
    reject_reason text,                 -- broker's verbatim reason (D-042)
    placed_at     timestamptz,
    CONSTRAINT order_side_ck CHECK (side IN ('BUY','SELL')),
    CONSTRAINT order_kind_ck CHECK (order_kind IN ('LIMIT','GTT')),
    CONSTRAINT order_product_ck CHECK (product = 'DELIVERY'),
    CONSTRAINT order_validity_ck CHECK (validity = 'DAY'),
    CONSTRAINT order_status_ck CHECK (status IN
        ('INTENT','PLACED','PARTIAL','FILLED','CANCELLED','REJECTED','IN_FLIGHT')),
    CONSTRAINT order_gtt_needs_trigger_ck
        CHECK ((order_kind = 'GTT') = (trigger_price IS NOT NULL))
);
```

> 🆕 **Three additions the implementation needed.**
>
> **`product` and `validity`**, each constrained to a single value. D-207 rules out
> margin, MTF, intraday and leverage everywhere, and without these columns the
> guarantee could only be inferred from the *absence* of a product field. An
> auditor reading an order row would have to take the design's word for it. Now
> the row says `DELIVERY` and the constraint refuses anything else.
>
> **`IN_FLIGHT` in the status set.** D-180 makes IN_FLIGHT the mandatory mapping
> for any broker status ATOM does not recognise, and it is never terminal. The
> documented status list here omitted it, which would have left the adapter layer
> producing a value the database rejects — so the first unfamiliar status from any
> broker would have failed the write rather than been recorded as unknown.
>
> **`order_gtt_needs_trigger_ck`**, an equivalence rather than two one-way checks:
> a GTT is *defined* by its trigger and a plain limit order has none, so the two
> nonsense rows are refused in one constraint.

```sql
CREATE TABLE atom.order_fill (
    order_fill_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_request_id bigint NOT NULL REFERENCES atom.order_request,
    quantity   integer NOT NULL CHECK (quantity > 0),
    fill_price numeric(18,4) NOT NULL,
    filled_at  timestamptz NOT NULL,
    broker_trade_id text
);

CREATE TABLE atom.position_lot (
    lot_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trading_account_id bigint NOT NULL REFERENCES atom.trading_account,
    universe_id   bigint NOT NULL REFERENCES atom.universe,   -- D-156: lots belong to a universe
    instrument_id bigint NOT NULL REFERENCES atom.instrument,
    buy_order_request_id bigint REFERENCES atom.order_request,
    order_fill_id bigint REFERENCES atom.order_fill,   -- D-166: one lot per fill
    quantity      integer NOT NULL CHECK (quantity > 0),
    quantity_open integer NOT NULL CHECK (quantity_open >= 0),
    unit_cost     numeric(18,4) NOT NULL,   -- all-in, incl. buy charges (D-076a)
    synthetic_cost_basis numeric(18,4),     -- harvest carry-over (D-019); NULL normally
    acquired_on   date NOT NULL,
    provenance    text NOT NULL,            -- ATOM | EXTERNAL   (D-062)
    status        text NOT NULL DEFAULT 'OPEN',
    CONSTRAINT lot_open_le_total_ck CHECK (quantity_open <= quantity)
);

CREATE TABLE atom.lot_closure (
    lot_closure_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lot_id        bigint NOT NULL REFERENCES atom.position_lot,
    sell_order_request_id bigint NOT NULL REFERENCES atom.order_request,
    quantity      integer NOT NULL CHECK (quantity > 0),
    unit_proceeds numeric(18,4) NOT NULL,
    closed_on     date NOT NULL,
    funds_credited_on date,                 -- OBSERVED, never assumed (D-050/D-080)
    CONSTRAINT lot_closure_uk UNIQUE (lot_id, sell_order_request_id)
);
```

### D-156 — Lots, and therefore sell orders, belong to a universe

One instrument can sit in several universes at once, and each maintains its **own average buy
price and its own sell target**:

| Step | Universe 1 | Universe 2 | Sell orders live at the broker |
|---|---|---|---|
| U1 buys 10 | 10 @ avg₁ | — | 1 order: 10 @ target(avg₁) |
| U2 buys 20 | 10 @ avg₁ | 20 @ avg₂ | **2 orders**: 10 @ target(avg₁), 20 @ target(avg₂) |
| U1 averages +10 | **20 @ avg₁′** | 20 @ avg₂ | 2 orders: **20 @ target(avg₁′)**, 20 @ target(avg₂) |

> ⚠️ **This supersedes D-055 ("one sell order per security").** The rule becomes **one sell order
> per (account, instrument, universe)**. Two consequences that need checking before build:
>
> 1. **Brokers may not permit multiple resting GTTs on the same instrument in one account.**
>    Unverified for all five. If a broker refuses, that account must either restrict an
>    instrument to one universe, or place a single blended sell — which would destroy per-universe
>    P&L attribution. (Q-257)
> 2. **The broker reports one aggregate holding**, not per-universe quantities. ATOM's universe
>    attribution is internal, so reconciliation matches the broker's total against the **sum** of
>    ATOM's lots across universes. A mismatch cannot say which universe is wrong — only that the
>    total is. (Q-258)

**Lots are the backbone.** Averaging creates a second lot rather than mutating the first
> (D-045); FIFO closes them in `acquired_on` order **within a trading account** (D-127);
> cost-of-capital accrues per lot; tax gains classify per closure. Position-level storage cannot
> express any of that, which is why `position` is a view, not a table (§12).

---

## 10. Cash, capital and charges

```sql
CREATE TABLE atom.cash_ledger (
    cash_ledger_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trading_account_id bigint NOT NULL REFERENCES atom.trading_account,
    entry_type text NOT NULL,   -- CAPITAL_IN | CAPITAL_OUT | PROFIT_WITHDRAWAL
                                -- | TRADE_BUY | TRADE_SELL | CHARGES | UNCLASSIFIED
    amount     numeric(18,4) NOT NULL,
    entry_date date NOT NULL,
    order_request_id bigint REFERENCES atom.order_request,
    source     text NOT NULL,   -- ATOM | BROKER_LEDGER | OPERATOR
    narration  text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT cash_entry_type_ck CHECK (entry_type IN
        ('CAPITAL_IN','CAPITAL_OUT','PROFIT_WITHDRAWAL','TRADE_BUY','TRADE_SELL',
         'CHARGES','UNCLASSIFIED'))
);
```

*`UNCLASSIFIED` exists because D-047 requires an unclassified withdrawal to **block** rather than
default. The row can be stored — losing broker ledger data would be worse — but the pre-flight
check refuses to run while any exists.*

```sql
CREATE TABLE atom.capital_rate (
    capital_rate_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trading_account_id bigint NOT NULL REFERENCES atom.trading_account,  -- D-053
    annual_rate_pct numeric(18,4) NOT NULL,
    effective_from  date NOT NULL,
    CONSTRAINT capital_rate_uk UNIQUE (trading_account_id, effective_from)
);

CREATE TABLE atom.capital_accrual_daily (
    trading_account_id bigint NOT NULL REFERENCES atom.trading_account,
    accrual_date date NOT NULL,
    principal_outstanding numeric(18,4) NOT NULL,
    deployed_amount   numeric(18,4) NOT NULL,
    settlement_amount numeric(18,4) NOT NULL,
    idle_amount       numeric(18,4) NOT NULL,
    rate_pct          numeric(18,4) NOT NULL,
    interest_total    numeric(18,4) NOT NULL,
    PRIMARY KEY (trading_account_id, accrual_date),
    CONSTRAINT accrual_buckets_ck
        CHECK (deployed_amount + settlement_amount + idle_amount = principal_outstanding)
);

-- D-169: deployed and settlement capital ARE attributable to a universe (via the lot).
-- Idle capital is NOT — it belongs to the account and to no universe.
CREATE TABLE atom.capital_accrual_universe_daily (
    trading_account_id bigint NOT NULL REFERENCES atom.trading_account,
    universe_id  bigint NOT NULL REFERENCES atom.universe,
    accrual_date date NOT NULL,
    deployed_amount   numeric(18,4) NOT NULL,
    settlement_amount numeric(18,4) NOT NULL,
    interest_amount   numeric(18,4) NOT NULL,
    PRIMARY KEY (trading_account_id, universe_id, accrual_date)
);
```

> **`accrual_buckets_ck` is D-080's invariant as a constraint.** The three buckets must sum to
> principal, every day. A bug that loses or duplicates capital between them cannot be written.

### D-169 — Capital is held at account level; reporting is three-tier

> "The capital will be at the account level but all the reporting will be at the universe level…
> if the amount was ₹60,000 and only ₹50,000 utilised, there is ₹10,000 idle cash. So idle-cash
> computation only comes at the account level, whereas the universe level should only have the
> pure profit-and-loss report."

```
account: ₹60,000 capital
   ├── universe 1 : ₹20,000 deployed   → P&L reported here
   ├── universe 2 : ₹30,000 deployed   → P&L reported here
   └── idle       : ₹10,000            → account level ONLY
```

| Report level | Contains |
|---|---|
| **Universe** | Pure P&L — what was bought, what was sold, when, realised and unrealised gain, charges, and the cost of capital on **its own deployed and settlement capital** |
| **Account** | All of the above summed, **plus idle-capital drag**, total principal, capital efficiency |
| **Investor (PAN)** | Tax only — gains pooled, set-off, exemption, liability (D-127) |

**Idle capital is deliberately unattributed.** It belongs to no universe, so charging it to one
would distort the comparison the universes exist to enable. `cash_ledger` therefore stays keyed
to the **trading account** with no `universe_id`: there is one real pot of money, and universes
draw from it.

```sql
CREATE TABLE atom.charge (
    charge_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_request_id bigint REFERENCES atom.order_request,
    trading_account_id bigint NOT NULL REFERENCES atom.trading_account,
    charge_type text NOT NULL,   -- BROKERAGE | STT | EXCHANGE | SEBI | STAMP | GST | DP
    amount      numeric(18,4) NOT NULL,
    source      text NOT NULL,   -- COMPUTED | BROKER   (D-024 contrast)
    charge_date date NOT NULL,
    CONSTRAINT charge_source_ck CHECK (source IN ('COMPUTED','BROKER'))
);
```

*Both sources coexist as separate rows for the same order — that **is** the computed-vs-reported
contrast (D-024), and it is why `charge` is not unique on `(order, type)`.*

---

## 10a. Broker sessions — daily tokens (D-170)

> "Make a call to fetch the holdings. If the call fails, that is probably an invalid token… once
> the run is complete you clear up the tokens."

```sql
CREATE TABLE atom.broker_session (
    broker_session_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
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
    CONSTRAINT broker_session_no_secret_ck
        CHECK (secret_ref IS NULL OR secret_ref NOT LIKE '%Bearer%')
);
```

**Validity is tested, not assumed.** There is no expiry arithmetic and no trust in a documented
token lifetime — ATOM calls **holdings**, and a failure means the token is invalid. That probe is
cheap, read-only, and it exercises exactly the path a real call will take, including the proxy
and the whitelisted IP.

**Lifecycle**

```
morning   operator generates the token per account → status VALID, secret_ref stored in SSM
during    every call uses it; a failure flips status to INVALID and blocks that account
run ends  token is destroyed in SSM → status CLEARED
```

With two investors across three brokers, that is **five accounts, five tokens, cleared daily**.
Clearing after the run means a stolen database yields nothing: the row holds only a path, and
the parameter behind it no longer exists.

*`broker_session_no_secret_ck` is a crude belt-and-braces guard — it cannot prove a token was not
stored, but it makes the most obvious mistake fail loudly.*

---

## 10b. Tax ledger (D-171)

Separate from the universe ledger by design (D-167). This is the **per-demat-account FIFO**
computation, aggregated to the **PAN** (D-127).

```sql
-- One row per taxable disposal, matched under TAX FIFO — not universe FIFO
CREATE TABLE atom.tax_gain (
    tax_gain_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trading_account_id bigint NOT NULL REFERENCES atom.trading_account,
    investor_id  bigint NOT NULL REFERENCES atom.investor,
    instrument_id bigint NOT NULL REFERENCES atom.instrument,
    financial_year text NOT NULL,          -- '2026-27'
    quantity     integer NOT NULL,
    acquired_on  date NOT NULL,
    disposed_on  date NOT NULL,
    holding_days integer NOT NULL,
    cost_basis   numeric(18,4) NOT NULL,   -- incl. deductible buy charges
    proceeds     numeric(18,4) NOT NULL,   -- net of deductible sell charges
    stt_paid     numeric(18,4) NOT NULL,   -- recorded but NOT deducted (D-127)
    gain_amount  numeric(18,4) NOT NULL,
    term         text NOT NULL,            -- SHORT | LONG
    tax_bucket   text NOT NULL,            -- EQUITY | COMMODITY | GLOBAL
    provenance   text NOT NULL,            -- ATOM | EXTERNAL   (D-123)
    computed_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT tax_gain_term_ck CHECK (term IN ('SHORT','LONG'))
);

-- Losses available to offset, by type and vintage; 8-year carry-forward window
CREATE TABLE atom.tax_loss_pool (
    tax_loss_pool_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    investor_id  bigint NOT NULL REFERENCES atom.investor,
    financial_year text NOT NULL,          -- year the loss AROSE
    term         text NOT NULL,            -- SHORT | LONG
    amount_original  numeric(18,4) NOT NULL,
    amount_remaining numeric(18,4) NOT NULL,
    expires_after_fy text NOT NULL,        -- 8 assessment years
    CONSTRAINT tax_loss_remaining_ck CHECK (amount_remaining >= 0),
    CONSTRAINT tax_loss_le_original_ck CHECK (amount_remaining <= amount_original)
);

-- How each loss was applied; the audit trail of the set-off ordering (D-127)
CREATE TABLE atom.tax_setoff (
    tax_setoff_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    investor_id  bigint NOT NULL REFERENCES atom.investor,
    financial_year text NOT NULL,          -- year the set-off was APPLIED
    tax_loss_pool_id bigint REFERENCES atom.tax_loss_pool,
    tax_gain_id  bigint REFERENCES atom.tax_gain,
    amount       numeric(18,4) NOT NULL CHECK (amount > 0),
    sequence_no  integer NOT NULL,         -- current-year first, then oldest vintage
    applied_at   timestamptz NOT NULL DEFAULT now()
);

-- ₹1.25 lakh equity LTCG exemption — once per PAN per FY (D-127)
CREATE TABLE atom.tax_exemption_usage (
    investor_id  bigint NOT NULL REFERENCES atom.investor,
    financial_year text NOT NULL,
    exemption_limit  numeric(18,4) NOT NULL,   -- config-driven (D-122)
    consumed_amount  numeric(18,4) NOT NULL DEFAULT 0,
    PRIMARY KEY (investor_id, financial_year),
    CONSTRAINT exemption_not_exceeded_ck CHECK (consumed_amount <= exemption_limit)
);

-- The computed liability, per PAN per FY — the output of the whole engine
CREATE TABLE atom.tax_computation (
    tax_computation_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    investor_id  bigint NOT NULL REFERENCES atom.investor,
    financial_year text NOT NULL,
    stcg_equity  numeric(18,4) NOT NULL DEFAULT 0,
    stcg_commodity numeric(18,4) NOT NULL DEFAULT 0,
    stcg_global  numeric(18,4) NOT NULL DEFAULT 0,
    ltcg_equity  numeric(18,4) NOT NULL DEFAULT 0,
    ltcg_commodity numeric(18,4) NOT NULL DEFAULT 0,
    ltcg_global  numeric(18,4) NOT NULL DEFAULT 0,
    exemption_applied numeric(18,4) NOT NULL DEFAULT 0,
    setoff_applied    numeric(18,4) NOT NULL DEFAULT 0,
    tax_before_surcharge numeric(18,4) NOT NULL,
    surcharge    numeric(18,4) NOT NULL DEFAULT 0,
    cess         numeric(18,4) NOT NULL,
    total_liability numeric(18,4) NOT NULL,
    computed_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT tax_computation_uk UNIQUE (investor_id, financial_year, computed_at)
);
```

**Why six tables rather than one.** Each answers a different question and they have different
lifetimes: `tax_gain` is a fact about a disposal; `tax_loss_pool` survives up to eight years;
`tax_setoff` records *how* a liability was reduced; `tax_exemption_usage` is a per-PAN annual
allowance; `tax_computation` is a point-in-time result that is recomputed as more trades land.
Collapsing them would lose the audit trail the engine exists to provide.

Note `tax_gain` carries **no `universe_id`** — deliberately. Tax does not know about universes,
and matching under tax FIFO may pair a disposal with a lot from a different universe (D-167).

---

## 11. Exclusions, harvests, audit and logs

```sql
CREATE TABLE atom.account_exclusion (
    account_exclusion_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trading_account_id bigint NOT NULL REFERENCES atom.trading_account,
    instrument_id bigint NOT NULL REFERENCES atom.instrument,
    exclusion_type text NOT NULL,        -- EXCLUSION (not ours) | FREEZE (ours, held)  (D-062)
    quantity integer NOT NULL CHECK (quantity > 0),
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    released_at timestamptz,             -- never auto-set (D-084)
    CONSTRAINT exclusion_type_ck CHECK (exclusion_type IN ('EXCLUSION','FREEZE'))
);

CREATE TABLE atom.harvest_chain (
    harvest_chain_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sold_lot_id  bigint NOT NULL REFERENCES atom.position_lot,
    proxy_lot_id bigint REFERENCES atom.position_lot,
    correlation  numeric(18,4),          -- NULL in v1 (D-163); V2-14 restores it
    proxy_tier   text,                   -- NULL in v1 (D-163); TIER1 | TIER2 in V2-14
    booked_loss  numeric(18,4) NOT NULL,
    carried_basis_amount numeric(18,4),  -- D-188: what the synthetic basis carries forward
    chain_depth  integer NOT NULL DEFAULT 1,   -- D-193: always 1; chaining is not allowed
    selected_by  text,                   -- operator who chose the pairing (D-163)
    status       text NOT NULL,          -- PROPOSED | EXECUTED | INCOMPLETE  (D-070b)
    approved_by  text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT harvest_no_chaining_ck CHECK (chain_depth = 1),           -- 🆕 D-193
    CONSTRAINT harvest_not_self_ck CHECK (proxy_lot_id IS DISTINCT FROM sold_lot_id),
    CONSTRAINT harvest_executed_complete_ck                              -- 🆕 D-070b
        CHECK (status <> 'EXECUTED'
               OR (proxy_lot_id IS NOT NULL AND carried_basis_amount IS NOT NULL))
);

> ⚠️ **`correlation` and `proxy_tier` were `NOT NULL` until 2026-09-25.** They were written
> before D-163 made proxy selection manual — "no predefined proxy buckets, no correlation floor,
> no automatic matching in v1" — so they demanded data v1 never computes. Now nullable; they
> stay in the schema because V2-14 restores correlation matching.
>
> `carried_basis_amount` is **stored, not recomputed.** It is the number that explains a lot's
> synthetic cost basis, and re-deriving it years later would depend on data that may have been
> corrected since. See [`HARVEST-COST-BASIS.md`](../04-strategy/HARVEST-COST-BASIS.md).

CREATE TABLE atom.action_audit (
    action_audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor      text NOT NULL,
    action     text NOT NULL,
    entity     text NOT NULL,
    entity_id  bigint,
    payload    jsonb,
    occurred_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE atom.run_log (
    run_log_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id     bigint NOT NULL REFERENCES atom.run ON DELETE CASCADE,
    level      text NOT NULL,
    stage      text NOT NULL,
    message    text NOT NULL,
    context    jsonb,
    logged_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX run_log_purge_idx ON atom.run_log (logged_at);
```

*`run_log` is the only table subject to the 90-day purge (D-030/D-073d). Trade, order, lot,
charge and audit tables are retained indefinitely.*

---

## 12. Derived views — deliberately not tables

Defined in [`0012_views.sql`](../../atom/persistence/migrations/0012_views.sql).

| View | Grain | Derived from | Why not stored |
|---|---|---|---|
| `v_position` | account × universe × instrument | open `position_lot` rows | Storing it invites divergence from the lots that define it |
| `v_sellable_quantity` | account × instrument | positions − `account_exclusion` | D-062's formula; one definition, one place |
| `v_cash_balance` | account | `cash_ledger` sum | D-046 reconstruction |
| `v_realised_gain` | one row per closure | `lot_closure` + `position_lot` + `charge` | Tax classification derives from it |

Three properties they share, each a decision rather than an implementation detail:

**Both cost bases, never blended.** `v_position` returns `actual_unit_cost` *and*
`strategy_unit_cost`, plus `synthetic_quantity` and `actual_quantity` — which are
the two sell tranches of D-195. A single blended average is the phantom-profit bug
the tranches exist to prevent, so the view does not offer one.

**Nothing coalesces to zero.** Where a broker reported no charges, `v_realised_gain`
returns `NULL`, not `0`. `₹0.00` claims no charge was levied; a dash says we cannot
know. The `SUM` over an empty set already gives NULL, so the correct behaviour is
achieved by *not* writing `COALESCE` — which is easy to add by reflex and is why it
is called out here.

**`v_sellable_quantity` does not clamp.** `holding − excluded − frozen` can go
negative when the withheld quantity exceeds what is held. `GREATEST(…, 0)` would
hide exactly the condition Q-181 is open about, so the subtraction is reported raw.

**All four are `security_invoker = true`.** A view otherwise runs with its owner's
privileges, and the owner bypasses RLS — so without it the views would be a route
around every policy in §12a.

---

## 12a. Access control — roles, grants and RLS

Applied by [`0014_roles_and_rls.sql`](../../atom/persistence/migrations/0014_roles_and_rls.sql).
Design rationale in [`../06-web/AUTH-AND-ACCESS.md`](../06-web/AUTH-AND-ACCESS.md) §4.

**`atom_engine` is `NOLOGIN`.** No credential appears in the repository. A login
role is created out of band and granted membership:

```sql
CREATE ROLE atom_api LOGIN PASSWORD '…' IN ROLE atom_engine;
```

Never `postgres`, and never reachable from a browser — the browser holds no
database key at all, so there is one authorisation point rather than two.

**Nine tables are append-only to the engine**, with `UPDATE` revoked:
`run_candidate`, `order_fill`, `lot_closure`, `charge`, `config_history`,
`action_audit`, `tax_gain`, `tax_setoff`, `tax_computation`. These hold the record
of a decision taken or a return filed, and a bug that could amend them would
rewrite the evidence rather than add to it.

One column-level exception: `GRANT UPDATE (funds_credited_on) ON atom.lot_closure`.
Settlement is *observed* when the ledger shows it and is not knowable when the lot
closes (D-050/D-080), so that one field is filled in later — and only that one.

**`run_log` is the only table the engine may `DELETE` from.** That is not a
coincidence: it is the only table holding no decision record, which is precisely
what makes it safe to purge on the archival schedule.

**RLS is enabled on all 38 tables**, each with one policy — `atom_engine_all`,
`USING (true)`. That policy isolates nothing today, and saying otherwise would be
dishonest: v1 is admin-only (D-040). What it buys is that every table *already*
denies by default to any role without a policy, so V2-5's investor-scoped read
access becomes a policy to add rather than a migration across 38 tables that has
to hope none was missed (Q-074).

The `ENABLE ROW LEVEL SECURITY` and `CREATE POLICY` statements are generated from
`pg_class` in a `DO` loop rather than written out 38 times, so a table added by a
later migration cannot be omitted by a typo. `verify_constraints.sql` asserts the
count anyway.

**Two deliberate denormalisations**, both for auditability:

1. **`run.config_snapshot jsonb`** duplicates `account_config` at run time. Intentional — the
   config will change, and a six-month-old decision must still be explicable (D-061).
2. **`universe_snapshot_member`** duplicates membership. Same reason (D-058e).

Both store *history that must not move*, which is the legitimate case for duplication.

---

## 13. Invariants enforced by the database

| # | Invariant | Mechanism | Decision |
|---|---|---|---|
| 1 | A LIVE account has an egress IP and proxy | `trading_account_live_needs_proxy_ck` | D-136 |
| 2 | Capital buckets sum to principal, daily | `accrual_buckets_ck` | D-080 |
| 3 | One execute run per account/universe/day | partial unique index | D-057e |
| 4 | An order is never sent twice | `idempotency_key` UNIQUE | D-094 |
| 5 | Open quantity never exceeds lot quantity | `lot_open_le_total_ck` | D-045 |
| 6 | Relationship inside SEBI's family definition | `investor_relationship_ck` | D-092 |
| 7 | Full PAN cannot be stored | `investor_pan_masked_ck` regex | D-128 |
| 8 | Paper and live never mix | `execution_mode` on the account, inherited by FK | D-041 |
| 9 | MARKET orders cannot be stored | `order_kind_ck` — the value is absent, not flagged | D-174 |
| 10 | No margin, MTF, intraday or leverage | `order_product_ck`, single-valued `DELIVERY` | D-207 |
| 11 | A harvest is never chained | `harvest_no_chaining_ck` — `CHECK (chain_depth = 1)` | D-193 |
| 12 | One lot per fill | partial unique index on `order_fill_id` | D-166 |
| 13 | A closed lot and an exhausted lot are one fact | `lot_status_matches_open_ck` | — |
| 14 | A session row holds a path, never a token | `broker_session_is_ssm_path_ck` regex | D-079 |
| 15 | A stated gain agrees with its own inputs | `tax_gain_amount_ck`, `tax_computation_total_ck` | — |
| 16 | A gated candidate was not also acted on | `run_candidate_gate_ck` | D-052 |
| 17 | A decision record cannot be amended | `UPDATE` revoked on nine tables | §12a |

Numbers 1–8 were designed here. Numbers 9–17 were added while writing the
migrations, each because a decision already taken had no mechanism behind it.

### Proving they fire

A constraint nobody has watched reject a row is a comment, not an invariant.
[`verify_constraints.sql`](../../atom/persistence/migrations/verify_constraints.sql)
runs 23 statements that must be rejected — each asserted against the *named*
constraint, so a row refused for the wrong reason fails the test — and 21 positive
assertions, including that a `FAILED` run does not consume the day's execute slot,
that `v_position` reports ₹200.20 strategy cost against ₹85.00 actual cost on a
harvest proxy, and that an over-exclusion surfaces as `-3` rather than `0`.

It runs inside a transaction and rolls back, and it is pure SQL with no psql
meta-commands, so the same file works through `make db-verify` and through a
single-statement SQL API.

---

## 14. Open questions

Raised in [`DECISIONS.md`](../00-discovery/DECISIONS.md) round 23 — Q-247 … Q-256.
