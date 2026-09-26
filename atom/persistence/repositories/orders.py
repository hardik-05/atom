"""Order intents, fills, lots, closures and exclusions."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from psycopg import Connection

from atom.domain.enums import Provenance
from atom.domain.models import OpenLot
from atom.persistence.db import (
    execute,
    execute_expecting,
    fetch_all,
    fetch_exactly_one,
    fetch_one,
)

Conn = Connection[Any]

UNSETTLED = ("INTENT", "PLACED", "PARTIAL", "IN_FLIGHT")


def insert_intent(
    conn: Conn,
    *,
    run_id: int | None,
    account_id: int,
    universe_id: int,
    instrument_id: int,
    side: str,
    order_kind: str,
    quantity: int,
    limit_price: Decimal,
    trigger_price: Decimal | None,
    idempotency_key: str,
) -> int:
    """Written BEFORE the send (D-094). A crash between here and the broker leaves
    an INTENT row — evidence to resolve by looking — never a silent gap."""
    row = fetch_exactly_one(
        conn,
        """
        INSERT INTO atom.order_request
            (run_id, trading_account_id, universe_id, instrument_id, side, order_kind,
             quantity, limit_price, trigger_price, idempotency_key, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'INTENT')
        RETURNING order_request_id
        """,
        (
            run_id,
            account_id,
            universe_id,
            instrument_id,
            side,
            order_kind,
            quantity,
            limit_price,
            trigger_price,
            idempotency_key,
        ),
    )
    return int(row["order_request_id"])


def mark_sent(
    conn: Conn, order_id: int, *, broker_order_id: str, status: str, placed_at: datetime
) -> None:
    execute_expecting(
        conn,
        "UPDATE atom.order_request SET broker_order_id = %s, status = %s, placed_at = %s "
        "WHERE order_request_id = %s",
        (broker_order_id, status, placed_at, order_id),
        rows=1,
    )


def mark_status(
    conn: Conn, order_id: int, *, status: str, reject_reason: str | None = None
) -> None:
    execute_expecting(
        conn,
        "UPDATE atom.order_request SET status = %s, "
        "reject_reason = COALESCE(%s, reject_reason) WHERE order_request_id = %s",
        (status, reject_reason, order_id),
        rows=1,
    )


_ORDER_SELECT = """
    SELECT o.*, i.symbol, i.isin, r.trade_date
    FROM atom.order_request o
    JOIN atom.instrument i ON i.instrument_id = o.instrument_id
    LEFT JOIN atom.run r   ON r.run_id = o.run_id
"""


def orders_for_run(conn: Conn, run_id: int) -> list[dict[str, Any]]:
    return fetch_all(
        conn, _ORDER_SELECT + " WHERE o.run_id = %s ORDER BY o.order_request_id", (run_id,)
    )


def get_order(conn: Conn, order_id: int) -> dict[str, Any]:
    return fetch_exactly_one(conn, _ORDER_SELECT + " WHERE o.order_request_id = %s", (order_id,))


def unsettled_orders(conn: Conn, account_id: int) -> list[dict[str, Any]]:
    return fetch_all(
        conn,
        _ORDER_SELECT + " WHERE o.trading_account_id = %s AND o.status = ANY(%s) "
        "AND o.order_kind = 'LIMIT' ORDER BY o.order_request_id",
        (account_id, list(UNSETTLED)),
    )


def live_gtts(conn: Conn, *, account_id: int, universe_id: int) -> list[dict[str, Any]]:
    """ATOM's own resting GTT sells. The ONLY link to them on Upstox and Zerodha,
    whose GTTs carry no ATOM identifier (D-176) — lose these rows and ATOM can no
    longer tell its sells from the operator's."""
    return fetch_all(
        conn,
        _ORDER_SELECT + " WHERE o.trading_account_id = %s AND o.universe_id = %s "
        "AND o.order_kind = 'GTT' AND o.status IN ('PLACED','IN_FLIGHT') "
        "AND o.broker_order_id IS NOT NULL ORDER BY o.order_request_id",
        (account_id, universe_id),
    )


