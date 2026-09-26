"""Instruments, their broker identifiers, and the resolver adapters are given.

Resolution is by ISIN and nothing else (D-187): symbols collide across
exchanges and get renamed by corporate actions, so a symbol match is how an
order lands on the wrong security.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from psycopg import Connection

from atom.domain.models import CanonicalInstrument
from atom.persistence.db import execute, fetch_all, fetch_exactly_one, fetch_one

Conn = Connection[Any]


def upsert_instrument(
    conn: Conn,
    *,
    isin: str,
    symbol: str,
    name: str,
    instrument_type: str,
    asset_class: str,
    tick_size: Decimal | None = None,
    exchange: str = "NSE",
    status: str = "ACTIVE",
    status_reason: str | None = None,
) -> int:
    """Insert, or refresh the descriptive fields of, one instrument.

    ``status`` is written only on INSERT. An instrument an operator has BLOCKED
    must not be silently reactivated because a reference file was re-imported.
    """
    row = fetch_exactly_one(
        conn,
        """
        INSERT INTO atom.instrument
            (isin, exchange, symbol, name, instrument_type, asset_class, tick_size,
             status, status_reason, status_changed_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
        ON CONFLICT (isin, exchange) DO UPDATE SET
            symbol    = EXCLUDED.symbol,
            name      = EXCLUDED.name,
            tick_size = COALESCE(EXCLUDED.tick_size, atom.instrument.tick_size)
        RETURNING instrument_id
        """,
        (
            isin,
            exchange,
            symbol,
            name,
            instrument_type,
            asset_class,
            tick_size,
            status,
            status_reason,
        ),
    )
    return int(row["instrument_id"])


def upsert_broker_instrument(
    conn: Conn,
    *,
    broker_id: int,
    instrument_id: int,
    broker_token: str,
    broker_symbol: str,
    tradable: bool,
) -> str | None:
    """Returns the PREVIOUS token when it changed, so the caller can log it.

    RUN-LIFECYCLE.md 4: a broker token that changed for an existing ISIN updates
    the row and logs it — a silent change would route the next order to a
    different security.
    """
    previous = fetch_one(
        conn,
        "SELECT broker_token FROM atom.broker_instrument "
        "WHERE broker_id = %s AND instrument_id = %s",
        (broker_id, instrument_id),
    )
    execute(
        conn,
        """
        INSERT INTO atom.broker_instrument
            (broker_id, instrument_id, broker_token, broker_symbol, tradable, synced_at)
        VALUES (%s, %s, %s, %s, %s, now())
        ON CONFLICT (broker_id, instrument_id) DO UPDATE SET
            broker_token  = EXCLUDED.broker_token,
            broker_symbol = EXCLUDED.broker_symbol,
            tradable      = EXCLUDED.tradable,
            synced_at     = now()
        """,
        (broker_id, instrument_id, broker_token, broker_symbol, tradable),
    )
    if previous and previous["broker_token"] != broker_token:
        return str(previous["broker_token"])
    return None


def upsert_classification(
    conn: Conn,
    *,
    instrument_id: int,
    bucket: str,
    tier2_group: str,
    tier1_index: str,
    assignment_status: str,
    assigned_by: str,
) -> None:
    execute(
        conn,
        """
        INSERT INTO atom.instrument_classification
            (instrument_id, bucket, tier2_group, tier1_index, assignment_status, assigned_by,
             assigned_at)
        VALUES (%s, %s, %s, %s, %s, %s, now())
        ON CONFLICT (instrument_id) DO UPDATE SET
            bucket = EXCLUDED.bucket, tier2_group = EXCLUDED.tier2_group,
            tier1_index = EXCLUDED.tier1_index, assignment_status = EXCLUDED.assignment_status,
            assigned_by = EXCLUDED.assigned_by, assigned_at = now()
        """,
        (instrument_id, bucket, tier2_group, tier1_index, assignment_status, assigned_by),
    )


def search(
    conn: Conn, query: str, *, broker_id: int | None, limit: int = 50
) -> list[dict[str, Any]]:
    pattern = f"%{query.strip().upper()}%"
    return fetch_all(
        conn,
        """
        SELECT i.instrument_id, i.isin, i.symbol, i.name, i.asset_class, i.instrument_type,
               i.tick_size, i.status, c.bucket, c.tier1_index,
               bi.broker_token, bi.tradable
        FROM atom.instrument i
        LEFT JOIN atom.instrument_classification c ON c.instrument_id = i.instrument_id
        LEFT JOIN atom.broker_instrument bi
               ON bi.instrument_id = i.instrument_id AND bi.broker_id = %s
        WHERE upper(i.symbol) LIKE %s OR upper(i.name) LIKE %s OR i.isin = %s
        ORDER BY i.symbol
        LIMIT %s
        """,
        (broker_id, pattern, pattern, query.strip().upper(), limit),
    )


def by_ids(conn: Conn, instrument_ids: list[int], *, broker_id: int | None) -> list[dict[str, Any]]:
    if not instrument_ids:
        return []
    return fetch_all(
        conn,
        """
        SELECT i.*, bi.broker_token, bi.tradable
        FROM atom.instrument i
        LEFT JOIN atom.broker_instrument bi
               ON bi.instrument_id = i.instrument_id AND bi.broker_id = %s
        WHERE i.instrument_id = ANY(%s)
        """,
        (broker_id, instrument_ids),
    )


def broker_id_for(conn: Conn, broker_code: str) -> int:
    row = fetch_exactly_one(
        conn, "SELECT broker_id FROM atom.broker WHERE broker_code = %s", (broker_code,)
    )
    return int(row["broker_id"])


def isin_index(conn: Conn) -> dict[str, int]:
    rows = fetch_all(conn, "SELECT isin, instrument_id FROM atom.instrument WHERE exchange = 'NSE'")
    return {str(r["isin"]): int(r["instrument_id"]) for r in rows}


def counts(conn: Conn, *, broker_id: int) -> dict[str, int]:
    row = fetch_exactly_one(
        conn,
        """
        SELECT (SELECT count(*) FROM atom.instrument) AS instruments,
               (SELECT count(*) FROM atom.broker_instrument WHERE broker_id = %s) AS mapped,
               (SELECT count(*) FROM atom.instrument_classification) AS classified
        """,
        (broker_id,),
    )
    return {k: int(v) for k, v in row.items()}


def _asset_class_for_unknown(isin: str | None) -> str:
    return "EQUITY"


class DbInstrumentResolver:
    """The engine's implementation of ``atom.adapters.base.InstrumentResolver``.

    Caches for the lifetime of one unit of work. An instrument met for the first
    time — typically a holding the operator bought by hand — is registered with
    status ``REVIEW``, which the tradability gate refuses. ATOM will show it and
    reconcile it, and will not trade it until someone classifies it.
    """

    def __init__(self, conn: Conn, broker_id: int) -> None:
        self._conn = conn
        self._broker_id = broker_id
        self._by_token: dict[str, int] | None = None
        self._by_id: dict[int, str] = {}

    def _load(self) -> dict[str, int]:
        if self._by_token is None:
            rows = fetch_all(
                self._conn,
                "SELECT broker_token, instrument_id FROM atom.broker_instrument "
                "WHERE broker_id = %s",
                (self._broker_id,),
            )
            self._by_token = {str(r["broker_token"]): int(r["instrument_id"]) for r in rows}
            self._by_id = {v: k for k, v in self._by_token.items()}
        return self._by_token

    def instrument_id_for(self, broker_token: str) -> int | None:
        return self._load().get(broker_token)

    def broker_token_for(self, instrument_id: int) -> str:
        self._load()
        token = self._by_id.get(instrument_id)
        if token is None:
            raise LookupError(
                f"instrument {instrument_id} has no broker token for broker {self._broker_id}; "
                "run the instrument sync before trading it"
            )
        return token

    def register(self, instrument: CanonicalInstrument) -> int:
        if not instrument.isin:
            raise LookupError(
                f"cannot register {instrument.broker_symbol}: no ISIN, and instruments are "
                "never matched on symbol alone (D-187)"
            )
        isin = instrument.isin
        instrument_id = upsert_instrument(
            self._conn,
            isin=isin,
            symbol=instrument.symbol,
            name=instrument.name,
            instrument_type="ETF" if isin.startswith("INF") else "EQUITY",
            asset_class=_asset_class_for_unknown(isin),
            exchange=instrument.exchange,
            status="REVIEW",
            status_reason="registered from a broker holding; classify before ATOM may trade it",
        )
        upsert_broker_instrument(
            self._conn,
            broker_id=self._broker_id,
            instrument_id=instrument_id,
            broker_token=instrument.broker_token,
            broker_symbol=instrument.broker_symbol,
            tradable=instrument.tradable,
        )
        self._load()[instrument.broker_token] = instrument_id
        self._by_id[instrument_id] = instrument.broker_token
        return instrument_id
