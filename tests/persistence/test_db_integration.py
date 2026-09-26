"""The query helpers, against a real database.

Skipped unless ATOM_TEST_DATABASE_URL is set. What is checked here is the
behaviour that cannot be checked without a server: that a pool configures every
connection identically, that the helpers' row-count assertions fire, and that a
constraint violation is recognisable by name.
"""

from __future__ import annotations

import pytest

from atom.persistence.db import (
    QueryShapeError,
    constraint_name,
    execute,
    execute_expecting,
    fetch_all,
    fetch_exactly_one,
    fetch_one,
    is_check_violation,
    is_unique_violation,
    make_pool,
)

psycopg = pytest.importorskip("psycopg")


def test_seed_data_is_present(conn) -> None:  # type: ignore[no-untyped-def]
    brokers = fetch_all(conn, "SELECT broker_code FROM atom.broker ORDER BY broker_code")
    assert [r["broker_code"] for r in brokers] == [
        "DHAN",
        "GROWW",
        "SHOONYA",
        "UPSTOX",
        "ZERODHA",
    ]
    keys = fetch_exactly_one(conn, "SELECT count(*) AS n FROM atom.config_key")
    assert keys["n"] == 26  # 24 from 0016, plus the two 0017 adds


def test_fetch_exactly_one_rejects_no_rows(conn) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(QueryShapeError, match="got 0"):
        fetch_exactly_one(conn, "SELECT 1 WHERE false")


def test_fetch_exactly_one_rejects_several_rows(conn) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(QueryShapeError, match="got 5"):
        fetch_exactly_one(conn, "SELECT broker_code FROM atom.broker")


def test_fetch_one_returns_none_rather_than_raising(conn) -> None:  # type: ignore[no-untyped-def]
    assert fetch_one(conn, "SELECT 1 AS x WHERE false") is None


def test_execute_expecting_catches_an_update_that_matched_nothing(conn) -> None:  # type: ignore[no-untyped-def]
    """The quietest bug in the system: a successful UPDATE that changed nothing."""
    with pytest.raises(QueryShapeError, match="affected 0 rows, expected 1"):
        execute_expecting(
            conn,
            "UPDATE atom.broker SET display_name = %s WHERE broker_code = %s",
            ("Nobody", "NOSUCHBROKER"),
            rows=1,
        )


def test_execute_expecting_passes_when_the_count_matches(conn) -> None:  # type: ignore[no-untyped-def]
    execute_expecting(
        conn,
        "UPDATE atom.broker SET display_name = %s WHERE broker_code = %s",
        ("Dhan Securities", "DHAN"),
        rows=1,
    )


def test_a_duplicate_idempotency_key_is_recognisable(conn) -> None:  # type: ignore[no-untyped-def]
    """D-094: the second write of the same key is the signal, not a crash to swallow."""
    _seed_account_and_instrument(conn)
    sql = """
        INSERT INTO atom.order_request
            (trading_account_id, universe_id, instrument_id, side, order_kind,
             quantity, limit_price, idempotency_key, status)
        SELECT a.trading_account_id, u.universe_id, i.instrument_id, 'BUY', 'LIMIT',
               1, 100, 'atm2609260101', 'INTENT'
        FROM atom.trading_account a, atom.universe u, atom.instrument i LIMIT 1
    """
    execute(conn, sql)
    with pytest.raises(psycopg.errors.UniqueViolation) as caught:
        execute(conn, sql)
    assert is_unique_violation(caught.value)
    assert constraint_name(caught.value) == "order_request_idempotency_key_key"


def test_a_market_order_is_refused_by_name(conn) -> None:  # type: ignore[no-untyped-def]
    """D-174, from the application's side of the wire.

    The constraint is proven in verify_constraints.sql; what matters here is that
    the failure arrives as something the code above can identify, rather than as
    an opaque database error.
    """
    _seed_account_and_instrument(conn)
    with pytest.raises(psycopg.errors.CheckViolation) as caught:
        execute(
            conn,
            """
            INSERT INTO atom.order_request
                (trading_account_id, universe_id, instrument_id, side, order_kind,
                 quantity, limit_price, idempotency_key, status)
            SELECT a.trading_account_id, u.universe_id, i.instrument_id, 'BUY', 'MARKET',
                   1, 100, 'atm2609260202', 'INTENT'
            FROM atom.trading_account a, atom.universe u, atom.instrument i LIMIT 1
            """,
        )
    assert is_check_violation(caught.value)
    assert constraint_name(caught.value) == "order_kind_ck"


def test_pool_configures_every_connection(migrated_dsn: str) -> None:
    """Timezone, statement timeout and search path must not depend on luck."""
    from atom.persistence.db import DbSettings

    pool = make_pool(
        DbSettings(
            dsn=migrated_dsn,
            min_size=1,
            max_size=2,
            connect_timeout_sec=10,
            statement_timeout_ms=7000,
        )
    )
    pool.open()
    try:
        for _ in range(3):
            with pool.connection() as conn:
                row = conn.execute(
                    "SELECT current_setting('TimeZone') AS tz, "
                    "current_setting('statement_timeout') AS timeout, "
                    "current_setting('search_path') AS path"
                ).fetchone()
                assert row is not None
                assert row["tz"] == "UTC"
                assert row["timeout"] == "7s"
                assert row["path"] == "atom"
                conn.rollback()
    finally:
        pool.close()


def _seed_account_and_instrument(conn) -> None:  # type: ignore[no-untyped-def]
    execute(
        conn,
        """
        INSERT INTO atom.investor (external_key, display_name, relationship, onboarded_on)
        VALUES ('INV-IT', 'Integration', 'SELF', DATE '2026-04-01')
        """,
    )
    execute(
        conn,
        """
        INSERT INTO atom.trading_account
            (investor_id, broker_id, broker_client_code, execution_mode, status)
        SELECT i.investor_id, b.broker_id, 'IT-CLIENT', 'DRY', 'ACTIVE'
        FROM atom.investor i, atom.broker b
        WHERE i.external_key = 'INV-IT' AND b.broker_code = 'DHAN'
        """,
    )
    execute(
        conn,
        """
        INSERT INTO atom.instrument (isin, symbol, name, instrument_type, asset_class)
        VALUES ('INE000IT0001', 'ITBEES', 'Integration ETF', 'ETF', 'EQUITY')
        """,
    )
    execute(
        conn,
        """INSERT INTO atom.universe (name, source, created_by)
           VALUES ('IT Universe', 'MANUAL', 'test')""",
    )
