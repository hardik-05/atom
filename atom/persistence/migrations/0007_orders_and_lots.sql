-- 0007_orders_and_lots.sql
-- Orders, fills, lots and closures.
--
-- Three rules shape these tables:
--   D-094  the intent is written BEFORE the order is sent, so a crash between
--          write and send leaves evidence rather than a silent gap
--   D-166  one lot per fill — never one lot per order
--   D-156  a lot belongs to a universe, and therefore so does every sell
--
-- `order_kind` admits LIMIT and GTT only. MARKET is absent from the constraint
-- for the same reason it is absent from OrderKind in atom/domain/enums.py: its
-- absence IS the enforcement of D-174.

CREATE TABLE atom.order_request (
    order_request_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id             bigint REFERENCES atom.run,
    trading_account_id bigint NOT NULL REFERENCES atom.trading_account,
    universe_id        bigint NOT NULL REFERENCES atom.universe,   -- D-156
    instrument_id      bigint NOT NULL REFERENCES atom.instrument,
    side               text NOT NULL,        -- BUY | SELL
    order_kind         text NOT NULL,        -- LIMIT | GTT     (never MARKET — D-174)
    product            text NOT NULL DEFAULT 'DELIVERY',  -- D-207: the only permitted value
    validity           text NOT NULL DEFAULT 'DAY',
    quantity           integer NOT NULL CHECK (quantity > 0),
    limit_price        numeric(18,4) NOT NULL,
    trigger_price      numeric(18,4),
    idempotency_key    text NOT NULL UNIQUE,   -- written BEFORE sending (D-094)
    broker_order_id    text,
    algo_id            text,                   -- unused, reserved (D-181)
    status             text NOT NULL,
    reject_reason      text,                   -- broker's verbatim reason (D-042)
    placed_at          timestamptz,
    CONSTRAINT order_side_ck CHECK (side IN ('BUY','SELL')),
    CONSTRAINT order_kind_ck CHECK (order_kind IN ('LIMIT','GTT')),
    CONSTRAINT order_product_ck CHECK (product = 'DELIVERY'),
    CONSTRAINT order_validity_ck CHECK (validity = 'DAY'),
    CONSTRAINT order_limit_price_ck CHECK (limit_price > 0),
    CONSTRAINT order_status_ck CHECK (status IN
        ('INTENT','PLACED','PARTIAL','FILLED','CANCELLED','REJECTED','IN_FLIGHT')),
    -- A GTT is defined by its trigger; a plain limit order has none.
    CONSTRAINT order_gtt_needs_trigger_ck
        CHECK ((order_kind = 'GTT') = (trigger_price IS NOT NULL)),
    CONSTRAINT order_trigger_price_ck CHECK (trigger_price IS NULL OR trigger_price > 0)
);

COMMENT ON CONSTRAINT order_kind_ck ON atom.order_request IS
    'D-174: MARKET is absent, not disallowed by a flag. Market orders have not been permitted via '
    'Indian broker APIs since 1 April 2026, and a value the constraint rejects cannot be stored '
    'by a future code path that forgets.';
COMMENT ON CONSTRAINT order_product_ck ON atom.order_request IS
    'D-207: delivery/CNC only. No margin, MTF, intraday or leverage anywhere in the system. The '
    'column is single-valued so an audit can read the guarantee off the order row itself.';
COMMENT ON COLUMN atom.order_request.status IS
    'D-180: IN_FLIGHT is the mandatory mapping for any broker status ATOM does not recognise. It '
    'is never terminal. Mapping an unknown status to CANCELLED or REJECTED would make ATOM '
    're-place an order that is about to fill.';
COMMENT ON COLUMN atom.order_request.idempotency_key IS
    'ATOM''s client_ref: 8-20 alphanumeric, at most two hyphens (D-175). Written before the send '
    '(D-094) and UNIQUE, which is invariant 4 — an order is never sent twice.';
COMMENT ON COLUMN atom.order_request.algo_id IS
    'D-181: reserved and unset. No Algo ID is required for this system - one order per second is '
    'far below the ten-per-second threshold the circular addresses.';

CREATE TABLE atom.order_fill (
    order_fill_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_request_id bigint NOT NULL REFERENCES atom.order_request,
    quantity        integer NOT NULL CHECK (quantity > 0),
    fill_price      numeric(18,4) NOT NULL,
    filled_at       timestamptz NOT NULL,
    broker_trade_id text,
    CONSTRAINT order_fill_price_ck CHECK (fill_price > 0)
);

