"""Daily prices and NAV — the data pool the strategy decides from."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
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


def upsert_candles_bulk(
    conn: Conn, *, bars: Sequence[tuple[int, CanonicalCandle]], source: str, chunk: int = 5000
) -> int:
    """Write many instruments' bars in a few statements.

    One ``unnest`` insert per ``chunk`` rows instead of one round trip per bar: the
    database is a continent away from the instance, so the round trips, not the
    inserts, were the cost. Within one statement a (instrument, date) pair must be
    unique, which the caller guarantees by fetching each instrument once.
    """
    written = 0
    for start in range(0, len(bars), chunk):
        part = bars[start : start + chunk]
        written += execute(
            conn,
            """
            INSERT INTO atom.price_daily
                (instrument_id, trade_date, open_px, high_px, low_px, close_px, volume, source)
            SELECT t.iid, t.d, t.o, t.h, t.l, t.c, t.v, %s
            FROM unnest(%s::bigint[], %s::date[], %s::numeric[], %s::numeric[],
                        %s::numeric[], %s::numeric[], %s::bigint[])
                 AS t(iid, d, o, h, l, c, v)
            ON CONFLICT (instrument_id, trade_date) DO UPDATE SET
                open_px = EXCLUDED.open_px, high_px = EXCLUDED.high_px,
                low_px = EXCLUDED.low_px, close_px = EXCLUDED.close_px,
                volume = EXCLUDED.volume, source = EXCLUDED.source, ingested_at = now()
            """,
            (
                source,
                [iid for iid, _ in part],
                [b.trade_date for _, b in part],
                [b.open for _, b in part],
                [b.high for _, b in part],
                [b.low for _, b in part],
                [b.close for _, b in part],
                [b.volume for _, b in part],
            ),
        )
    return written


def _has_sync_state(conn: Conn) -> bool:
    """False until migration 0019 is applied; the sync then runs on coverage alone."""
    row = fetch_all(conn, "SELECT to_regclass('atom.history_sync_state') AS t")
    return row[0]["t"] is not None


def sync_state(conn: Conn, instrument_ids: list[int], *, source: str) -> dict[int, dict[str, Any]]:
    """What the history sync has already asked the broker for (migration 0019)."""
    if not instrument_ids or not _has_sync_state(conn):
        return {}
    rows = fetch_all(
        conn,
        "SELECT instrument_id, requested_from, synced_through FROM atom.history_sync_state "
        "WHERE instrument_id = ANY(%s) AND source = %s",
        (instrument_ids, source),
    )
    return {int(r["instrument_id"]): r for r in rows}


def record_sync_state(conn: Conn, rows: Sequence[tuple[int, date, date]], *, source: str) -> None:
    """Widen each instrument's covered span to include (requested_from, synced_through)."""
    if not rows or not _has_sync_state(conn):
        return
    execute(
        conn,
        """
        INSERT INTO atom.history_sync_state AS h
            (instrument_id, source, requested_from, synced_through)
        SELECT t.iid, %s, t.f, t.th FROM unnest(%s::bigint[], %s::date[], %s::date[])
               AS t(iid, f, th)
        ON CONFLICT (instrument_id, source) DO UPDATE SET
            requested_from = LEAST(h.requested_from, EXCLUDED.requested_from),
            synced_through = GREATEST(h.synced_through, EXCLUDED.synced_through),
            updated_at = now()
        """,
        (source, [r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows]),
    )


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


def average_volumes(
    conn: Conn, instrument_ids: list[int], *, window: int, before: date
) -> dict[int, tuple[Decimal, int]]:
    """``{instrument_id: (average volume, days counted)}`` over the last ``window`` bars
    strictly before ``before`` that carry a volume."""
    if not instrument_ids:
        return {}
    rows = fetch_all(
        conn,
        """
        SELECT instrument_id, avg(volume)::numeric AS avg_volume, count(*) AS days FROM (
            SELECT p.instrument_id, p.volume, row_number() OVER (
                PARTITION BY p.instrument_id ORDER BY p.trade_date DESC) AS rn
            FROM atom.price_daily p
            WHERE p.instrument_id = ANY(%s) AND p.trade_date < %s AND p.volume IS NOT NULL
        ) ranked
        WHERE rn <= %s
        GROUP BY instrument_id
        """,
        (instrument_ids, before, window),
    )
    return {int(r["instrument_id"]): (Decimal(r["avg_volume"]), int(r["days"])) for r in rows}
