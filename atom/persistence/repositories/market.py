"""Daily prices and NAV — the data pool the strategy decides from."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from typing import Any

from psycopg import Connection

from atom.domain.models import CanonicalCandle
from atom.persistence.db import execute, fetch_all

Conn = Connection[Any]


def upsert_candles(
    conn: Conn, *, instrument_id: int, candles: Iterable[CanonicalCandle], source: str
) -> int:
    """Write bars; a re-fetch overwrites the same day rather than duplicating it."""
    count = 0
    for bar in candles:
        execute(
            conn,
            """
            INSERT INTO atom.price_daily
                (instrument_id, trade_date, open_px, high_px, low_px, close_px, volume, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (instrument_id, trade_date) DO UPDATE SET
                open_px = EXCLUDED.open_px, high_px = EXCLUDED.high_px,
                low_px = EXCLUDED.low_px, close_px = EXCLUDED.close_px,
                volume = EXCLUDED.volume, source = EXCLUDED.source, ingested_at = now()
            """,
            (
                instrument_id,
                bar.trade_date,
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.volume,
                source,
            ),
        )
        count += 1
    return count


def recent_bars(
    conn: Conn, instrument_ids: list[int], *, before: date, limit: int
) -> dict[int, list[dict[str, Any]]]:
    """The last ``limit`` bars strictly BEFORE ``before``, newest first.

    Strictly before: the decision on a day is taken against history, and today's
    own bar — incomplete until the close — must not leak into its own mean.
    """
    if not instrument_ids:
        return {}
    rows = fetch_all(
        conn,
        """
        SELECT instrument_id, trade_date, close_px, volume FROM (
            SELECT p.*, row_number() OVER (
                PARTITION BY instrument_id ORDER BY trade_date DESC) AS rn
            FROM atom.price_daily p
            WHERE instrument_id = ANY(%s) AND trade_date < %s
        ) ranked
        WHERE rn <= %s
        ORDER BY instrument_id, trade_date DESC
        """,
        (instrument_ids, before, limit),
    )
    out: dict[int, list[dict[str, Any]]] = {iid: [] for iid in instrument_ids}
    for row in rows:
        out[int(row["instrument_id"])].append(row)
    return out


def bars_between(
    conn: Conn, instrument_id: int, from_date: date, to_date: date
) -> list[dict[str, Any]]:
    return fetch_all(
        conn,
        "SELECT trade_date, open_px, high_px, low_px, close_px, volume, source "
        "FROM atom.price_daily WHERE instrument_id = %s AND trade_date BETWEEN %s AND %s "
        "ORDER BY trade_date",
        (instrument_id, from_date, to_date),
    )


def coverage(conn: Conn, instrument_ids: list[int]) -> dict[int, dict[str, Any]]:
    if not instrument_ids:
        return {}
    rows = fetch_all(
        conn,
        "SELECT instrument_id, count(*) AS bars, min(trade_date) AS first_date, "
        "max(trade_date) AS last_date FROM atom.price_daily "
        "WHERE instrument_id = ANY(%s) GROUP BY instrument_id",
        (instrument_ids,),
    )
    return {int(r["instrument_id"]): r for r in rows}


def upsert_nav(conn: Conn, *, instrument_id: int, trade_date: date, nav: Decimal) -> None:
    execute(
        conn,
        """
        INSERT INTO atom.nav_daily (instrument_id, trade_date, nav)
        VALUES (%s, %s, %s)
        ON CONFLICT (instrument_id, trade_date) DO UPDATE SET nav = EXCLUDED.nav,
            is_interpolated = false
        """,
        (instrument_id, trade_date, nav),
    )


def latest_navs(
    conn: Conn, instrument_ids: list[int], *, on_or_before: date
) -> dict[int, dict[str, Any]]:
    if not instrument_ids:
        return {}
    rows = fetch_all(
        conn,
        """
        SELECT DISTINCT ON (instrument_id) instrument_id, trade_date, nav, is_interpolated
        FROM atom.nav_daily
        WHERE instrument_id = ANY(%s) AND trade_date <= %s AND nav IS NOT NULL
        ORDER BY instrument_id, trade_date DESC
        """,
        (instrument_ids, on_or_before),
    )
    return {int(r["instrument_id"]): r for r in rows}
