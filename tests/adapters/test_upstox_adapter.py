"""The Upstox adapter against recorded-shape responses.

No network: an ``httpx.MockTransport`` answers every request, and each test
asserts both what the adapter SENT and what it made of the reply. The payload
shapes follow UPSTOX-ADAPTER.md; a vendor change is caught here first.
"""

from __future__ import annotations

import gzip
import json
from datetime import date
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from atom.adapters.base import BrokerAdapter
from atom.adapters.upstox import UpstoxAdapter
from atom.adapters.upstox import map as m
from atom.domain.enums import GttStatus, OrderStatus, Side
from atom.domain.errors import (
    AuthError,
    InsufficientFundsError,
    IpBlockedError,
    TransientError,
    UnknownError,
    ValidationError,
)
from atom.domain.models import AccountRef, CanonicalInstrument, GttIntent, OrderIntent
from atom.infra.clock import today_ist
from atom.infra.secrets import MemorySecretStore, broker_secret_path, session_path

GOLD = "NSE_EQ|INF204KB17I5"
NIFTY = "NSE_EQ|INF204KB14I2"
REDIRECT = "https://app.example.com/brokers/upstox/callback"


class DictResolver:
    def __init__(self) -> None:
        self.by_token: dict[str, int] = {GOLD: 1, NIFTY: 2}
        self.registered: list[CanonicalInstrument] = []

    def instrument_id_for(self, broker_token: str) -> int | None:
        return self.by_token.get(broker_token)

    def broker_token_for(self, instrument_id: int) -> str:
        for token, iid in self.by_token.items():
            if iid == instrument_id:
                return token
        raise KeyError(instrument_id)

    def register(self, instrument: CanonicalInstrument) -> int:
        self.registered.append(instrument)
        new_id = max(self.by_token.values()) + 1
        self.by_token[instrument.broker_token] = new_id
        return new_id


class Recorder:
    """A transport that answers from a route table and records every request."""

    def __init__(self, routes: dict[tuple[str, str], httpx.Response | Any]) -> None:
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = (request.method, request.url.path)
        answer = self.routes.get(key)
        if answer is None:
            return httpx.Response(
                404, json={"status": "error", "errors": [{"message": "no route"}]}
            )
        if isinstance(answer, httpx.Response):
            return answer
        return httpx.Response(200, json=answer)


def make(routes: dict[tuple[str, str], Any], *, with_token: bool = True):
    recorder = Recorder(routes)
    secrets = MemorySecretStore(
        {
            broker_secret_path("UPSTOX", 7, "api_key"): "key-123",
            broker_secret_path("UPSTOX", 7, "api_secret"): "secret-456",
        }
    )
    ref = None
    if with_token:
        ref = session_path(7, today_ist())
        secrets.put(ref, "tok-789")
    account = AccountRef(
        trading_account_id=7,
        broker_code="UPSTOX",
        broker_client_id="ABC123",
        proxy_url=None,
        egress_ip=None,
        secret_ref=ref,
    )
    resolver = DictResolver()
    adapter = UpstoxAdapter(
        secrets=secrets,
        resolver=resolver,
        redirect_uri=REDIRECT,
        transport=httpx.MockTransport(recorder),
    )
    return adapter, account, recorder, secrets, resolver


def ok(data: Any) -> dict[str, Any]:
    return {"status": "success", "data": data}


def test_satisfies_the_protocol() -> None:
    adapter, *_ = make({})
    assert isinstance(adapter, BrokerAdapter)


# ------------------------------------------------------------------ session


def test_auth_url_carries_key_redirect_and_account_state() -> None:
    adapter, account, *_ = make({}, with_token=False)
    url = adapter.build_auth_url(account)
    assert url is not None
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.netloc == "api.upstox.com"
    assert query["client_id"] == ["key-123"]
    assert query["redirect_uri"] == [REDIRECT]
    assert query["response_type"] == ["code"]
    assert query["state"] == ["7"]


