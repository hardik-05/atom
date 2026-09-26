"""Upstox payloads → canonical models. Pure functions, no I/O.

Everything the adapter knows about the *shape* of an Upstox response lives here,
so that a vendor change is a change to this file and to the fixtures that test
it — and to nothing above the adapter boundary (D-185).

Numbers arrive as JSON floats. The adapter parses responses with
``parse_float=Decimal``, so every price reaching this module is already exact;
``_dec`` still refuses a float, because one slipping through would round a price
in binary and nobody would see it happen.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from atom.domain.enums import GttStatus, OrderStatus
from atom.domain.models import (
    BrokerProfile,
    CanonicalCandle,
    CanonicalFill,
    CanonicalFunds,
    CanonicalHolding,
    CanonicalInstrument,
    CanonicalQuote,
    GttState,
    OrderState,
)
from atom.domain.money import ZERO, money
from atom.infra.clock import IST

EQUITY_SEGMENTS = frozenset({"NSE_EQ", "BSE_EQ"})

Json = Mapping[str, Any]


def _dec(value: object) -> Decimal:
    if value is None:
        return ZERO
    if isinstance(value, float):
        raise TypeError("float reached the mapper — parse with parse_float=Decimal")
    return money(value)


def _opt_dec(value: object) -> Decimal | None:
    return None if value is None else _dec(value)


def _int(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        raise TypeError("bool is not a quantity")
    if isinstance(value, (int, Decimal)):
        return int(value)
    if isinstance(value, str):
        return int(Decimal(value))
    raise TypeError(f"not a quantity: {value!r}")


def isin_from_token(instrument_key: str) -> str | None:
    """``NSE_EQ|INF204KB14I2`` → ``INF204KB14I2``. Upstox's key *is* the ISIN."""
    segment, _, rest = instrument_key.partition("|")
    if segment in EQUITY_SEGMENTS and len(rest) == 12:
        return rest
    return None


def _ts(value: object) -> datetime:
    """Upstox timestamps carry +05:30; a bare one is read as IST, never as UTC."""
    if not value:
        return datetime.now(UTC)
    text = str(value).replace(" ", "T")
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=IST)


# ----------------------------------------------------------------- session


def profile(data: Json) -> BrokerProfile:
    return BrokerProfile(
        broker_client_id=str(data["user_id"]),
        display_name=str(data.get("user_name") or data["user_id"]),
        is_active=bool(data.get("is_active", False)),
        # Deliberately not the email: the console shows whose account this is, and
        # an email address adds PII to every screen and log line for no decision.
        flags={
            "poa": bool(data.get("poa", False)),
            "ddpi": bool(data.get("ddpi", False)),
            "exchanges": list(data.get("exchanges") or []),
            "products": list(data.get("products") or []),
            "user_type": data.get("user_type"),
        },
    )


# ------------------------------------------------------------------- funds


def funds(data: Json, *, as_of: datetime) -> CanonicalFunds:
    """``GET /v2/user/get-funds-and-margin?segment=SEC``.

    Upstox nests equity funds under ``equity``; a response that has already
    been flattened is accepted too, rather than silently reading zeros.
    """
    equity = data.get("equity", data)
    components = {
        key: _dec(value)
        for key, value in equity.items()
        if value is not None and not isinstance(value, (dict, list, bool, str))
    }
    return CanonicalFunds(
        available_cash=_dec(equity.get("available_margin")),
        used_margin=_dec(equity.get("used_margin")),
        as_of=as_of,
        components=components,
    )


# ---------------------------------------------------------------- holdings

InstrumentLookup = Callable[[CanonicalInstrument], int]
"""Returns ATOM's instrument_id for an Upstox instrument, registering it if new."""


def instrument_from_holding(row: Json) -> CanonicalInstrument:
    symbol = str(row.get("trading_symbol") or row.get("tradingsymbol") or "")
    return CanonicalInstrument(
        symbol=symbol,
        exchange=str(row.get("exchange") or "NSE"),
        name=str(row.get("company_name") or symbol),
        broker_token=str(row["instrument_token"]),
        broker_symbol=symbol,
        isin=row.get("isin") or isin_from_token(str(row["instrument_token"])),
    )


