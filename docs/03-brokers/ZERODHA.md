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
