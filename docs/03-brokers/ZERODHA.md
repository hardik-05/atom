# Zerodha — Broker Adapter Specification

**Status:** 🟢 Complete route table verified from SDK source
**Role in ATOM:** trading account — **orders only, no data subscription**
**Priority:** Phase C (D-140)
**Source:** `kiteconnect` 5.2.2 (PyPI), Kite Connect documentation

---

## 1. Why Zerodha is third, deliberately

The account exists but has **no data API subscription** (D-056a). That makes it the first real
exercise of the decoupling in D-017 — **data from Upstox, orders to Zerodha**. Better to prove
that path early than to discover a hidden coupling late, when four adapters already assume the
data and trading brokers are the same.

## 2. Auth
```
POST /session/token           request_token → access_token
POST /session/refresh_token
DELETE /session/token         invalidate
```
Daily access token. API key/secret from a Kite Connect developer app.

## 3. Complete route table (verified from SDK)

### Orders
| Purpose | Route |
|---|---|
| Place | `POST /orders/{variety}` |
| Cancel | `DELETE /orders/{variety}/{order_id}` |
| Modify | `PUT /orders/{variety}/{order_id}` *(unused — D-066)* |
| Order book | `GET /orders` |
| Order info | `GET /orders/{order_id}` |
| Trades for order | `GET /orders/{order_id}/trades` |
| Trade book | `GET /trades` |

`{variety}` distinguishes regular / amo / co / iceberg — ATOM uses `regular` only.

### GTT
| Purpose | Route |
|---|---|
| Place | `POST /gtt/triggers` |
| List | `GET /gtt/triggers` |
| Info | `GET /gtt/triggers/{trigger_id}` |
| Cancel | `DELETE /gtt/triggers/{trigger_id}` |
| Modify | `PUT /gtt/triggers/{trigger_id}` *(unused)* |

### Portfolio, funds, market data
| Purpose | Route |
|---|---|
| Holdings | `GET /portfolio/holdings` |
| Positions | `GET /portfolio/positions` |
| Funds | `GET /user/margins`, `/user/margins/{segment}` |
| Profile | `GET /user/profile` |
| Quote / OHLC / LTP | `GET /quote`, `/quote/ohlc`, `/quote/ltp` |
| Historical | `GET /instruments/historical/{instrument_token}/{interval}` |
| Instruments | `GET /instruments`, `/instruments/{exchange}` |

### 🟢 Charges — a dedicated endpoint
| Purpose | Route |
|---|---|
| **Contract note / charges for orders** | `GET /charges/orders` |
| Order margins | `GET /margins/orders` |
| Basket margins | `GET /margins/basket` |

> **`/charges/orders` is the most direct charge API found across the five brokers.** It returns
> the charge breakdown for given orders, which is exactly what the computed-vs-reported contrast
> (D-024) needs. Confirm whether DP charges are included or appear only in the ledger (Q-178).

## 4. Rate limits — ✅ verified
- **10 requests/second per API key**, enforced at key level.
- **5,000 orders/day**, **400 orders/minute**.

Comfortably above ATOM's 2 OPS cap (D-088).

> ⚠️ **Enforced per API key, not per account.** If one Kite app served several investors, they
> would share the 10/s budget. ATOM's volumes make this irrelevant, but the per-key nature
> matters if a single app is ever used across accounts — and it interacts with IP whitelisting,
> since the app, not the account, is the unit. (Q-231)

## 5. Proxy behaviour — ✅ the cleanest of the five
```python
self.proxies = proxies if proxies else {}
r = self.reqsession.request(method, url, ..., proxies=self.proxies)
```
Passed explicitly on every request, nothing bypasses it (D-139). ATOM still uses raw HTTP for
uniformity, but Zerodha's client is the reference implementation of what correct looks like.

## 6. Commercials
Reported at roughly **₹2,000/month** for Kite Connect, though sources disagree (Q-224). Since
Zerodha is **orders-only** here, confirm whether a cheaper order-only tier exists without the
historical-data add-on — ATOM needs no data from this broker.

## 7. Open items
| ID | Item |
|---|---|
| Q-231 | Rate limits are per API key — confirm whether one app across accounts is acceptable, and how it interacts with IP whitelisting |
| Q-232 | Is there an order-only subscription tier, without historical data? |
| Q-178c | Does `/charges/orders` include DP charges, or ledger only? |
| Q-185a | Is GTT cancellation synchronous, or must `/gtt/triggers` be re-polled? |

---

## 8. Round 2 — verified from vendor documentation (2026-09-24)

Full cross-broker detail in [`API-REFERENCE-VERIFIED.md`](API-REFERENCE-VERIFIED.md).

### 8.1 🔴 Token expires at 6 AM the next day — a hard regulatory boundary

