"""Investors, brokers, trading accounts and their daily broker sessions."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from psycopg import Connection

from atom.domain.models import AccountRef
from atom.persistence.db import execute, execute_expecting, fetch_all, fetch_exactly_one, fetch_one

Conn = Connection[Any]

_ACCOUNT_SELECT = """
    SELECT a.trading_account_id, a.investor_id, a.broker_client_code, a.execution_mode,
           host(a.egress_ip) AS egress_ip, a.proxy_url, a.status, a.onboarded_at, a.created_at,
           i.display_name AS investor_name, i.external_key AS investor_key,
           b.broker_id, b.broker_code, b.display_name AS broker_name, b.auth_flow,
           b.supports_gtt
    FROM atom.trading_account a
    JOIN atom.investor i ON i.investor_id = a.investor_id
    JOIN atom.broker   b ON b.broker_id   = a.broker_id
"""


def list_brokers(conn: Conn) -> list[dict[str, Any]]:
    return fetch_all(conn, "SELECT * FROM atom.broker ORDER BY broker_code")


def list_investors(conn: Conn) -> list[dict[str, Any]]:
    return fetch_all(conn, "SELECT * FROM atom.investor ORDER BY display_name")


def create_investor(
    conn: Conn,
    *,
    external_key: str,
    display_name: str,
    relationship: str,
    onboarded_on: date,
    pan_masked: str | None = None,
) -> int:
    row = fetch_exactly_one(
        conn,
        """
        INSERT INTO atom.investor
            (external_key, display_name, relationship, onboarded_on, pan_masked)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING investor_id
        """,
        (external_key, display_name, relationship, onboarded_on, pan_masked),
    )
    return int(row["investor_id"])


def create_account(
    conn: Conn,
    *,
    investor_id: int,
    broker_code: str,
    broker_client_code: str,
    execution_mode: str,
    egress_ip: str | None,
    proxy_url: str | None,
) -> int:
    row = fetch_exactly_one(
        conn,
        """
        INSERT INTO atom.trading_account
            (investor_id, broker_id, broker_client_code, execution_mode, egress_ip, proxy_url,
             status)
        SELECT %s, broker_id, %s, %s, %s, %s, 'ACTIVE'
        FROM atom.broker WHERE broker_code = %s
        RETURNING trading_account_id
        """,
        (investor_id, broker_client_code, execution_mode, egress_ip, proxy_url, broker_code),
    )
    return int(row["trading_account_id"])


def list_accounts(conn: Conn) -> list[dict[str, Any]]:
    return fetch_all(conn, _ACCOUNT_SELECT + " ORDER BY i.display_name, b.broker_code")


def get_account(conn: Conn, account_id: int) -> dict[str, Any]:
    return fetch_exactly_one(
        conn, _ACCOUNT_SELECT + " WHERE a.trading_account_id = %s", (account_id,)
    )


def mark_onboarded(conn: Conn, account_id: int) -> None:
    execute_expecting(
        conn,
        "UPDATE atom.trading_account SET onboarded_at = now() "
        "WHERE trading_account_id = %s AND onboarded_at IS NULL",
        (account_id,),
        rows=1,
    )


# ------------------------------------------------------------------ sessions


def get_session(conn: Conn, account_id: int, trade_date: date) -> dict[str, Any] | None:
    return fetch_one(
        conn,
        "SELECT * FROM atom.broker_session WHERE trading_account_id = %s AND trade_date = %s",
        (account_id, trade_date),
    )


def record_session(
    conn: Conn,
    *,
    account_id: int,
    trade_date: date,
    status: str,
    secret_ref: str | None,
    obtained_at: datetime | None = None,
    verified_at: datetime | None = None,
) -> None:
    """Upsert today's session row. One row per (account, day) by constraint."""
    execute(
        conn,
        """
        INSERT INTO atom.broker_session
            (trading_account_id, trade_date, status, secret_ref, obtained_at, verified_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (trading_account_id, trade_date) DO UPDATE SET
            status      = EXCLUDED.status,
            secret_ref  = EXCLUDED.secret_ref,
            obtained_at = COALESCE(EXCLUDED.obtained_at, atom.broker_session.obtained_at),
            verified_at = COALESCE(EXCLUDED.verified_at, atom.broker_session.verified_at),
            cleared_at  = NULL
        """,
        (account_id, trade_date, status, secret_ref, obtained_at, verified_at),
    )


def mark_session(conn: Conn, *, account_id: int, trade_date: date, status: str) -> None:
    """VALID after a successful probe, INVALID after a failed one."""
    execute(
        conn,
        """
        UPDATE atom.broker_session
        SET status = %s,
            verified_at = CASE WHEN %s = 'VALID' THEN now() ELSE verified_at END
        WHERE trading_account_id = %s AND trade_date = %s AND status <> 'CLEARED'
        """,
        (status, status, account_id, trade_date),
    )


def clear_session(conn: Conn, *, account_id: int, trade_date: date) -> None:
    """The secret is deleted by the caller; the reference goes with it."""
    execute(
        conn,
        """
        UPDATE atom.broker_session
        SET status = 'CLEARED', secret_ref = NULL, cleared_at = now()
        WHERE trading_account_id = %s AND trade_date = %s
        """,
        (account_id, trade_date),
    )


def account_ref(conn: Conn, account_id: int, trade_date: date) -> AccountRef:
    """What an adapter needs to act for this account today.

    ``secret_ref`` is set only while today's session is live. A CLEARED or
    INVALID session yields ``None``, and the adapter then refuses with a message
    that says to generate a token — rather than trying a dead one.
    """
    acct = get_account(conn, account_id)
    session = get_session(conn, account_id, trade_date)
    live = session is not None and session["status"] in ("PENDING", "VALID")
    return AccountRef(
        trading_account_id=account_id,
        broker_code=str(acct["broker_code"]),
        broker_client_id=str(acct["broker_client_code"]),
        proxy_url=acct["proxy_url"],
        egress_ip=acct["egress_ip"],
        secret_ref=session["secret_ref"] if live and session else None,
    )


# ------------------------------------------------------------------- audit


def audit(
    conn: Conn,
    *,
    actor: str,
    action: str,
    entity: str,
    entity_id: int | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    from psycopg.types.json import Jsonb

    execute(
        conn,
        "INSERT INTO atom.action_audit (actor, action, entity, entity_id, payload) "
        "VALUES (%s, %s, %s, %s, %s)",
        (actor, action, entity, entity_id, Jsonb(payload) if payload is not None else None),
    )


def recent_audit(conn: Conn, limit: int = 100) -> list[dict[str, Any]]:
    return fetch_all(
        conn, "SELECT * FROM atom.action_audit ORDER BY occurred_at DESC LIMIT %s", (limit,)
    )
