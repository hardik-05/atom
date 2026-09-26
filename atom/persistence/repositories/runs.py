"""Runs, the decision record, and run logs."""

from __future__ import annotations

from datetime import date
from typing import Any

from psycopg import Connection
from psycopg.types.json import Jsonb

from atom.persistence.db import execute, execute_expecting, fetch_all, fetch_exactly_one, fetch_one

Conn = Connection[Any]


def create_batch(conn: Conn, *, triggered_by: str, trade_date: date) -> int:
    row = fetch_exactly_one(
        conn,
        "INSERT INTO atom.run_batch (triggered_by, trade_date) VALUES (%s, %s) "
        "RETURNING run_batch_id",
        (triggered_by, trade_date),
    )
    return int(row["run_batch_id"])


def create_run(
    conn: Conn,
    *,
    batch_id: int | None,
    account_id: int,
    universe_id: int,
    snapshot_id: int | None,
    run_type: str,
    execution_mode: str,
    trade_date: date,
    config_snapshot: dict[str, Any],
) -> int:
    """Created EXECUTING. The partial unique index refuses a second non-FAILED
    EXECUTE run for the same account, universe and day (D-057e)."""
    row = fetch_exactly_one(
        conn,
        """
        INSERT INTO atom.run
            (run_batch_id, trading_account_id, universe_id, snapshot_id, run_type,
             execution_mode, trade_date, status, config_snapshot)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'EXECUTING', %s)
        RETURNING run_id
        """,
        (
            batch_id,
            account_id,
            universe_id,
            snapshot_id,
            run_type,
            execution_mode,
            trade_date,
            Jsonb(config_snapshot),
        ),
    )
    return int(row["run_id"])


def set_status(conn: Conn, run_id: int, status: str) -> None:
    execute_expecting(
        conn,
        "UPDATE atom.run SET status = %s, "
        "finished_at = CASE WHEN %s IN ('COMPLETED','FAILED') THEN now() ELSE finished_at END "
        "WHERE run_id = %s",
        (status, status, run_id),
        rows=1,
    )


def add_candidate(conn: Conn, run_id: int, row: dict[str, Any]) -> None:
    execute(
        conn,
        """
        INSERT INTO atom.run_candidate
            (run_id, instrument_id, category, rank, mean_price, median_price, ltp,
             deviation_pct, nav, nav_premium_pct, holdings_status, gate_failed, decision,
             decision_reason)
        VALUES (%(run_id)s, %(instrument_id)s, %(category)s, %(rank)s, %(mean_price)s,
                %(median_price)s, %(ltp)s, %(deviation_pct)s, %(nav)s, %(nav_premium_pct)s,
                %(holdings_status)s, %(gate_failed)s, %(decision)s, %(decision_reason)s)
        """,
        {"run_id": run_id, **row},
    )


def log(
    conn: Conn,
    run_id: int,
    *,
    level: str,
    stage: str,
    message: str,
    context: dict[str, Any] | None = None,
) -> None:
    execute(
        conn,
        "INSERT INTO atom.run_log (run_id, level, stage, message, context) "
        "VALUES (%s, %s, %s, %s, %s)",
        (run_id, level, stage, message, Jsonb(context) if context else None),
    )


_RUN_SELECT = """
    SELECT r.*, u.name AS universe_name, a.broker_client_code, b.broker_code,
           i.display_name AS investor_name
    FROM atom.run r
    JOIN atom.universe u        ON u.universe_id = r.universe_id
    JOIN atom.trading_account a ON a.trading_account_id = r.trading_account_id
    JOIN atom.broker b          ON b.broker_id = a.broker_id
    JOIN atom.investor i        ON i.investor_id = a.investor_id
"""


def get_run(conn: Conn, run_id: int) -> dict[str, Any]:
    return fetch_exactly_one(conn, _RUN_SELECT + " WHERE r.run_id = %s", (run_id,))


def list_runs(conn: Conn, *, limit: int = 50) -> list[dict[str, Any]]:
    return fetch_all(conn, _RUN_SELECT + " ORDER BY r.run_id DESC LIMIT %s", (limit,))


def candidates(conn: Conn, run_id: int) -> list[dict[str, Any]]:
    return fetch_all(
        conn,
        """
        SELECT c.*, i.symbol, i.name
        FROM atom.run_candidate c JOIN atom.instrument i ON i.instrument_id = c.instrument_id
        WHERE c.run_id = %s
        ORDER BY c.category, c.rank
        """,
        (run_id,),
    )


def logs(conn: Conn, run_id: int) -> list[dict[str, Any]]:
    return fetch_all(
        conn, "SELECT * FROM atom.run_log WHERE run_id = %s ORDER BY run_log_id", (run_id,)
    )


def live_execute_run(
    conn: Conn, *, account_id: int, universe_id: int, trade_date: date
) -> dict[str, Any] | None:
    return fetch_one(
        conn,
        "SELECT * FROM atom.run WHERE trading_account_id = %s AND universe_id = %s "
        "AND trade_date = %s AND run_type = 'EXECUTE' AND status <> 'FAILED'",
        (account_id, universe_id, trade_date),
    )
