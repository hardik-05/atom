# Database Schema

**Status:** 🟢 v1 design · PostgreSQL (Supabase)
**Implements:** D-150 · the gate for all application code
**Convention:** schema `atom`, snake_case, `NUMERIC(18,4)` money, `timestamptz` UTC (D-073c)

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
CREATE TABLE atom.run (
    run_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
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

> The partial unique index enforces **one execute run per account per universe per day**
> (D-057e). Where the operator enables multiple runs, the index is dropped by migration rather
> than worked around in code.

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
    order_kind    text NOT NULL,        -- LIMIT | GTT
    quantity      integer NOT NULL CHECK (quantity > 0),
    limit_price   numeric(18,4) NOT NULL,
    trigger_price numeric(18,4),
    idempotency_key text NOT NULL UNIQUE,   -- written BEFORE sending (D-094)
    broker_order_id text,
    algo_id       text,                     -- unused, reserved (D-089)
    status        text NOT NULL,        -- INTENT | PLACED | PARTIAL | FILLED | CANCELLED | REJECTED
    reject_reason text,                 -- broker's verbatim reason (D-042)
    placed_at     timestamptz,
    CONSTRAINT order_side_ck CHECK (side IN ('BUY','SELL'))
);

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
```

> **`accrual_buckets_ck` is D-080's invariant as a constraint.** The three buckets must sum to
> principal, every day. A bug that loses or duplicates capital between them cannot be written.

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
    correlation  numeric(18,4) NOT NULL,
    proxy_tier   text NOT NULL,          -- TIER1 | TIER2   (D-103)
    booked_loss  numeric(18,4) NOT NULL,
    status       text NOT NULL,          -- PROPOSED | EXECUTED | INCOMPLETE  (D-070b)
    approved_by  text,
    created_at   timestamptz NOT NULL DEFAULT now()
);

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

| View | Derived from | Why not stored |
|---|---|---|
| `v_position` | `position_lot` where `quantity_open > 0` | Storing it invites divergence from the lots that define it |
| `v_sellable_quantity` | `v_position` − `account_exclusion` | D-062's formula; one definition, one place |
| `v_cash_balance` | `cash_ledger` running sum | D-046 reconstruction |
| `v_realised_gain` | `lot_closure` + `charge` | Tax classification derives from it |

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

---

## 14. Open questions

Raised in [`DECISIONS.md`](../00-discovery/DECISIONS.md) round 23 — Q-247 … Q-256.