-- ---------------------------------------------------------------------------
-- position_lot — one row per FILL (D-166), carrying TWO cost bases
-- ---------------------------------------------------------------------------
CREATE TABLE atom.position_lot (
    lot_id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trading_account_id   bigint NOT NULL REFERENCES atom.trading_account,
    universe_id          bigint NOT NULL REFERENCES atom.universe,  -- D-156
    instrument_id        bigint NOT NULL REFERENCES atom.instrument,
    buy_order_request_id bigint REFERENCES atom.order_request,
    order_fill_id        bigint REFERENCES atom.order_fill,   -- D-166: one lot per fill
    quantity             integer NOT NULL CHECK (quantity > 0),
    quantity_open        integer NOT NULL CHECK (quantity_open >= 0),
    unit_cost            numeric(18,4) NOT NULL,   -- all-in, incl. buy charges (D-076a)
    synthetic_cost_basis numeric(18,4),            -- harvest carry-over (D-019); NULL normally
    acquired_on          date NOT NULL,
    provenance           text NOT NULL,            -- ATOM | EXTERNAL   (D-062)
    status               text NOT NULL DEFAULT 'OPEN',
    -- Invariant 5: open quantity never exceeds lot quantity.
    CONSTRAINT lot_open_le_total_ck CHECK (quantity_open <= quantity),
    CONSTRAINT lot_provenance_ck CHECK (provenance IN ('ATOM','EXTERNAL')),
    CONSTRAINT lot_status_ck CHECK (status IN ('OPEN','CLOSED')),
    -- CLOSED and exhausted are the same fact, so they cannot disagree.
    CONSTRAINT lot_status_matches_open_ck CHECK ((status = 'CLOSED') = (quantity_open = 0)),
    CONSTRAINT lot_unit_cost_ck CHECK (unit_cost > 0),
    CONSTRAINT lot_synthetic_basis_ck
        CHECK (synthetic_cost_basis IS NULL OR synthetic_cost_basis > 0),
    -- D-166: an ATOM lot comes from a fill; an EXTERNAL lot was found on the account.
    CONSTRAINT lot_one_per_fill_ck
        CHECK (provenance = 'EXTERNAL' OR order_fill_id IS NOT NULL)
);

-- D-166: one lot per fill, enforced rather than assumed.
CREATE UNIQUE INDEX position_lot_fill_uk
    ON atom.position_lot (order_fill_id)
    WHERE order_fill_id IS NOT NULL;

COMMENT ON COLUMN atom.position_lot.unit_cost IS
    'D-076a: the ACTUAL all-in cost, including buy charges. Drives tax, cash P&L and '
    'cost-of-capital. Never the deviation or the sell trigger.';
COMMENT ON COLUMN atom.position_lot.synthetic_cost_basis IS
    'D-019/D-188: set only on a harvest proxy lot, where it carries forward the capital committed '
    'to the security that was harvested. Drives deviation, the sell trigger, the GTT price and '
    'averaging. NULL on every normally bought lot - and NULL means "use unit_cost", not zero.';
COMMENT ON COLUMN atom.position_lot.provenance IS
    'D-062: ATOM bought it, or reconciliation found it. An EXTERNAL lot has no fill of ours, '
    'which is why order_fill_id is nullable only for that case.';

CREATE TABLE atom.lot_closure (
    lot_closure_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lot_id                bigint NOT NULL REFERENCES atom.position_lot,
    sell_order_request_id bigint NOT NULL REFERENCES atom.order_request,
    quantity              integer NOT NULL CHECK (quantity > 0),
    unit_proceeds         numeric(18,4) NOT NULL,
    closed_on             date NOT NULL,
    funds_credited_on     date,               -- OBSERVED, never assumed (D-050/D-080)
    CONSTRAINT lot_closure_uk UNIQUE (lot_id, sell_order_request_id),
    CONSTRAINT lot_closure_proceeds_ck CHECK (unit_proceeds > 0),
    CONSTRAINT lot_closure_credit_after_close_ck
        CHECK (funds_credited_on IS NULL OR funds_credited_on >= closed_on)
);

COMMENT ON COLUMN atom.lot_closure.funds_credited_on IS
    'D-050/D-080: OBSERVED from the broker ledger, never computed as closed_on + 1. Settlement '
    'slips, and a computed date would move money into the idle bucket before it exists.';