[Source](https://kite.trade/docs/connect/v3/user/)

> "Unless this is invalidated using the API, or invalidated by a master-logout from the Kite Web
> trading terminal, it'll **expire at 6 AM on the next day (regulatory requirement)**."

This closes the `❓ UNVERIFIED` token-lifetime cell and adds a scheduling constraint ATOM did
not have: **a Zerodha token generated before 6 AM is dead before the market opens.** The
token-generation window and the run window must both sit after 6 AM IST.

`refresh_token` is returned in the session payload but is "only available to certain approved
platforms" — not available to ATOM. There is no refresh path; it is re-login every day.

`DELETE /session/token` explicitly invalidates the session. Zerodha is the **only** broker where
ATOM can actively destroy the token at end of run rather than merely forgetting it — the D-170
`CLEARED` step should call it.

### 8.2 Login flow — verified

1. `https://kite.zerodha.com/connect/login?v=3&api_key=xxx`
2. Redirect carries `request_token` (**lifetime: a few minutes**)
3. `POST /session/token` with `api_key`, `request_token`, and
   `checksum = SHA-256(api_key + request_token + api_secret)`
4. All later calls: `Authorization: token api_key:access_token`

An optional **`redirect_params`** may be appended to the login URL (URL-encoded query string)
and comes back at the redirect. ATOM should carry `trading_account_id` through it so the console
knows which account a returning token belongs to without keeping server-side state.

Prerequisite: the Zerodha account must have **2FA TOTP enabled**.

### 8.3 🔴 An active GTT carries no ATOM identifier

[Source](https://kite.trade/docs/connect/v3/gtt/)

An *active* trigger returns `"meta": {}` or `null`. The `app_id` appears only inside
`orders[].result.meta` **after** the trigger has fired. There is no `tag` field on a GTT at all.

**So on Zerodha, ATOM cannot identify its own GTTs from the broker's data.** The cancel-all-first
step (D-063) must work entirely from ATOM's own `trigger_id` mapping in the database, and a GTT
placed by the investor through Kite Web is indistinguishable from ATOM's until it fires.

This makes durable storage of every placed `trigger_id` **load-bearing on Zerodha specifically**:
if that mapping is lost, ATOM can neither cancel its own GTTs nor safely leave the investor's
alone. It is the strongest argument in the matrix for persisting broker order IDs before
returning from `place_gtt`, not after.

### 8.4 GTT — verified payload

`POST /gtt/triggers`

- `type`: `single` · `two-leg` (OCO)
- `condition`: `{exchange, tradingsymbol, trigger_values[], last_price}` — **`last_price` must
  be supplied at placement**, so ATOM needs a live quote in hand before placing
- `orders[]`: array whose **index** determines which order fires for which trigger value
- `order_type` inside a GTT: **`LIMIT` only**
- Status: `active` · `triggered` · `disabled` · `expired` · `cancelled` · `rejected` · `deleted`
- Retrieval returns active GTTs plus **the previous 7 days** of other states
- Modify is a `PUT`; the docs recommend fetching by ID and modifying the returned object,
  because a partial PUT will drop fields

### 8.5 Order tagging and status mapping

`tag` — **alphanumeric, max 20 characters** — is returned in the order book as both `tag` and
`tags[]`. `guid` is documented as a "request id to avoid order duplication". ATOM's `client_ref`
must be ≤ 20 characters so a single format works across all five brokers.

**Order statuses are not a closed enum.** Beyond `OPEN` / `COMPLETE` / `CANCELLED` / `REJECTED`
there are transient states — `PUT ORDER REQ RECEIVED`, `VALIDATION PENDING`, `OPEN PENDING`,
`MODIFY VALIDATION PENDING`, `TRIGGER PENDING`, `CANCEL PENDING`, `AMO REQ RECEIVED` — and the
docs warn "there may be other values as well".

> **The adapter's status mapping must have a default branch that treats an unknown status as
> in-flight, never as terminal.** Mapping an unrecognised status to "failed" would make ATOM
> re-place an order that is about to fill.

Rejections return `status_message` and `status_message_raw`, e.g. *"Insufficient funds. Required
margin is 95417.84 but available margin is 74251.80."* D-052 ("let the order fail if money is not
present") is satisfied with a human-readable reason to log.

### 8.6 New parameters since the route table was captured

`market_protection` (custom % up to 100, or `-1` for automatic) and `autoslice` now appear on the
regular order payload. ATOM uses neither — it places plain limit orders — but the adapter must
not reject them as unknown if they appear in a response. `autoslice=true` changes the response
shape to an **array** of per-slice results mixing `order_id` and `error` objects; ATOM never
sets it, so the adapter may treat an array response as a fault.

### 8.7 New open items

| ID | Item |
|---|---|
| Q-268 | Does ATOM need an empanelled Algo ID at 2 OPS on Zerodha? |
| Q-273 | Does Zerodha expose per-trade charges via API, or console reports only? |
| Q-274 | Zerodha static-IP whitelisting procedure — not found in the developer docs |
