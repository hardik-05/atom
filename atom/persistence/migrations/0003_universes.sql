-- 0003_universes.sql
-- Trading universes as a first-class entity (D-151, D-156).
--
-- A universe is a named collection with its own config, its own runs, its own
-- lots and its own P&L. Two universes over the same instruments are peers that
-- can be compared, not two views of one thing. Membership is SCD Type 2: every
-- change is a new row, so "what did this universe look like on 12 March" is
-- answerable years later (D-154).

CREATE TABLE atom.universe (
    universe_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        text NOT NULL UNIQUE,
    description text,
    source      text NOT NULL,        -- MANUAL | VOLUME_FILTER | IMPORTED     (D-151)
    country     text NOT NULL DEFAULT 'IN',
    status      text NOT NULL DEFAULT 'ACTIVE',
    created_by  text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT universe_source_ck CHECK (source IN ('MANUAL','VOLUME_FILTER','IMPORTED')),
    CONSTRAINT universe_status_ck CHECK (status IN ('ACTIVE','ARCHIVED'))
);

CREATE TABLE atom.universe_category (
    universe_category_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    universe_id   bigint NOT NULL REFERENCES atom.universe ON DELETE CASCADE,
    category_code text NOT NULL,      -- EQUITY|COMMODITY|GLOBAL for the ETF universe;
                                      -- one row equal to the universe name for a manual one
    display_order integer NOT NULL,   -- the buy priority ordering (D-042)
    CONSTRAINT universe_category_uk UNIQUE (universe_id, category_code)
);

COMMENT ON COLUMN atom.universe_category.display_order IS
    'D-042: the buy priority ordering. Categories are attempted in this order and the reason a '
    'lower-priority category was not reached is recorded per candidate.';

-- ---------------------------------------------------------------------------
-- SCD Type 2 membership: every change is a new row, nothing is updated in place (D-154)
-- ---------------------------------------------------------------------------
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

COMMENT ON COLUMN atom.universe_member.member_status IS
    'FROZEN is universe-level: the instrument stays a member but yields no new buys. Distinct '
    'from a holdings-level freeze in atom.account_exclusion (D-062).';

-- ---------------------------------------------------------------------------
-- Snapshots — reproducibility. A run records which snapshot it decided against
-- so the decision stays explicable after membership moves (D-058e).
-- ---------------------------------------------------------------------------
CREATE TABLE atom.universe_snapshot (
    snapshot_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    universe_id    bigint NOT NULL REFERENCES atom.universe,
    effective_from date NOT NULL,
    effective_to   date,
    generated_by   text NOT NULL,
    generated_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT universe_snapshot_uk UNIQUE (universe_id, effective_from),
    CONSTRAINT universe_snapshot_period_ck
        CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE TABLE atom.universe_snapshot_member (
    snapshot_id   bigint NOT NULL REFERENCES atom.universe_snapshot ON DELETE CASCADE,
    instrument_id bigint NOT NULL REFERENCES atom.instrument,
    avg_volume    numeric(18,4),
    PRIMARY KEY (snapshot_id, instrument_id)
);

COMMENT ON TABLE atom.universe_snapshot_member IS
    'A deliberate denormalisation of universe_member. It stores history that must not move, '
    'which is the legitimate case for duplication (D-058e).';
