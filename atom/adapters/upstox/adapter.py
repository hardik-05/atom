"""The Upstox adapter.

Researched in ``docs/03-brokers/adapters/UPSTOX-ADAPTER.md``. v2 for session,
portfolio, market quotes and funds; v3 for orders, GTT and historical candles.

Two injected collaborators keep this module free of the database:

* a ``SecretStore`` — the API key and secret are read from, and each day's
  token written to, SSM paths defined in ``atom.infra.secrets``
* an ``InstrumentResolver`` — Upstox's ``NSE_EQ|<ISIN>`` key is mapped to
  ATOM's ``instrument_id`` by the engine, which owns the instrument tables
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import quote as urlquote
from urllib.parse import urlencode

import httpx

from atom.adapters.base import InstrumentResolver, UnsupportedOperationError
from atom.adapters.client_ref import truncate_for
from atom.adapters.http import BrokerHttpClient
from atom.adapters.upstox import map as m
from atom.adapters.upstox.capabilities import UPSTOX
from atom.domain.enums import GttStatus, OrderStatus, Side, TokenProbe
from atom.domain.errors import (
    AuthError,
    BrokerError,
    InsufficientFundsError,
    InsufficientHoldingsError,
    IpBlockedError,
    UnknownError,
    ValidationError,
)
from atom.domain.models import (
    AccountRef,
    AuthorisationRequest,
    BrokerCapabilities,
    BrokerProfile,
    CanonicalCandle,
    CanonicalCashEvent,
    CanonicalCharges,
    CanonicalFill,
    CanonicalFunds,
    CanonicalHolding,
    CanonicalInstrument,
    CanonicalQuote,
    GttIntent,
    GttState,
    OrderIntent,
    OrderState,
    Token,
    TokenProbeResult,
)
from atom.infra.clock import today_ist
from atom.infra.secrets import SecretStore, broker_secret_path, session_path

API_BASE = "https://api.upstox.com"
AUTH_DIALOG = f"{API_BASE}/v2/login/authorization/dialog"
INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
SUSPENDED_URL = (
    "https://assets.upstox.com/market-quote/instruments/exchange/suspended-instrument.json.gz"
)
QUOTE_BATCH = 500

HttpFactory = Callable[[AccountRef | None], BrokerHttpClient]


def classify(response: httpx.Response, *, context: str) -> BrokerError:
    """Map a failed Upstox response onto the canonical error taxonomy.

    Matching is on Upstox's own error codes where they are documented and on the
    message otherwise. Anything unrecognised becomes ``UnknownError`` — which
    halts the account and preserves the payload — rather than a guess.
    """
    raw = response.text
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        body = {}
    errors = body.get("errors") or []
    first = errors[0] if errors and isinstance(errors[0], dict) else {}
    code = str(first.get("errorCode") or first.get("error_code") or "")
    message = str(first.get("message") or body.get("message") or "")
    text = f"{context}: {message or f'HTTP {response.status_code}'}"
    lowered = message.lower()

    if response.status_code == 401 or code in {"UDAPI100050", "UDAPI100016"}:
        return AuthError(text, broker="UPSTOX", raw=raw)
    if " ip" in f" {lowered}" and any(w in lowered for w in ("static", "whitelist", "register")):
        return IpBlockedError(text, broker="UPSTOX", raw=raw)
    if "insufficient" in lowered and ("fund" in lowered or "margin" in lowered):
        return InsufficientFundsError(text, broker="UPSTOX", raw=raw)
    if "insufficient" in lowered and ("holding" in lowered or "quantity" in lowered):
        return InsufficientHoldingsError(text, broker="UPSTOX", raw=raw)
    if response.status_code in (400, 422):
        return ValidationError(text, broker="UPSTOX", raw=raw)
    return UnknownError(text, broker="UPSTOX", raw=raw)


class UpstoxAdapter:
    capabilities: BrokerCapabilities = UPSTOX

    def __init__(
        self,
        *,
        secrets: SecretStore,
        resolver: InstrumentResolver,
        redirect_uri: str,
        default_proxy_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._secrets = secrets
        self._resolver = resolver
        self._redirect_uri = redirect_uri
        self._default_proxy = default_proxy_url
        self._transport = transport
        self._clients: dict[int | None, BrokerHttpClient] = {}

    # ---------------------------------------------------------------- plumbing
    def _client(self, account: AccountRef | None) -> BrokerHttpClient:
        key = None if account is None else account.trading_account_id
        client = self._clients.get(key)
        if client is None:
            client = BrokerHttpClient(
                base_url=API_BASE,
                proxy_url=(account.proxy_url if account else None) or self._default_proxy,
                broker_code="UPSTOX",
                orders_per_second=UPSTOX.orders_per_second,
                transport=self._transport,
            )
            self._clients[key] = client
        return client

    def close(self) -> None:
        for client in self._clients.values():
            client.close()
        self._clients.clear()

    def _token(self, account: AccountRef) -> str:
        if not account.secret_ref:
            raise AuthError(
                "no Upstox token for today — generate one from the Tokens screen",
                broker="UPSTOX",
            )
        return self._secrets.get(account.secret_ref)

    def _headers(self, account: AccountRef) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Api-Version": "2.0",
            "Authorization": f"Bearer {self._token(account)}",
        }

    def _call(
        self,
        account: AccountRef,
        method: str,
        path: str,
        *,
        context: str,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
        is_order: bool = False,
    ) -> Any:
        response = self._client(account).request(
            method,  # type: ignore[arg-type]
            path,
            headers=self._headers(account),
            params=params,
            json=json_body,
            is_order=is_order,
            # An order is never retried blindly: Upstox's tag is not idempotent, so
            # a retry after a timeout could place it twice (UPSTOX capabilities).
            retry=not is_order,
        )
        if not response.is_success:
            raise classify(response, context=context)
        body = response.json(parse_float=Decimal)
        if isinstance(body, dict) and body.get("status") == "error":
            raise classify(response, context=context)
        return body.get("data") if isinstance(body, dict) else body

    def _resolve(self, instrument: CanonicalInstrument) -> int:
        known = self._resolver.instrument_id_for(instrument.broker_token)
        return known if known is not None else self._resolver.register(instrument)

    # ----------------------------------------------------------------- session
    def build_auth_url(self, account: AccountRef) -> str | None:
        api_key = self._secrets.get(
            broker_secret_path("UPSTOX", account.trading_account_id, "api_key")
        )
        query = urlencode(
            {
                "response_type": "code",
                "client_id": api_key,
                "redirect_uri": self._redirect_uri,
                # Upstox echoes ``state`` to the redirect. The console uses it to
                # know which account a returning code belongs to without holding
                # any server-side state across the round trip.
                "state": str(account.trading_account_id),
            }
        )
        return f"{AUTH_DIALOG}?{query}"

    def exchange_code(self, account: AccountRef, code: str) -> Token:
        code = code.strip()
        if not code:
            raise ValidationError("empty authorisation code", broker="UPSTOX")
        aid = account.trading_account_id
        form = {
            "code": code,
            "client_id": self._secrets.get(broker_secret_path("UPSTOX", aid, "api_key")),
            "client_secret": self._secrets.get(broker_secret_path("UPSTOX", aid, "api_secret")),
            "redirect_uri": self._redirect_uri,
            "grant_type": "authorization_code",
        }
        response = self._client(account).request(
            "POST",
            "/v2/login/authorization/token",
            headers={
                "Accept": "application/json",
                "Api-Version": "2.0",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=form,
            # A code is single-use. Retrying the exchange after a timeout either
            # fails ("code already used") or, worse, looks like a second login.
            retry=False,
        )
        if not response.is_success:
            raise classify(response, context="token exchange")
        body = response.json(parse_float=Decimal)
        access_token = body.get("access_token")
        if not access_token:
            raise UnknownError("token exchange returned no access_token", broker="UPSTOX", raw=body)
        path = session_path(aid, today_ist())
        self._secrets.put(path, str(access_token))
        return Token(
            secret_ref=path,
            obtained_at=datetime.now(UTC),
            broker_client_id=str(body.get("user_id") or ""),
            flags={"poa": bool(body.get("poa", False)), "is_active": bool(body.get("is_active"))},
        )

    def fetch_profile(self, account: AccountRef) -> BrokerProfile:
        return m.profile(self._call(account, "GET", "/v2/user/profile", context="profile"))

    def probe_token(self, account: AccountRef) -> TokenProbeResult:
        try:
            prof = self.fetch_profile(account)
        except AuthError as exc:
            return TokenProbeResult(ok=False, probe_used=TokenProbe.PROFILE, detail=str(exc))
        return TokenProbeResult(
            ok=prof.is_active,
            probe_used=TokenProbe.PROFILE,
            detail=f"{prof.display_name} ({prof.broker_client_id})",
            flags={"broker_client_id": prof.broker_client_id, **prof.flags},
        )

    def revoke_token(self, account: AccountRef) -> None:
        try:
            self._call(account, "DELETE", "/v2/logout", context="logout")
        except AuthError:
            return  # already dead is the outcome we wanted

    # ---------------------------------------------------------- reference data
    def fetch_instruments(self) -> Iterable[CanonicalInstrument]:
        with httpx.Client(
            proxy=self._default_proxy, timeout=60.0, verify=True, transport=self._transport
        ) as client:
            suspended = frozenset(
                str(row["isin"])
                for row in self._gz_json(client, SUSPENDED_URL, required=False)
                if row.get("isin")
            )
            rows = self._gz_json(client, INSTRUMENTS_URL, required=True)
        out = []
        for row in rows:
            item = m.instrument(row, suspended=suspended)
            if item is not None:
                out.append(item)
        return out

    @staticmethod
    def _gz_json(client: httpx.Client, url: str, *, required: bool) -> list[dict[str, Any]]:
        response = client.get(url)
        if not response.is_success:
            if required:
                raise BrokerError(
                    f"instrument master: HTTP {response.status_code}", broker="UPSTOX"
                )
            return []
        payload = gzip.decompress(response.content)
        data = json.loads(payload, parse_float=Decimal)
        return data if isinstance(data, list) else []

    # ------------------------------------------------------------------- reads
    def fetch_holdings(self, account: AccountRef) -> list[CanonicalHolding]:
        rows = self._call(account, "GET", "/v2/portfolio/long-term-holdings", context="holdings")
        return [m.holding(row, self._resolve(m.instrument_from_holding(row))) for row in rows or []]

    def fetch_positions(self, account: AccountRef) -> list[CanonicalHolding]:
        rows = self._call(account, "GET", "/v2/portfolio/short-term-positions", context="positions")
        out = []
        for row in rows or []:
            if not row.get("instrument_token"):
                continue
            mapped = m.delivery_position(row, self._resolve(m.instrument_from_holding(row)))
            if mapped is not None:
                out.append(mapped)
        return out

    def fetch_funds(self, account: AccountRef) -> CanonicalFunds:
        data = self._call(
            account,
            "GET",
            "/v2/user/get-funds-and-margin",
            params={"segment": "SEC"},
            context="funds",
        )
        return m.funds(data or {}, as_of=datetime.now(UTC))

    def fetch_quotes(
        self, account: AccountRef, broker_tokens: Sequence[str]
    ) -> list[CanonicalQuote]:
        out: list[CanonicalQuote] = []
        tokens = list(dict.fromkeys(broker_tokens))
        for start in range(0, len(tokens), QUOTE_BATCH):
            batch = tokens[start : start + QUOTE_BATCH]
            data = self._call(
                account,
                "GET",
                "/v2/market-quote/quotes",
                params={"instrument_key": ",".join(batch)},
                context="quotes",
            )
            for row in (data or {}).values():
                token = str(row.get("instrument_token") or "")
                instrument_id = self._resolver.instrument_id_for(token)
                if instrument_id is None:
                    continue  # only instruments ATOM asked for, and so already knows
                out.append(m.quote(row, instrument_id))
        return out

    def fetch_daily_candles(
        self, account: AccountRef, broker_token: str, from_date: date, to_date: date
    ) -> list[CanonicalCandle]:
        key = urlquote(broker_token, safe="")
        path = f"/v3/historical-candle/{key}/days/1/{to_date.isoformat()}/{from_date.isoformat()}"
        data = self._call(account, "GET", path, context=f"historical {broker_token}")
        bars = m.candles((data or {}).get("candles") or [])
        return [bar for bar in bars if from_date <= bar.trade_date <= to_date]

    def fetch_orders(self, account: AccountRef) -> list[OrderState]:
        rows = self._call(account, "GET", "/v2/order/retrieve-all", context="order book")
        return [m.order_state(row) for row in rows or []]

    def fetch_fills(self, account: AccountRef, since: date) -> list[CanonicalFill]:
        """Today's trades only — Upstox's trade book has no date range. Settlement
        therefore runs on the day, and a missed day is recovered from holdings."""
        rows = self._call(account, "GET", "/v2/order/trades/get-trades-for-day", context="trades")
        return [m.fill(row) for row in rows or [] if row.get("trade_id")]

    def fetch_charges(
        self, account: AccountRef, broker_order_ids: Sequence[str]
    ) -> dict[str, CanonicalCharges]:
        """Upstox reports charges per PERIOD, never per order (UPSTOX-ADAPTER.md
        5.4). Returning an empty map is the honest answer to a per-order question;
        the UI shows computed charges with no broker counterpart and says so."""
        return {}

    def fetch_ledger(
        self, account: AccountRef, from_date: date, to_date: date
    ) -> list[CanonicalCashEvent]:
        raise UnsupportedOperationError("UPSTOX", "fetch_ledger")

    # ------------------------------------------------------------------ writes
    def place_order(self, account: AccountRef, intent: OrderIntent) -> OrderState:
        body = {
            "quantity": intent.quantity,
            "product": "D",
            "validity": "DAY",
            "price": str(intent.limit_price),
            "tag": truncate_for(intent.client_ref, UPSTOX.client_ref_max_len),
            "instrument_token": self._resolver.broker_token_for(intent.instrument_id),
            "order_type": "LIMIT",
            "transaction_type": "BUY" if intent.side is Side.BUY else "SELL",
            "disclosed_quantity": 0,
            "trigger_price": 0,
            "is_amo": False,
            # Pinned off: with slicing on, the response becomes a per-slice array.
            "slice": False,
        }
        data = self._call(
            account, "POST", "/v3/order/place", json_body=body, context="place order", is_order=True
        )
        ids = (data or {}).get("order_ids") or []
        if len(ids) != 1:
            raise UnknownError(
                f"place order returned {len(ids)} order ids, expected 1", broker="UPSTOX", raw=data
            )
        return OrderState(
            broker_order_id=str(ids[0]),
            status=OrderStatus.PLACED,
            raw_status="submitted",
            pending_quantity=intent.quantity,
            client_ref=intent.client_ref,
        )

    def cancel_order(self, account: AccountRef, broker_order_id: str) -> OrderState:
        self._call(
            account,
            "DELETE",
            "/v3/order/cancel",
            params={"order_id": broker_order_id},
            context="cancel order",
            is_order=True,
        )
        # Accepted is not cancelled. The caller re-reads the book to verify
        # (D-063), so the honest status here is still in flight.
        return OrderState(
            broker_order_id=broker_order_id,
            status=OrderStatus.IN_FLIGHT,
            raw_status="cancel requested",
        )

    def place_gtt(self, account: AccountRef, intent: GttIntent) -> GttState:
        if intent.side is not Side.SELL:
            raise ValidationError("ATOM places GTT sells only", broker="UPSTOX")
        body = {
            "type": "SINGLE",
            "quantity": intent.quantity,
            "product": "D",
            "instrument_token": self._resolver.broker_token_for(intent.instrument_id),
            "transaction_type": "SELL",
            "rules": [
                {
                    "strategy": "ENTRY",
                    "trigger_type": "ABOVE",
                    "trigger_price": str(intent.trigger_price),
                }
            ],
        }
        data = self._call(
            account,
            "POST",
            "/v3/order/gtt/place",
            json_body=body,
            context="place GTT",
            is_order=True,
        )
        ids = (data or {}).get("gtt_order_ids") or []
        if len(ids) != 1:
            raise UnknownError(
                f"place GTT returned {len(ids)} ids, expected 1", broker="UPSTOX", raw=data
            )
        return GttState(
            broker_gtt_id=str(ids[0]),
            status=GttStatus.ACTIVE,
            raw_status="placed",
            client_ref=intent.client_ref,
            instrument_id=intent.instrument_id,
            trigger_price=intent.trigger_price,
            quantity=intent.quantity,
            is_ours=True,
        )

    def cancel_gtt(self, account: AccountRef, broker_gtt_id: str) -> GttState:
        self._call(
            account,
            "DELETE",
            "/v3/order/gtt/cancel",
            json_body={"gtt_order_id": broker_gtt_id},
            context="cancel GTT",
            is_order=True,
        )
        return GttState(
            broker_gtt_id=broker_gtt_id, status=GttStatus.UNKNOWN, raw_status="cancel requested"
        )

    def fetch_gtts(self, account: AccountRef) -> list[GttState]:
        rows = self._call(account, "GET", "/v3/order/gtt", context="GTT book")
        out = []
        for row in rows or []:
            token = str(row.get("instrument_token") or "")
            out.append(m.gtt_state(row, self._resolver.instrument_id_for(token)))
        return out

    # ------------------------------------------------------------- optional
    def preview_charges(
        self, account: AccountRef, intents: Sequence[OrderIntent]
    ) -> dict[str, CanonicalCharges]:
        raise UnsupportedOperationError("UPSTOX", "preview_charges")

    def initiate_sell_authorisation(
        self, account: AccountRef, isins: Sequence[str]
    ) -> AuthorisationRequest:
        raise UnsupportedOperationError("UPSTOX", "initiate_sell_authorisation")
