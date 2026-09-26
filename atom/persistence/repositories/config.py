"""Configuration values. No defaults: an absent row is absent (D-037, D-039)."""

from __future__ import annotations

from typing import Any

from psycopg import Connection

from atom.persistence.db import execute, fetch_all, fetch_exactly_one, fetch_one

Conn = Connection[Any]


def keys(conn: Conn) -> list[dict[str, Any]]:
    return fetch_all(conn, "SELECT * FROM atom.config_key ORDER BY scope, key_name")


def _key(conn: Conn, key_name: str) -> dict[str, Any]:
    return fetch_exactly_one(conn, "SELECT * FROM atom.config_key WHERE key_name = %s", (key_name,))


def account_values(conn: Conn, account_id: int, universe_id: int) -> list[dict[str, Any]]:
    return fetch_all(
        conn,
        """
        SELECT k.key_name, k.scope, k.value_type, ac.category_code, ac.value_text,
               ac.is_configured, ac.version, ac.updated_by, ac.updated_at
        FROM atom.account_config ac
        JOIN atom.config_key k ON k.config_key_id = ac.config_key_id
        WHERE ac.trading_account_id = %s AND ac.universe_id = %s
        ORDER BY k.key_name, ac.category_code
        """,
        (account_id, universe_id),
    )


def global_values(conn: Conn) -> list[dict[str, Any]]:
    return fetch_all(
        conn,
        """
        SELECT k.key_name, k.value_type, g.value_text, g.is_configured, g.version,
               g.updated_by, g.updated_at
        FROM atom.global_config g JOIN atom.config_key k ON k.config_key_id = g.config_key_id
        ORDER BY k.key_name
        """,
    )


def set_account_value(
    conn: Conn,
    *,
    account_id: int,
    universe_id: int,
    key_name: str,
    category_code: str | None,
    value_text: str | None,
    updated_by: str,
) -> None:
    """Write one value and its history row. ``None`` stores an explicit NULL
    (D-039) — "switched off" — which is a different fact from never set."""
    key = _key(conn, key_name)
    current = fetch_one(
        conn,
        """
        SELECT account_config_id, value_text FROM atom.account_config
        WHERE trading_account_id = %s AND universe_id = %s AND config_key_id = %s
          AND category_code IS NOT DISTINCT FROM %s
        """,
        (account_id, universe_id, key["config_key_id"], category_code),
    )
    if current is None:
        row = fetch_exactly_one(
            conn,
            """
            INSERT INTO atom.account_config
                (trading_account_id, config_key_id, universe_id, category_code, value_text,
                 is_configured, updated_by)
            VALUES (%s, %s, %s, %s, %s, true, %s)
            RETURNING account_config_id
            """,
            (account_id, key["config_key_id"], universe_id, category_code, value_text, updated_by),
        )
        config_id, old = row["account_config_id"], None
    else:
        if current["value_text"] == value_text:
            return
        execute(
            conn,
            "UPDATE atom.account_config SET value_text = %s, is_configured = true, "
            "version = version + 1, updated_by = %s, updated_at = now() "
            "WHERE account_config_id = %s",
            (value_text, updated_by, current["account_config_id"]),
        )
        config_id, old = current["account_config_id"], current["value_text"]
    execute(
        conn,
        "INSERT INTO atom.config_history (account_config_id, old_value, new_value, changed_by) "
        "VALUES (%s, %s, %s, %s)",
        (config_id, old, value_text, updated_by),
    )


def set_global_value(conn: Conn, *, key_name: str, value_text: str | None, updated_by: str) -> None:
    key = _key(conn, key_name)
    current = fetch_one(
        conn,
        "SELECT value_text FROM atom.global_config WHERE config_key_id = %s",
        (key["config_key_id"],),
    )
    if current is not None and current["value_text"] == value_text:
        return
    execute(
        conn,
        """
        INSERT INTO atom.global_config (config_key_id, value_text, updated_by)
        VALUES (%s, %s, %s)
        ON CONFLICT (config_key_id) DO UPDATE SET
            value_text = EXCLUDED.value_text, is_configured = true,
            version = atom.global_config.version + 1,
            updated_by = EXCLUDED.updated_by, updated_at = now()
        """,
        (key["config_key_id"], value_text, updated_by),
    )
    execute(
        conn,
        "INSERT INTO atom.global_config_history (config_key_id, old_value, new_value, changed_by) "
        "VALUES (%s, %s, %s, %s)",
        (
            key["config_key_id"],
            None if current is None else current["value_text"],
            value_text,
            updated_by,
        ),
    )


def global_value(conn: Conn, key_name: str) -> tuple[bool, str | None]:
    """``(is_set, value)``. ``(False, None)`` means never configured."""
    row = fetch_one(
        conn,
        """
        SELECT g.value_text FROM atom.global_config g
        JOIN atom.config_key k ON k.config_key_id = g.config_key_id
        WHERE k.key_name = %s AND g.is_configured
        """,
        (key_name,),
    )
    return (False, None) if row is None else (True, row["value_text"])
