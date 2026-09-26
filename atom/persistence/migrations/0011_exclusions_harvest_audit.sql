-- 0011_exclusions_harvest_audit.sql
-- Exclusions and freezes, the harvest chain, the action audit, and run logs.

-- ---------------------------------------------------------------------------
-- account_exclusion — sellable = holding - excluded - frozen (D-062)
-- ---------------------------------------------------------------------------
CREATE TABLE atom.account_exclusion (
    account_exclusion_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trading_account_id   bigint NOT NULL REFERENCES atom.trading_account,
    instrument_id        bigint NOT NULL REFERENCES atom.instrument,
    exclusion_type text NOT NULL,        -- EXCLUSION (not ours) | FREEZE (ours, held)  (D-062)
    quantity integer NOT NULL CHECK (quantity > 0),
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    released_at timestamptz,             -- never auto-set (D-084)
    CONSTRAINT exclusion_type_ck CHECK (exclusion_type IN ('EXCLUSION','FREEZE')),
    CONSTRAINT exclusion_released_after_created_ck
        CHECK (released_at IS NULL OR released_at >= created_at)
);

COMMENT ON TABLE atom.account_exclusion IS
    'D-062: the default is to SELL. A holding with no row here is sold at the configured target. '
    'EXCLUSION means quantity ATOM never bought; FREEZE means quantity ATOM bought and the '
    'operator wants held. They differ in one consequence: a freeze accrues cost of capital and an '
    'exclusion does not (D-065).';
COMMENT ON COLUMN atom.account_exclusion.released_at IS
    'D-084: never set automatically. A freeze the operator forgot about is visible; a freeze the '
    'system silently released is a position sold without anyone deciding to sell it.';

-- ---------------------------------------------------------------------------
-- harvest_chain — one hop, never two (D-193)
-- ---------------------------------------------------------------------------
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
    CONSTRAINT harvest_status_ck CHECK (status IN ('PROPOSED','EXECUTED','INCOMPLETE')),
    CONSTRAINT harvest_proxy_tier_ck
        CHECK (proxy_tier IS NULL OR proxy_tier IN ('TIER1','TIER2')),
    CONSTRAINT harvest_booked_loss_ck CHECK (booked_loss > 0),
    CONSTRAINT harvest_carried_amount_ck
        CHECK (carried_basis_amount IS NULL OR carried_basis_amount > 0),
    CONSTRAINT harvest_not_self_ck CHECK (proxy_lot_id IS DISTINCT FROM sold_lot_id),
    -- D-193: the no-chaining rule, enforced by the database rather than remembered by code.
    CONSTRAINT harvest_no_chaining_ck CHECK (chain_depth = 1),
    -- D-070b: an EXECUTED harvest has both legs and the amount it carried forward.
    CONSTRAINT harvest_executed_complete_ck
        CHECK (status <> 'EXECUTED'
               OR (proxy_lot_id IS NOT NULL AND carried_basis_amount IS NOT NULL))
);

COMMENT ON CONSTRAINT harvest_no_chaining_ck ON atom.harvest_chain IS
    'D-193: a lot carrying a synthetic basis can never itself be harvested. Each hop lifts the '
    'basis further above cash until the position is effectively unsellable, so the database '
    'refuses the second hop rather than trusting application code to remember.';
COMMENT ON COLUMN atom.harvest_chain.carried_basis_amount IS
    'D-188/D-206: an AMOUNT, not a price. The capital committed to the harvested security is '
    'carried to the proxy and divided by the PROXY quantity - the per-unit figures coincide only '
    'when the two securities happen to trade at the same price. Stored rather than recomputed, '
    'because re-deriving it years later would depend on data since corrected.';
COMMENT ON COLUMN atom.harvest_chain.correlation IS
    'NULL in v1. D-163 made proxy selection manual - no predefined buckets, no correlation floor, '
    'no automatic matching. The column stays for V2-14, which restores correlation matching.';
COMMENT ON COLUMN atom.harvest_chain.status IS
    'D-070b: INCOMPLETE is a real outcome. The sell filled and the proxy buy did not, which '
    'leaves booked capital with nowhere to go and needs an operator, not a retry.';

-- ---------------------------------------------------------------------------
-- action_audit — who did what, from the console
-- ---------------------------------------------------------------------------
CREATE TABLE atom.action_audit (
    action_audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor      text NOT NULL,
    action     text NOT NULL,
    entity     text NOT NULL,
    entity_id  bigint,
    payload    jsonb,
    occurred_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE atom.action_audit IS
    'Every operator action: an override, a freeze, a config change, a manual harvest pairing. '
    'The console role cannot delete from here (docs/09-security/THREAT-MODEL.md).';

-- ---------------------------------------------------------------------------
-- run_log — diagnostics, purgeable. NOT the decision record.
-- ---------------------------------------------------------------------------
CREATE TABLE atom.run_log (
    run_log_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id     bigint NOT NULL REFERENCES atom.run ON DELETE CASCADE,
    level      text NOT NULL,
    stage      text NOT NULL,
    message    text NOT NULL,
    context    jsonb,
    logged_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT run_log_level_ck CHECK (level IN ('DEBUG','INFO','WARNING','ERROR','CRITICAL'))
);

CREATE INDEX run_log_purge_idx ON atom.run_log (logged_at);

COMMENT ON TABLE atom.run_log IS
    'Diagnostics only, and purgeable on the archival schedule. The DECISION record lives in '
    'atom.run_candidate, never here - which is what makes this table safe to delete from.';
