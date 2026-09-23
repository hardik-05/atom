# Dhan — Broker Adapter Specification

**Status:** 🟢 Endpoints verified from SDK source
**Role in ATOM:** trading account (Person A, Person B)
**Priority:** Phase B (D-140)
**Source:** `dhanhq` 2.2.0 (PyPI), DhanHQ v2 documentation

---

## 1. Auth
- Access token generated from the account, **valid 24 hours**, explicitly aligned to exchange
  and SEBI guidance on API access management.
- ⚠️ **The SDK's auth flow bypasses its own session** — five module-level `requests` calls in
  `auth.py` (D-135). ATOM implements auth over `HttpCore`, so this does not apply, but it is the
  reason the SDK is unusable here.

## 2. 🟢 IP whitelisting is an API, not a form

```
GET  /ip/getIP
POST /ip/setIP
POST /ip/modifyIP
```

**Dhan is the only broker examined that exposes static-IP registration programmatically.**
D-007 assumes IP registration is manual per broker. For Dhan it need not be — and more usefully,
`getIP` allows ATOM to **verify** the registered IP matches the investor's Elastic IP at startup,
catching a misconfiguration before an order is rejected.

*Recommendation: read via `getIP` as a health check; keep `setIP` manual and operator-initiated.
Automatically changing a whitelisted IP is exactly the kind of irreversible, outward-facing action
that should stay in human hands.* (Q-229)

## 3. Endpoints (verified from SDK)

| Purpose | Endpoint |
|---|---|
| Place / modify / cancel order | `/orders`, `/orders/{order_id}` |
| Order by correlation id | `/orders/external/{correlation_id}` |
| **Forever Order (GTT)** | `/forever/orders`, `/forever/orders/{order_id}` |
| Super orders | `/super/orders`, `/super/orders/{order_id}/{order_leg}` |
| Holdings | `/holdings` |
| Positions | `/positions`, `/positions/convert` |
| Funds | `/fundlimit` |
| **Ledger** | `/ledger?from-date={from}&to-date={to}` |
| Trade book | `/trades/{order_id}` |
| **Trade history (paged)** | `/trades/{from_date}/{to_date}/{page_number}` |
| Historical candles | `/charts/historical`, `/charts/intraday` |
| Market quote | `/marketfeed/ltp`, `/ohlc`, `/quote` |
| Margin calculator | `/margincalculator` |
| Kill switch | `/killswitch` |
| eDIS | `/edis/tpin`, `/edis/form`, `/edis/inquire/{isin}` |
| IP management | `/ip/getIP`, `/ip/setIP`, `/ip/modifyIP` |

> 🟢 **`/ledger` with a date range** — Dhan exposes the ledger directly, which is where DP
> charges typically surface (Q-178). Combined with paged trade history, this is what the charges
> model (D-024) and `funds_credited_date` (D-050) need. **Confirm whether ledger entries are
> attributable to a specific trade or only dated** — that decides whether FIFO matching of
> credits is required (Q-175).

## 4. Rate limits — ✅ verified
| Surface | Limit |
|---|---|
| Non-trading | 20/s |
| **Orders** | 10/s |
| Data | 5/s |
| **Quote** | **1/s** |
| Daily | 5,000 orders · 25/s · 250/min |

> ⚠️ **Quote at 1 request/second is the sharpest constraint found across all five brokers.**
> Pricing a 60-ETF universe serially would take a full minute per account. **Dhan must never be
> the market-data source** — reinforcing D-017 and D-058i.

## 5. Order behaviour
**MARKET orders are converted to LIMIT with market price protection.** ATOM places limit orders
priced from a fresh LTP anyway (D-056c), so this aligns — but it means Dhan's fill behaviour will
differ subtly from brokers that accept true market orders, and the paper fill model should not
assume otherwise.

## 6. Proxy behaviour
⚠️ Trading calls use a per-instance `requests.Session` (proxy settable post-construction), but
**six calls in `auth.py` and `_security.py` bypass it** (D-135). ATOM uses raw HTTP.

## 7. Open items
| ID | Item |
|---|---|
| Q-229 | Use `/ip/getIP` as a startup health check; keep `setIP` manual? |
| Q-175a | Are `/ledger` entries attributable to a specific trade, or only dated? |
| Q-178b | Confirm DP charges appear in `/ledger` and their latency |
| Q-230 | Forever Order semantics: max validity, behaviour when the underlying holding is sold elsewhere, synchronous cancellation (Q-185) |
