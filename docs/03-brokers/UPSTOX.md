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

## 7. Rate limits — ✅ verified 2026-09-24

[Source](https://upstox.com/developer/api-documentation/rate-limiting/) — explicitly aligned to
NSE circular of 5 May 2025.

| Category | /sec | /min | /30 min |
|---|---|---|---|
| Order placement (place, modify, cancel, multi, **GTT**) — regular algos | 10 | 500 | 2,000 |
| Order placement — **SEBI-registered** algos | 50 | 500 | 2,000 |
| Standard APIs (holdings, positions, funds, candles) | 50 | 500 | 2,000 |
| TOTP login | 1 | 10 | 60 |

ATOM's 2 OPS ceiling (D-149) sits an order of magnitude below the unregistered limit, so no
registration is needed **on Upstox's reading of the rules** — see §8.

### Superseded note
The previous text here said "❓ UNVERIFIED — confirm on the developer site and enter in the
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

---

## 10. Round 2 — verified from vendor documentation (2026-09-24)

Full cross-broker detail in [`API-REFERENCE-VERIFIED.md`](API-REFERENCE-VERIFIED.md).

### 10.1 Three token-generation methods, one of which fits ATOM unusually well

[Source](https://upstox.com/developer/api-documentation/authentication/)

| Method | Shape |
|---|---|
| **Authorization code** | `GET /v2/login/authorization/dialog` → single-use `code` at the redirect URI → `POST /v2/login/authorization/token` with `code`, `client_id`, `client_secret`, `redirect_uri`, `grant_type=authorization_code` |
| **Semi-automated** | The app triggers an auth request at a set time; the operator approves from a **mobile notification** or the developer dashboard; **the token is then delivered to a notifier URL** registered at app creation |
| **Manual** | Copy from the Upstox Developer Apps dashboard |

The **semi-automated / notifier-URL** method is the closest any of the five brokers comes to the
"generate token" pattern the brief asked for: the operator taps approve on their phone and the
token arrives at ATOM without anyone opening a browser. It is the recommended primary path for
Upstox, with paste-in as the fallback.

Two documented gotchas for the redirect URI: **URLs ending in `.php` may be blocked**, and the
redirect should not sit at the very end of the URL. TOTP is available for 2FA.

### 10.2 GTT — verified payload

`POST https://api.upstox.com/v3/order/gtt/place`

- `type`: `SINGLE` (exactly one rule) · `MULTIPLE` (**2–3 rules, no duplicate strategies**)
- `rules[].strategy`: `ENTRY` (mandatory) · `TARGET` · `STOPLOSS`
- `rules[].trigger_type`: ENTRY may be `ABOVE` / `BELOW` / `IMMEDIATE`; TARGET and STOPLOSS
  **only** `IMMEDIATE`
- `product`: `I` · **`D`** (delivery — ATOM's) · `MTF`
- Returns `data.gtt_order_ids[]` — an **array**, even for a single-leg order
- **Valid up to one year** from creation
- **"A GTT order is always placed as a LIMIT order upon execution."**

### 10.3 🔴 EDIS authorization is required for any GTT with a SELL leg

> "To place GTT orders with a SELL leg, **EDIS authorization is required**. You can authorize
> EDIS from any of our platforms — Web, iOS, or Android — by placing a GTT order. Once
> authorized on any one platform, it will also be valid for API-based orders. You don't need to
> complete the order; simply going through the authorization flow is sufficient."

ATOM's entire sell side is GTT sells (D-063). **Without EDIS, every sell GTT on Upstox fails.**
This is a one-time manual step per account and belongs in the onboarding checklist as a hard
gate, before the first dry run is promoted to live. Raised as **Q-270**.

### 10.4 Error codes worth mapping explicitly

| Code | Meaning | ATOM handling |
|---|---|---|
| `UDAPI1154` | Access blocked due to **static IP restrictions** | Fail the run, alert — this is an infrastructure fault, never retry |
| `UDAPI1158` | **Market orders are not allowed.** Try placing a limit order | Should be unreachable; ATOM places limits only. If seen, it is a bug |
| `UDAPI1156` | Invalid Algo name in `X-Algo-Name` | Configuration fault, fail loudly |
| `UDAPI1176` / `UDAPI1177` | Market protection > 25% / invalid | Configuration fault |
| `UDAPI1136` / `UDAPI1137` | Rule-count violation for SINGLE / MULTIPLE | Bug in the GTT builder |

### 10.5 Regulatory changes live since 1 April 2026

[Source](https://community.upstox.com/t/important-update-regulatory-changes-for-api-and-algo-trading-are-now-live/14874)

- **Registered static IP is mandatory** — validates D-009…D-011 outright
- **Market orders no longer permitted**; Market Price Protection on by default
- **Algo registration required only above 10 OPS** — note this is a *weaker* reading than
  Shoonya's (see `API-REFERENCE-VERIFIED.md` §0.3 and **Q-268**)
- **MCX API trading temporarily disabled** — no impact; ATOM's commodity ETFs are NSE CASH

### 10.6 New open items

| ID | Item |
|---|---|
| Q-268 | Does ATOM need an empanelled Algo ID at 2 OPS? Upstox says no, Shoonya says yes |
| Q-270 | 🔴 EDIS authorization per Upstox account — blocking for the sell side |
