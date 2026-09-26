-- 0012_views.sql
-- The four derived figures are views, not tables (DATABASE-SCHEMA.md section 12).
-- Storing them invites divergence from the lots and ledger lines that define them.
--
-- One rule runs through all four: nothing is coalesced to zero. Where a figure
-- cannot be known, the view returns NULL, so the UI can render a dash. Rs 0.00
-- reads as "no charge was levied"; a dash reads as "we cannot know" - and
-- conflating them makes a report actively misleading (CHARGES-MODEL.md section 4.2).
--
-- All four are `security_invoker = true`. Without it a view runs with its owner's
-- privileges, and the owner bypasses RLS - so the views would be a way round the
-- policies in 0014 the moment those policies stop being `USING (true)`.

-- ---------------------------------------------------------------------------
-- v_position — open lots, aggregated, with BOTH cost bases (D-190)
-- ---------------------------------------------------------------------------
CREATE VIEW atom.v_position WITH (security_invoker = true) AS
SELECT
    l.trading_account_id,
    l.universe_id,
    l.instrument_id,
    SUM(l.quantity_open)                                    AS quantity_open,
    COUNT(*)                                                AS lot_count,
    -- The ACTUAL average: drives tax, cash P&L and cost of capital (D-076a).
    ROUND(SUM(l.quantity_open * l.unit_cost)
          / SUM(l.quantity_open), 4)                        AS actual_unit_cost,
    -- The STRATEGY average: drives deviation, the sell trigger and the GTT price.
    -- A harvest proxy contributes its synthetic basis; every other lot its actual cost.
    ROUND(SUM(l.quantity_open * COALESCE(l.synthetic_cost_basis, l.unit_cost))
          / SUM(l.quantity_open), 4)                        AS strategy_unit_cost,
    SUM(l.quantity_open) FILTER (WHERE l.synthetic_cost_basis IS NOT NULL)
                                                            AS synthetic_quantity,
    SUM(l.quantity_open) FILTER (WHERE l.synthetic_cost_basis IS NULL)
                                                            AS actual_quantity,
    MIN(l.acquired_on)                                      AS first_acquired_on,
    bool_or(l.provenance = 'EXTERNAL')                       AS has_external_lots
FROM atom.position_lot l
WHERE l.quantity_open > 0
GROUP BY l.trading_account_id, l.universe_id, l.instrument_id;

COMMENT ON VIEW atom.v_position IS
    'D-190: two averages, never blended into one. A blended average would sell a harvest proxy '
    'against a figure below the capital it carries, booking a loss as a gain - which is the exact '
    'phantom-profit bug D-195 exists to prevent. synthetic_quantity and actual_quantity are the '
    'two sell tranches.';

-- ---------------------------------------------------------------------------
-- v_sellable_quantity — D-062's formula, in one place
-- ---------------------------------------------------------------------------
-- Exclusions are per (account, instrument) and carry no universe, because the
-- demat holding they protect carries none either. Sellable quantity is therefore
-- an account-level figure, and a universe's share of it is decided above this view.
CREATE VIEW atom.v_sellable_quantity WITH (security_invoker = true) AS
WITH held AS (
    SELECT trading_account_id, instrument_id, SUM(quantity_open) AS quantity_open
    FROM atom.position_lot
    WHERE quantity_open > 0
    GROUP BY 1, 2
),
withheld AS (
    SELECT trading_account_id, instrument_id,
           SUM(quantity) FILTER (WHERE exclusion_type = 'EXCLUSION') AS excluded_quantity,
           SUM(quantity) FILTER (WHERE exclusion_type = 'FREEZE')    AS frozen_quantity,
           SUM(quantity)                                             AS withheld_quantity
    FROM atom.account_exclusion
    WHERE released_at IS NULL
    GROUP BY 1, 2
)
SELECT
    h.trading_account_id,
    h.instrument_id,
    h.quantity_open,
    w.excluded_quantity,
    w.frozen_quantity,
    h.quantity_open - COALESCE(w.withheld_quantity, 0) AS sellable_quantity
FROM held h
LEFT JOIN withheld w
       ON w.trading_account_id = h.trading_account_id
      AND w.instrument_id      = h.instrument_id;