def bought_today(conn: Conn, *, account_id: int, universe_id: int, trade_date: date) -> set[int]:
    """Instruments with a live BUY from a run on ``trade_date`` — the one-lot-per-day
    gate. A rejected or cancelled buy does not count: nothing was bought."""
    rows = fetch_all(
        conn,
        """
        SELECT DISTINCT o.instrument_id FROM atom.order_request o
        JOIN atom.run r ON r.run_id = o.run_id
        WHERE o.trading_account_id = %s AND o.universe_id = %s AND r.trade_date = %s
          AND o.side = 'BUY' AND o.status NOT IN ('REJECTED','CANCELLED')
        """,
        (account_id, universe_id, trade_date),
    )
    return {int(r["instrument_id"]) for r in rows}


# -------------------------------------------------------------------- fills


def insert_fill(
    conn: Conn,
    *,
    order_id: int,
    quantity: int,
    fill_price: Decimal,
    filled_at: datetime,
    broker_trade_id: str | None,
) -> int | None:
    """Idempotent on (order, broker_trade_id). ``None`` means already recorded —
    which is what makes a settle re-run safe (RUN-LIFECYCLE.md 9.2)."""
    row = fetch_one(
        conn,
        """
        INSERT INTO atom.order_fill
            (order_request_id, quantity, fill_price, filled_at, broker_trade_id)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (order_request_id, broker_trade_id) WHERE broker_trade_id IS NOT NULL
        DO NOTHING
        RETURNING order_fill_id
        """,
        (order_id, quantity, fill_price, filled_at, broker_trade_id),
    )
    return None if row is None else int(row["order_fill_id"])


def filled_quantity(conn: Conn, order_id: int) -> int:
    row = fetch_exactly_one(
        conn,
        "SELECT COALESCE(sum(quantity), 0) AS q FROM atom.order_fill WHERE order_request_id = %s",
        (order_id,),
    )
    return int(row["q"])


# --------------------------------------------------------------------- lots


def insert_lot(
    conn: Conn,
    *,
    account_id: int,
    universe_id: int,
    instrument_id: int,
    buy_order_id: int | None,
    fill_id: int | None,
    quantity: int,
    unit_cost: Decimal,
    acquired_on: date,
    provenance: str = "ATOM",
) -> int:
    row = fetch_exactly_one(
        conn,
        """
        INSERT INTO atom.position_lot
            (trading_account_id, universe_id, instrument_id, buy_order_request_id, order_fill_id,
             quantity, quantity_open, unit_cost, acquired_on, provenance)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING lot_id
        """,
        (
            account_id,
            universe_id,
            instrument_id,
            buy_order_id,
            fill_id,
            quantity,
            quantity,
            unit_cost,
            acquired_on,
            provenance,
        ),
    )
    return int(row["lot_id"])


def open_lots(conn: Conn, *, account_id: int, universe_id: int | None = None) -> list[OpenLot]:
    rows = fetch_all(
        conn,
        """
        SELECT lot_id, instrument_id, universe_id, quantity_open, unit_cost, acquired_on,
               synthetic_cost_basis, provenance
        FROM atom.position_lot
        WHERE trading_account_id = %s AND quantity_open > 0
          AND (%s::bigint IS NULL OR universe_id = %s)
        ORDER BY instrument_id, acquired_on, lot_id
        """,
        (account_id, universe_id, universe_id),
    )
    return [
        OpenLot(
            lot_id=int(r["lot_id"]),
            instrument_id=int(r["instrument_id"]),
            universe_id=int(r["universe_id"]),
            quantity_open=int(r["quantity_open"]),
            unit_cost=r["unit_cost"],
            acquired_on=r["acquired_on"],
            synthetic_cost_basis=r["synthetic_cost_basis"],
            provenance=Provenance(r["provenance"]),
        )
        for r in rows
    ]