def test_exchange_stores_the_token_and_never_returns_it() -> None:
    adapter, account, recorder, secrets, _ = make(
        {
            ("POST", "/v2/login/authorization/token"): {
                "user_id": "ABC123",
                "user_name": "Nidhi",
                "access_token": "fresh-token",
                "poa": False,
                "is_active": True,
            }
        },
        with_token=False,
    )
    token = adapter.exchange_code(account, "  the-code  ")

    assert token.secret_ref == session_path(7, today_ist())
    assert secrets.get(token.secret_ref) == "fresh-token"
    assert token.broker_client_id == "ABC123"
    assert "fresh-token" not in repr(token)

    sent = parse_qs(recorder.requests[0].content.decode())
    assert sent["code"] == ["the-code"]
    assert sent["client_secret"] == ["secret-456"]
    assert sent["redirect_uri"] == [REDIRECT]
    assert sent["grant_type"] == ["authorization_code"]


def test_a_failed_exchange_is_not_retried() -> None:
    """A code is single-use; a retry either fails or looks like a second login."""
    adapter, account, recorder, *_ = make(
        {("POST", "/v2/login/authorization/token"): httpx.Response(503, text="busy")},
        with_token=False,
    )
    with pytest.raises(TransientError):
        adapter.exchange_code(account, "code")
    assert len(recorder.requests) == 1


def test_an_empty_code_is_refused_before_any_request() -> None:
    adapter, account, recorder, *_ = make({}, with_token=False)
    with pytest.raises(ValidationError):
        adapter.exchange_code(account, "   ")
    assert recorder.requests == []


def test_probe_uses_the_profile_and_reports_the_client() -> None:
    adapter, account, recorder, *_ = make(
        {
            ("GET", "/v2/user/profile"): ok(
                {"user_id": "ABC123", "user_name": "Nidhi", "is_active": True, "poa": True}
            )
        }
    )
    probe = adapter.probe_token(account)
    assert probe.ok
    assert probe.flags["broker_client_id"] == "ABC123"
    assert recorder.requests[0].headers["Authorization"] == "Bearer tok-789"


def test_probe_is_false_not_an_exception_when_the_token_is_dead() -> None:
    adapter, account, *_ = make(
        {
            ("GET", "/v2/user/profile"): httpx.Response(
                401, json={"status": "error", "errors": [{"errorCode": "UDAPI100050"}]}
            )
        }
    )
    assert adapter.probe_token(account).ok is False


def test_no_token_today_is_an_auth_error_with_a_next_step() -> None:
    adapter, account, *_ = make({}, with_token=False)
    with pytest.raises(AuthError, match="Tokens screen"):
        adapter.fetch_funds(account)


# -------------------------------------------------------------------- reads


def test_funds_reads_the_equity_segment() -> None:
    adapter, account, recorder, *_ = make(
        {
            ("GET", "/v2/user/get-funds-and-margin"): ok(
                {"equity": {"available_margin": 25432.75, "used_margin": 1200.5, "payin_amount": 0}}
            )
        }
    )
    funds = adapter.fetch_funds(account)
    assert funds.available_cash == Decimal("25432.7500")
    assert funds.used_margin == Decimal("1200.5000")
    assert recorder.requests[0].url.params["segment"] == "SEC"


def test_holdings_split_total_from_free() -> None:
    """UPSTOX-ADAPTER.md 6.1: T1 counts toward the total and never toward free."""
    adapter, account, *_ = make(
        {
            ("GET", "/v2/portfolio/long-term-holdings"): ok(
                [
                    {
                        "isin": "INF204KB17I5",
                        "instrument_token": GOLD,
                        "trading_symbol": "GOLDBEES",
                        "exchange": "NSE",
                        "company_name": "Nippon Gold",
                        "quantity": 50,
                        "t1_quantity": 10,
                        "cnc_used_quantity": 5,
                        "collateral_quantity": 3,
                        "average_price": 61.25,
                        "last_price": 64.1,
                    }
                ]
            )
        }
    )
    [h] = adapter.fetch_holdings(account)
    assert h.instrument_id == 1
    assert h.total_quantity == 60
    assert h.free_quantity == 42
    assert h.unsettled_quantity == 10
    assert h.average_price == Decimal("61.2500")


