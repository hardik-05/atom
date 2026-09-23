# Upstox — Broker Adapter Specification

**Status:** 🟢 Endpoints verified from SDK source · auth verified from vendor docs
**Role in ATOM:** **primary market-data source** (D-058i) **and** a trading account
**Priority:** Phase A — first broker built (D-140)
**Source:** `upstox-python-sdk` 2.30.0 (PyPI), Upstox Developer API docs

---

## 1. Why Upstox is first

Its read-only surface alone unblocks the universe job, ranking engine, NAV gate and the whole
paper-trading path — before any other broker exists, before the static IPs are registered and
before any money is at risk (D-140).

## 2. Auth

OAuth 2.0 authorization-code flow:

```
/v2/login/authorization/dialog   → user logs in, returns single-use code
/v2/login/authorization/token    → exchange code for access_token
/v2/logout
```

- **Access token: regenerated daily.** A separate long-lived *analytics* token exists that needs
  no daily re-auth — worth investigating for the data path, since it would remove the daily
  ritual for market data while leaving trading tokens short-lived. (Q-226)
- API key and secret come from a developer app at `account.upstox.com/developer/apps`.
- A redirect URI is registered with the app — served by the always-on Render site (D-018).

## 3. 🟢 `/v2/user/ip` — the static-IP self-test

Upstox exposes an endpoint that **returns the IP address the request arrived from**.

This is the cleanest possible verification of the hardest part of the infrastructure (D-005):
after wiring the per-account proxy, call it through each account's proxy and assert the returned
address equals that investor's Elastic IP. **This becomes a startup health check and a test**,
turning "did the proxy work?" from an assumption into an assertion.

*No other broker examined offers this. It is a strong argument for building Upstox first
regardless of the data-source role.*

## 4. Endpoints (verified from SDK)

### Orders — v3 preferred
| Purpose | Endpoint |
|---|---|
| Place | `POST /v3/order/place` |
| Modify | `POST /v3/order/modify` *(unused — D-066)* |
| Cancel | `DELETE /v3/order/cancel` |
| Details / history | `/v2/order/details`, `/v2/order/history` |
| Order book | `/v2/order/retrieve-all` |
| Trades | `/v2/order/trades`, `/v2/order/trades/get-trades-for-day` |
| Multi-order | `/v2/order/multi/place`, `/v2/order/multi/cancel` |

### GTT — v3
| Purpose | Endpoint |
|---|---|
| Place | `POST /v3/order/gtt/place` |
| Modify | `POST /v3/order/gtt/modify` *(unused)* |
| Cancel | `DELETE /v3/order/gtt/cancel` |
| Retrieve | `GET /v3/order/gtt` |

Active until expiry; intraday GTTs valid only for the day. `X-Algo-Name` header is optional,
required only for exchange-approved algo strategies — see the SEBI compliance note (§8).

### Portfolio, funds, market data, charges
| Purpose | Endpoint |
|---|---|
| Holdings | `GET /v2/portfolio/long-term-holdings` |
| Positions | `GET /v2/portfolio/short-term-positions` |
| Funds | `GET /v3/user/get-funds-and-margin` |
| LTP / OHLC / full quote | `/v2/market-quote/ltp`, `/ohlc`, `/quotes` |
| Historical candles | `/v2/historical-candle/{instrumentKey}/{interval}/{to_date}/{from_date}` |
| Intraday candles | `/v2/historical-candle/intraday/{instrumentKey}/{interval}` |
| **Brokerage estimate** | `GET /v2/charges/brokerage` |
| **Historical trade charges** | `GET /v2/charges/historical-trades` |
| **P&L data / charges / metadata** | `/v2/trade/profit-loss/data`, `/charges`, `/metadata` |
| Market holidays | `/v2/market/holidays` |
| Kill switch | `/v2/user/kill-switch` |

> 🟢 **Upstox exposes charges directly** — `/v2/charges/brokerage` for a pre-trade estimate and
> `/v2/trade/profit-loss/charges` for realised charges. This is the best charge visibility of the
> five and partially answers Q-178 for this broker. Whether DP charges appear there or only in a
> ledger still needs confirmation against a real contract note.

### Instrument master
`https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz` — unauthenticated CDN
file carrying ISIN, trading symbol, name, instrument_key. Already used by
`scripts/fetch_etf_reference_data.py`.

## 5. Identifiers
Instruments are keyed as `NSE_EQ|<ISIN>` (e.g. `NSE_EQ|INE002A01018`) — **ISIN-based, not
symbol-based**, which suits ATOM well since the ETF master is ISIN-keyed (D-114).

## 6. Proxy behaviour
✅ `configuration.proxy` → `urllib3.ProxyManager` per Configuration instance. ATOM uses raw HTTP
regardless (D-135), but Upstox is one of only two SDKs that could have complied.

## 7. Rate limits
❓ **UNVERIFIED** — not stated in the SDK. Confirm on the developer site and enter in the
capability matrix. ATOM's own cap is 2 OPS (D-088), far below any plausible broker limit.

## 8. Compliance
`X-Algo-Name` is required only for exchange-approved algo strategies. ATOM operates below the
10 OPS TOPS threshold and is exempt from algo registration (D-088), so the header is not
expected to apply — but its presence confirms Upstox implements the SEBI framework, and the
adapter should carry the field unused (D-089).

## 9. Open items
| ID | Item |
|---|---|
| Q-226 | Can the long-lived analytics token serve the market-data path, removing the daily ritual for data? |
| Q-227 | Confirm `/v2/user/ip` returns the egress IP and can be used as the static-IP health check |
| Q-228 | Rate limits |
| Q-178a | Do DP charges appear in `/v2/trade/profit-loss/charges`, or only in a ledger? |
