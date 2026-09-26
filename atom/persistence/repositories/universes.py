"""Universes, their categories, SCD-2 membership and snapshots (D-151, D-154)."""

from __future__ import annotations

from datetime import date
from typing import Any

from psycopg import Connection

from atom.persistence.db import execute, fetch_all, fetch_exactly_one, fetch_one

Conn = Connection[Any]

OPEN_END = "9999-12-31 00:00:00+00"


def list_universes(conn: Conn) -> list[dict[str, Any]]:
    return fetch_all(
        conn,
        f"""
        SELECT u.*,
               (SELECT count(*) FROM atom.universe_member m
                WHERE m.universe_id = u.universe_id AND m.valid_to = '{OPEN_END}') AS member_count,
               (SELECT array_agg(category_code ORDER BY display_order)
                FROM atom.universe_category c WHERE c.universe_id = u.universe_id) AS categories
        FROM atom.universe u
        ORDER BY u.name
        """,
    )


def get_universe(conn: Conn, universe_id: int) -> dict[str, Any]:
    return fetch_exactly_one(
        conn, "SELECT * FROM atom.universe WHERE universe_id = %s", (universe_id,)
    )


def find_universe(conn: Conn, name: str) -> dict[str, Any] | None:
    return fetch_one(conn, "SELECT * FROM atom.universe WHERE name = %s", (name,))


def create_universe(
    conn: Conn,
    *,
    name: str,
    source: str,
    created_by: str,
    categories: list[str],
    description: str | None = None,
) -> int:
    """``categories`` in buy-priority order (D-042); at least one."""
    if not categories:
        raise ValueError("a universe needs at least one category")
    row = fetch_exactly_one(
        conn,
        "INSERT INTO atom.universe (name, description, source, created_by) "
        "VALUES (%s, %s, %s, %s) RETURNING universe_id",
        (name, description, source, created_by),
    )
    universe_id = int(row["universe_id"])
    for order, code in enumerate(categories, start=1):
        execute(
            conn,
            "INSERT INTO atom.universe_category (universe_id, category_code, display_order) "
            "VALUES (%s, %s, %s)",
            (universe_id, code, order),
        )
    return universe_id


def categories(conn: Conn, universe_id: int) -> list[str]:
    rows = fetch_all(
        conn,
        "SELECT category_code FROM atom.universe_category WHERE universe_id = %s "
        "ORDER BY display_order",
        (universe_id,),
    )
    return [str(r["category_code"]) for r in rows]


def set_member(
    conn: Conn,
    *,
    universe_id: int,
    instrument_id: int,
    member_status: str,
    changed_by: str,
    reason: str | None = None,
) -> bool:
    """Make ``member_status`` the instrument's current state. SCD Type 2: the open
    row is closed and a new one opened; nothing is updated in place (D-154).

    Returns False when the instrument is already a member in that state, so a
    re-import does not churn history with no-op rows.
    """
    current = fetch_one(
        conn,
        f"SELECT universe_member_id, member_status FROM atom.universe_member "
        f"WHERE universe_id = %s AND instrument_id = %s AND valid_to = '{OPEN_END}'",
        (universe_id, instrument_id),
    )
    if current and current["member_status"] == member_status:
        return False
    if current:
        execute(
            conn,
            "UPDATE atom.universe_member SET valid_to = now() WHERE universe_member_id = %s",
            (current["universe_member_id"],),
        )
    execute(
        conn,
        "INSERT INTO atom.universe_member "
        "(universe_id, instrument_id, member_status, change_reason, changed_by) "
        "VALUES (%s, %s, %s, %s, %s)",
        (universe_id, instrument_id, member_status, reason, changed_by),
    )
    return True


def remove_member(conn: Conn, *, universe_id: int, instrument_id: int) -> bool:
    touched = execute(
        conn,
        f"UPDATE atom.universe_member SET valid_to = now() "
        f"WHERE universe_id = %s AND instrument_id = %s AND valid_to = '{OPEN_END}'",
        (universe_id, instrument_id),
    )
    return touched > 0


def current_members(
    conn: Conn, universe_id: int, *, broker_id: int | None = None
) -> list[dict[str, Any]]:
    """Every current member with what the strategy needs to place it.

    ``category`` is the instrument's asset class when the universe has a
    category of that name (the ETF universe: EQUITY, COMMODITY, GLOBAL), and the
    universe's single category otherwise (a manual universe). An instrument that
    fits neither has category NULL and is reported as not considered.
    """
    return fetch_all(
        conn,
        f"""
        WITH cats AS (
            SELECT array_agg(category_code) AS codes, count(*) AS n
            FROM atom.universe_category WHERE universe_id = %(u)s
        )
        SELECT m.instrument_id, m.member_status, m.valid_from,
               i.isin, i.symbol, i.name, i.asset_class, i.status AS instrument_status,
               i.tick_size, c.bucket, c.tier1_index, c.assignment_status,
               bi.broker_token, bi.tradable,
               CASE WHEN i.asset_class = ANY(cats.codes) THEN i.asset_class
                    WHEN cats.n = 1 THEN cats.codes[1]
               END AS category
        FROM atom.universe_member m
        JOIN atom.instrument i ON i.instrument_id = m.instrument_id
        LEFT JOIN atom.instrument_classification c ON c.instrument_id = i.instrument_id
        LEFT JOIN atom.broker_instrument bi
               ON bi.instrument_id = i.instrument_id AND bi.broker_id = %(b)s
        CROSS JOIN cats
        WHERE m.universe_id = %(u)s AND m.valid_to = '{OPEN_END}'
        ORDER BY i.symbol
        """,
        {"u": universe_id, "b": broker_id},
    )


def snapshot(conn: Conn, *, universe_id: int, effective_from: date, generated_by: str) -> int:
    """Freeze today's membership for a run (D-058e). One snapshot per universe per
    day: a second run the same day decides against the same list as the first."""
    existing = fetch_one(
        conn,
        "SELECT snapshot_id FROM atom.universe_snapshot "
        "WHERE universe_id = %s AND effective_from = %s",
        (universe_id, effective_from),
    )
    if existing:
        return int(existing["snapshot_id"])
    row = fetch_exactly_one(
        conn,
        "INSERT INTO atom.universe_snapshot (universe_id, effective_from, generated_by) "
        "VALUES (%s, %s, %s) RETURNING snapshot_id",
        (universe_id, effective_from, generated_by),
    )
    snapshot_id = int(row["snapshot_id"])
    execute(
        conn,
        f"INSERT INTO atom.universe_snapshot_member (snapshot_id, instrument_id) "
        f"SELECT %s, instrument_id FROM atom.universe_member "
        f"WHERE universe_id = %s AND valid_to = '{OPEN_END}'",
        (snapshot_id, universe_id),
    )
    return snapshot_id