def test_an_unknown_holding_is_registered_by_isin() -> None:
    adapter, account, _, _, resolver = make(
        {
            ("GET", "/v2/portfolio/long-term-holdings"): ok(
                [
                    {
                        "isin": "INE002A01018",
                        "instrument_token": "NSE_EQ|INE002A01018",
                        "trading_symbol": "RELIANCE",
                        "quantity": 1,
                        "average_price": 2400,
                    }
                ]
            )
        }
    )
    [h] = adapter.fetch_holdings(account)
    assert resolver.registered[0].isin == "INE002A01018"
    assert h.instrument_id == resolver.by_token["NSE_EQ|INE002A01018"]


def test_quotes_are_matched_on_instrument_token_not_the_response_key() -> None:
    """The response is keyed ``NSE_EQ:SYMBOL``; the token inside is the truth."""
    adapter, account, recorder, *_ = make(
        {
            ("GET", "/v2/market-quote/quotes"): ok(
                {
                    "NSE_EQ:GOLDBEES": {
                        "instrument_token": GOLD,
                        "last_price": 64.12,
                        "net_change": 0.5,
                        "volume": 1234567,
                        "timestamp": "2026-09-26T15:29:59.000+05:30",
                    }
                }
            )
        }
    )
    [q] = adapter.fetch_quotes(account, [GOLD, GOLD])
    assert q.instrument_id == 1
    assert q.last_price == Decimal("64.1200")
    assert q.close_price == Decimal("63.6200")
    assert q.volume == 1234567
    assert recorder.requests[0].url.params["instrument_key"] == GOLD  # de-duplicated


def test_candles_come_back_oldest_first_and_within_range() -> None:
    adapter, account, recorder, *_ = make(
        {
            (
                "GET",
                "/v3/historical-candle/NSE_EQ|INF204KB17I5/days/1/2026-09-25/2026-09-23",
            ): ok(
                {
                    "candles": [
                        ["2026-09-25T00:00:00+05:30", 64, 64.5, 63.5, 64.2, 900, 0],
                        ["2026-09-24T00:00:00+05:30", 63, 63.9, 62.8, 63.7, 800, 0],
                        ["2026-09-23T00:00:00+05:30", 62, 63.1, 61.9, 62.9, 700, 0],
                    ]
                }
            )
        }
    )
    bars = adapter.fetch_daily_candles(account, GOLD, date(2026, 9, 23), date(2026, 9, 25))
    assert [b.trade_date for b in bars] == [date(2026, 9, 23), date(2026, 9, 24), date(2026, 9, 25)]
    assert bars[-1].close == Decimal("64.2000")
    assert "%7C" in str(recorder.requests[0].url)  # the pipe is escaped, not sent raw


# ------------------------------------------------------------------- writes


def test_place_order_is_a_delivery_limit_with_slicing_off() -> None:
    adapter, account, recorder, *_ = make(
        {("POST", "/v3/order/place"): ok({"order_ids": ["2509260001"]})}
    )
    state = adapter.place_order(
        account,
        OrderIntent(
            trading_account_id=7,
            universe_id=1,
            instrument_id=1,
            side=Side.BUY,
            quantity=150,
            limit_price=Decimal("64.05"),
            client_ref="atm2609260006a01",
        ),
    )
    sent = json.loads(recorder.requests[0].content)
    assert sent["order_type"] == "LIMIT"
    assert sent["product"] == "D"
    assert sent["slice"] is False
    assert sent["instrument_token"] == GOLD
    assert sent["price"] == "64.05"
    assert state.broker_order_id == "2509260001"
    assert state.status is OrderStatus.PLACED


def test_an_order_is_never_retried_blindly() -> None:
    """Upstox's tag is not idempotent: a retry after a 5xx could buy twice."""
    adapter, account, recorder, *_ = make(
        {("POST", "/v3/order/place"): httpx.Response(502, text="bad gateway")}
    )
    with pytest.raises(TransientError):
        adapter.place_order(
            account,
            OrderIntent(
                trading_account_id=7,
                universe_id=1,
                instrument_id=1,
                side=Side.BUY,
                quantity=1,
                limit_price=Decimal("10"),
                client_ref="atm2609260006a02",
            ),
        )
    assert len(recorder.requests) == 1