def holding(row: Json, instrument_id: int) -> CanonicalHolding:
    """UPSTOX-ADAPTER.md 5.1 and 6.1.

    ``total = quantity + t1_quantity`` answers "do our books agree".
    ``free = quantity - cnc_used_quantity - collateral_quantity`` answers "can a
    sell execute": ``cnc_used_quantity`` covers stock blocked by a resting or an
    already-filled sell today, and T1 stock is never free.
    """
    quantity = _int(row.get("quantity"))
    t1 = _int(row.get("t1_quantity"))
    used = _int(row.get("cnc_used_quantity"))
    pledged = _int(row.get("collateral_quantity"))
    return CanonicalHolding(
        instrument_id=instrument_id,
        total_quantity=quantity + t1,
        average_price=_dec(row.get("average_price")),
        free_quantity=max(0, quantity - used - pledged),
        last_price=_opt_dec(row.get("last_price")),
        pledged_quantity=pledged,
        unsettled_quantity=t1,
        broker_flags={
            "symbol": row.get("trading_symbol") or row.get("tradingsymbol"),
            "isin": row.get("isin"),
            "collateral_type": row.get("collateral_type"),
            "haircut": str(row["haircut"]) if row.get("haircut") is not None else None,
        },
    )


def delivery_position(row: Json, instrument_id: int) -> CanonicalHolding | None:
    """Today's delivery buys sit in positions until they move to holdings at T+1.

    Anything that is not product ``D`` is ignored: ATOM trades delivery only
    (D-207), so an intraday position here is someone else's.
    """
    if str(row.get("product")) != "D":
        return None
    quantity = _int(row.get("quantity"))
    if quantity == 0:
        return None
    return CanonicalHolding(
        instrument_id=instrument_id,
        total_quantity=quantity,
        average_price=_dec(row.get("buy_price") or row.get("average_price")),
        free_quantity=None,
        last_price=_opt_dec(row.get("last_price")),
        unsettled_quantity=max(0, quantity),
        broker_flags={"source": "positions", "symbol": row.get("trading_symbol")},
    )


# ------------------------------------------------------------------ quotes


def quote(row: Json, instrument_id: int) -> CanonicalQuote:
    """``GET /v2/market-quote/quotes``. Keyed ``NSE_EQ:SYMBOL`` in the response,
    which is why the caller maps by ``instrument_token`` inside the value and
    never by the dictionary key."""
    last = _dec(row.get("last_price"))
    net_change = row.get("net_change")
    previous_close = None if net_change is None else last - _dec(net_change)
    return CanonicalQuote(
        instrument_id=instrument_id,
        last_price=last,
        as_of=_ts(row.get("timestamp") or row.get("last_trade_time")),
        close_price=previous_close,
        volume=_int(row.get("volume")) if row.get("volume") is not None else None,
    )


def candles(rows: list[list[Any]]) -> list[CanonicalCandle]:
    """``[[timestamp, open, high, low, close, volume, oi], ...]``, newest first.

    Returned oldest first, one bar per date. A duplicate date keeps the later
    row, which is what Upstox would have corrected it to.
    """
    by_date: dict[date, CanonicalCandle] = {}
    for row in rows:
        stamp, open_, high, low, close = row[0], row[1], row[2], row[3], row[4]
        volume = row[5] if len(row) > 5 else None
        day = _ts(stamp).astimezone(IST).date()
        by_date[day] = CanonicalCandle(
            trade_date=day,
            open=_dec(open_),
            high=_dec(high),
            low=_dec(low),
            close=_dec(close),
            volume=None if volume is None else _int(volume),
        )
    return [by_date[d] for d in sorted(by_date)]


# ------------------------------------------------------------- instruments