COMMENT ON VIEW atom.v_sellable_quantity IS
    'D-062: sellable = holding - excluded - frozen, and the subtraction is NOT clamped at zero. '
    'A negative result means the withheld quantity exceeds what is held - a real condition worth '
    'surfacing rather than hiding, and the subject of open question Q-181.';

-- ---------------------------------------------------------------------------
-- v_cash_balance — D-046 reconstruction from the ledger
-- ---------------------------------------------------------------------------
CREATE VIEW atom.v_cash_balance WITH (security_invoker = true) AS
SELECT
    trading_account_id,
    SUM(amount)                                                  AS balance,
    SUM(amount) FILTER (WHERE entry_type IN ('CAPITAL_IN','CAPITAL_OUT')) AS net_capital,
    SUM(amount) FILTER (WHERE entry_type = 'PROFIT_WITHDRAWAL')   AS withdrawn,
    COUNT(*)    FILTER (WHERE entry_type = 'UNCLASSIFIED')        AS unclassified_count,
    MAX(entry_date)                                               AS last_entry_date
FROM atom.cash_ledger
GROUP BY trading_account_id;

COMMENT ON VIEW atom.v_cash_balance IS
    'D-046: the balance is reconstructed from the ledger, never stored. unclassified_count is '
    'exposed here on purpose - a balance that agrees with the broker while unclassified lines sit '
    'in the ledger is agreement by luck.';

-- ---------------------------------------------------------------------------
-- v_realised_gain — closures, with sell charges allocated pro rata
-- ---------------------------------------------------------------------------
-- A sell order can close several lots, so its charges are allocated across the
-- closures by proceeds. Where the broker reported no charges, the allocated
-- figure is NULL rather than zero.
CREATE VIEW atom.v_realised_gain WITH (security_invoker = true) AS
WITH order_proceeds AS (
    SELECT sell_order_request_id, SUM(quantity * unit_proceeds) AS total_proceeds
    FROM atom.lot_closure
    GROUP BY 1
),
order_charges AS (
    SELECT order_request_id,
           SUM(amount) FILTER (WHERE source = 'BROKER')   AS broker_charges,
           SUM(amount) FILTER (WHERE source = 'COMPUTED') AS computed_charges
    FROM atom.charge
    WHERE order_request_id IS NOT NULL
    GROUP BY 1
)
SELECT
    c.lot_closure_id,
    l.trading_account_id,
    l.universe_id,
    l.instrument_id,
    c.sell_order_request_id,
    c.quantity,
    c.closed_on,
    c.funds_credited_on,
    l.acquired_on,
    l.provenance,
    c.unit_proceeds,
    c.quantity * c.unit_proceeds                             AS gross_proceeds,
    -- Actual cost: what was paid, including buy charges (D-076a).
    l.unit_cost,
    c.quantity * l.unit_cost                                 AS actual_cost,
    c.quantity * (c.unit_proceeds - l.unit_cost)             AS gain_on_actual_cost,
    -- Strategy cost: a harvest proxy is measured against the capital it carries (D-188).
    l.synthetic_cost_basis,
    c.quantity * COALESCE(l.synthetic_cost_basis, l.unit_cost) AS strategy_cost,
    c.quantity * (c.unit_proceeds - COALESCE(l.synthetic_cost_basis, l.unit_cost))
                                                             AS gain_on_strategy_cost,
    -- Charges allocated by this closure's share of the sell order's proceeds.
    -- NULL, never zero, when the broker reported nothing (CHARGES-MODEL.md 4.2).
    ROUND(ch.broker_charges
          * (c.quantity * c.unit_proceeds) / op.total_proceeds, 4) AS allocated_broker_charges,
    ROUND(ch.computed_charges
          * (c.quantity * c.unit_proceeds) / op.total_proceeds, 4) AS allocated_computed_charges
FROM atom.lot_closure c
JOIN atom.position_lot l ON l.lot_id = c.lot_id
JOIN order_proceeds op   ON op.sell_order_request_id = c.sell_order_request_id
LEFT JOIN order_charges ch ON ch.order_request_id = c.sell_order_request_id;

COMMENT ON VIEW atom.v_realised_gain IS
    'D-190: two gain figures per closure, each named for the basis it was computed against. '
    'gain_on_strategy_cost is what the strategy earned; gain_on_actual_cost is what the bank '
    'account saw. Taxable gain is a third number and lives in atom.tax_gain, because its FIFO '
    'matching differs (D-167).';