def test_gtt_is_a_single_entry_above_rule() -> None:
    adapter, account, recorder, *_ = make(
        {("POST", "/v3/order/gtt/place"): ok({"gtt_order_ids": ["GTT-1"]})}
    )
    state = adapter.place_gtt(
        account,
        GttIntent(
            instrument_id=2,
            quantity=10,
            trigger_price=Decimal("280.55"),
            limit_price=Decimal("280.55"),
            client_ref="atm2609260006a03",
        ),
    )
    sent = json.loads(recorder.requests[0].content)
    assert sent["type"] == "SINGLE"
    assert sent["rules"] == [
        {"strategy": "ENTRY", "trigger_type": "ABOVE", "trigger_price": "280.55"}
    ]
    assert state.is_ours and state.status is GttStatus.ACTIVE


# ------------------------------------------------------------------- errors


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (401, {"errors": [{"errorCode": "UDAPI100050", "message": "Invalid token"}]}, AuthError),
        (
            403,
            {"errors": [{"message": "Request from an IP not registered as static IP"}]},
            IpBlockedError,
        ),
        (
            400,
            {"errors": [{"message": "Insufficient funds to place order"}]},
            InsufficientFundsError,
        ),
        (400, {"errors": [{"message": "price is invalid"}]}, ValidationError),
        (403, {"errors": [{"message": "something new"}]}, UnknownError),
    ],
)
def test_errors_map_onto_the_canonical_taxonomy(status: int, body: dict, expected: type) -> None:
    adapter, account, *_ = make(
        {("GET", "/v2/user/get-funds-and-margin"): httpx.Response(status, json=body)}
    )
    with pytest.raises(expected):
        adapter.fetch_funds(account)


@pytest.mark.parametrize(
    ("raw", "filled", "expected"),
    [
        ("complete", 10, OrderStatus.FILLED),
        ("open", 0, OrderStatus.PLACED),
        ("open", 3, OrderStatus.PARTIAL),
        ("rejected", 0, OrderStatus.REJECTED),
        ("trigger pending", 0, OrderStatus.IN_FLIGHT),
        ("a status nobody has seen", 0, OrderStatus.IN_FLIGHT),
    ],
)
def test_unknown_status_is_in_flight_never_terminal(
    raw: str, filled: int, expected: OrderStatus
) -> None:
    assert m.order_status(raw, filled) is expected


# -------------------------------------------------------------- instruments


def test_instrument_master_converts_paise_and_marks_suspended() -> None:
    master = [
        {
            "segment": "NSE_EQ",
            "exchange": "NSE",
            "isin": "INF204KB17I5",
            "instrument_type": "EQ",
            "instrument_key": GOLD,
            "trading_symbol": "GOLDBEES",
            "name": "NIPPON GOLD ETF",
            "lot_size": 1,
            "tick_size": 1.0,
        },
        {
            "segment": "NSE_EQ",
            "isin": "INF000000001",
            "instrument_key": "NSE_EQ|INF000000001",
            "trading_symbol": "HALTED",
            "tick_size": 5.0,
        },
        {"segment": "NSE_FO", "instrument_key": "NSE_FO|1", "trading_symbol": "X"},
    ]
    suspended = [{"isin": "INF000000001"}]

    def handler(request: httpx.Request) -> httpx.Response:
        payload = suspended if "suspended" in request.url.path else master
        return httpx.Response(200, content=gzip.compress(json.dumps(payload).encode()))

    adapter = UpstoxAdapter(
        secrets=MemorySecretStore(),
        resolver=DictResolver(),
        redirect_uri=REDIRECT,
        transport=httpx.MockTransport(handler),
    )
    rows = {i.broker_symbol: i for i in adapter.fetch_instruments()}
    assert set(rows) == {"GOLDBEES", "HALTED"}
    assert rows["GOLDBEES"].tick_size == Decimal("0.0100")
    assert rows["HALTED"].tick_size == Decimal("0.0500")
    assert rows["GOLDBEES"].tradable is True
    assert rows["HALTED"].tradable is False