def instrument(row: Json, *, suspended: frozenset[str] = frozenset()) -> CanonicalInstrument | None:
    """One row of ``NSE.json.gz``. Non-equity segments are skipped.

    ``tick_size`` in the JSON master is in **paise** — ``5.0`` for a 5-paise
    tick — where the deprecated CSV used rupees (Q-300). It is converted here and
    carried for cross-checking only; ATOM prices against its own tick (D-209).
    """
    if row.get("segment") not in EQUITY_SEGMENTS:
        return None
    isin = row.get("isin")
    tick = row.get("tick_size")
    return CanonicalInstrument(
        symbol=str(row["trading_symbol"]),
        exchange=str(row.get("exchange") or "NSE"),
        name=str(row.get("name") or row["trading_symbol"]),
        broker_token=str(row["instrument_key"]),
        broker_symbol=str(row["trading_symbol"]),
        isin=isin,
        lot_size=_int(row.get("lot_size") or 1),
        tick_size=None if tick is None else (_dec(tick) / 100).quantize(Decimal("0.0001")),
        tradable=isin not in suspended,
        instrument_type=row.get("instrument_type"),
        broker_flags={"security_type": row.get("security_type")},
    )


# ------------------------------------------------------------------ orders

_STATUS: dict[str, OrderStatus] = {
    "complete": OrderStatus.FILLED,
    "rejected": OrderStatus.REJECTED,
    "cancelled": OrderStatus.CANCELLED,
}


def order_status(raw: str, filled_quantity: int) -> OrderStatus:
    """UPSTOX-ADAPTER.md 8. Anything unrecognised is IN_FLIGHT, never terminal
    (D-180): guessing "cancelled" for a status we have not seen would make ATOM
    re-place an order that is about to fill."""
    key = raw.strip().lower()
    if key in _STATUS:
        return _STATUS[key]
    if key == "open":
        return OrderStatus.PARTIAL if filled_quantity > 0 else OrderStatus.PLACED
    return OrderStatus.IN_FLIGHT


def order_state(row: Json) -> OrderState:
    filled = _int(row.get("filled_quantity"))
    raw = str(row.get("status") or "")
    status = order_status(raw, filled)
    return OrderState(
        broker_order_id=str(row["order_id"]),
        status=status,
        raw_status=raw,
        filled_quantity=filled,
        pending_quantity=_int(row.get("pending_quantity")),
        average_price=_opt_dec(row.get("average_price")) if filled else None,
        client_ref=row.get("tag"),
        reject_reason=(row.get("status_message") or None)
        if status in (OrderStatus.REJECTED, OrderStatus.CANCELLED)
        else None,
    )


def fill(row: Json) -> CanonicalFill:
    return CanonicalFill(
        broker_order_id=str(row["order_id"]),
        broker_trade_id=str(row["trade_id"]),
        quantity=_int(row.get("quantity")),
        fill_price=_dec(row.get("average_price")),
        filled_at=_ts(row.get("exchange_timestamp") or row.get("order_timestamp")),
    )


_GTT_STATUS: dict[str, GttStatus] = {
    "scheduled": GttStatus.ACTIVE,
    "pending": GttStatus.ACTIVE,
    "active": GttStatus.ACTIVE,
    "triggered": GttStatus.TRIGGERED,
    "completed": GttStatus.TRIGGERED,
    "cancelled": GttStatus.CANCELLED,
    "expired": GttStatus.EXPIRED,
    "failed": GttStatus.REJECTED,
    "rejected": GttStatus.REJECTED,
}


def gtt_state(row: Json, instrument_id: int | None) -> GttState:
    """``is_ours`` is always False here. Upstox GTTs carry no tag (Q-297), so
    ownership is decided solely from the GTT ids ATOM stored when it placed them
    — which the engine knows and the adapter deliberately does not."""
    rules = row.get("rules") or [{}]
    first = rules[0]
    raw = str(first.get("status") or row.get("status") or "")
    return GttState(
        broker_gtt_id=str(row["gtt_order_id"]),
        status=_GTT_STATUS.get(raw.lower(), GttStatus.UNKNOWN),
        raw_status=raw,
        instrument_id=instrument_id,
        trigger_price=_opt_dec(first.get("trigger_price")),
        quantity=_int(row.get("quantity")) or None,
        is_ours=False,
        broker_flags={
            "transaction_type": row.get("transaction_type"),
            "instrument_token": row.get("instrument_token"),
            # Once triggered, the GTT's rule carries the id of the ORDER it became.
            # Settlement follows that id to the fills; without it a triggered GTT
            # sell is a sale ATOM cannot attach to any lot.
            "triggered_order_id": first.get("order_id"),
        },
    )