def positions(conn: Conn, account_id: int) -> list[dict[str, Any]]:
    return fetch_all(
        conn,
        """
        SELECT p.*, i.symbol, i.name, u.name AS universe_name
        FROM atom.v_position p
        JOIN atom.instrument i ON i.instrument_id = p.instrument_id
        JOIN atom.universe u   ON u.universe_id = p.universe_id
        WHERE p.trading_account_id = %s
        ORDER BY u.name, i.symbol
        """,
        (account_id,),
    )


def close_lots_fifo(
    conn: Conn,
    *,
    account_id: int,
    universe_id: int,
    instrument_id: int,
    sell_order_id: int,
    quantity: int,
    unit_proceeds: Decimal,
    closed_on: date,
) -> int:
    """Close ``quantity`` units under UNIVERSE FIFO (D-167). Returns the quantity
    closed, which is less than asked only if ATOM's books hold less — the caller
    treats any shortfall as a reconciliation fault, never as a rounding matter."""
    remaining = quantity
    lots = fetch_all(
        conn,
        "SELECT lot_id, quantity_open FROM atom.position_lot "
        "WHERE trading_account_id = %s AND universe_id = %s AND instrument_id = %s "
        "AND quantity_open > 0 ORDER BY acquired_on, lot_id FOR UPDATE",
        (account_id, universe_id, instrument_id),
    )
    for lot in lots:
        if remaining == 0:
            break
        take = min(remaining, int(lot["quantity_open"]))
        execute(
            conn,
            "INSERT INTO atom.lot_closure (lot_id, sell_order_request_id, quantity, unit_proceeds, "
            "closed_on) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (lot_id, sell_order_request_id) "
            "DO NOTHING",
            (lot["lot_id"], sell_order_id, take, unit_proceeds, closed_on),
        )
        left = int(lot["quantity_open"]) - take
        execute(
            conn,
            "UPDATE atom.position_lot SET quantity_open = %s, status = %s WHERE lot_id = %s",
            (left, "CLOSED" if left == 0 else "OPEN", lot["lot_id"]),
        )
        remaining -= take
    return quantity - remaining


# --------------------------------------------------------------- exclusions


def add_exclusion(
    conn: Conn,
    *,
    account_id: int,
    instrument_id: int,
    exclusion_type: str,
    quantity: int,
    created_by: str,
) -> int:
    row = fetch_exactly_one(
        conn,
        "INSERT INTO atom.account_exclusion "
        "(trading_account_id, instrument_id, exclusion_type, quantity, created_by) "
        "VALUES (%s, %s, %s, %s, %s) RETURNING account_exclusion_id",
        (account_id, instrument_id, exclusion_type, quantity, created_by),
    )
    return int(row["account_exclusion_id"])


def active_exclusions(conn: Conn, account_id: int) -> list[dict[str, Any]]:
    return fetch_all(
        conn,
        """
        SELECT e.*, i.symbol, i.name FROM atom.account_exclusion e
        JOIN atom.instrument i ON i.instrument_id = e.instrument_id
        WHERE e.trading_account_id = %s AND e.released_at IS NULL
        ORDER BY i.symbol
        """,
        (account_id,),
    )


def withheld_by_instrument(conn: Conn, account_id: int) -> dict[int, int]:
    rows = fetch_all(
        conn,
        "SELECT instrument_id, sum(quantity) AS q FROM atom.account_exclusion "
        "WHERE trading_account_id = %s AND released_at IS NULL GROUP BY instrument_id",
        (account_id,),
    )
    return {int(r["instrument_id"]): int(r["q"]) for r in rows}


def release_exclusion(conn: Conn, exclusion_id: int) -> None:
    execute_expecting(
        conn,
        "UPDATE atom.account_exclusion SET released_at = now() "
        "WHERE account_exclusion_id = %s AND released_at IS NULL",
        (exclusion_id,),
        rows=1,
    )
