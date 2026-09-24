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

---

## 8. Round 2 — verified from vendor documentation (2026-09-24)

Full cross-broker detail in [`API-REFERENCE-VERIFIED.md`](API-REFERENCE-VERIFIED.md).

### 8.1 🔴 The static IP, once set, is locked for 7 days

[Source](https://dhanhq.co/docs/v2/authentication/)

`POST /v2/ip/setIP` · `PUT /v2/ip/modifyIP` · `GET /v2/ip/getIP`, with
`{dhanClientId, ip, ipFlag: PRIMARY|SECONDARY}`. IPv4 and IPv6 both accepted.

Three constraints that change ATOM's infrastructure design rather than merely informing it:

1. **"Once an IP is whitelisted, it cannot be edited for the next 7 days."** `GET /v2/ip/getIP`
   returns `modifyDatePrimary` / `modifyDateSecondary` — the earliest date each may change. An
   instance rebuild that picks up a fresh address is therefore **a week-long outage on Dhan**,
   not a restartable error. The Elastic IP is mandatory, and it must be allocated *before* the
   address is registered with Dhan.
2. **"Each individual needs to have a unique static IP."** This is the vendor stating, in its own
   words, the requirement D-010 derived from first principles: one address per investor, never
   shared.
3. **Whitelisting gates writes only.** "Static IP is only required while using Order Placement
   APIs including Orders, Super Order, Forever Order. While fetching order details or trade
   details, no such IP whitelisting is required."

Consequence (3) is subtle and matters. The D-170 token probe reads **holdings** — which on Dhan
works from *any* address. A token can therefore probe green and the first order still fail on
IP. **The pre-flight must verify egress IP as a separate gate from token validity**, not fold
one into the other. `verify_egress_ip.py` runs on every run, not only at onboarding.

### 8.2 Auth — TOTP makes this fully headless

`POST https://auth.dhan.co/app/generateAccessToken?dhanClientId=&pin=&totp=` returns
`accessToken` plus an explicit `expiryTime`, **24-hour validity**, no browser involved. This is
the best automation story of the five brokers.

`GET /v2/RenewToken` expires the current token and issues a fresh 24-hour one — works only for
tokens generated from Dhan Web, and only while the current token is still active.

The alternative **API key + secret** path (keys valid **12 months**) is a three-step consent
flow: `generate-consent` → browser `consentApp-login` (302 with `tokenId`) → `consumeApp-consent`.
Capped at **25 `consentAppId` per day**, one live token at a time.

Both flows return **`givenPowerOfAttorney`** (DDPI status) — capture it at onboarding, since it
determines whether sells need per-trade authorisation.

### 8.3 `GET /v2/profile` is a better token probe than holdings

Returns `tokenValidity`, `activeSegment`, `ddpi`, `mtf`, `dataPlan`, `dataValidity`.

D-170 specifies probing holdings to test a token. On Dhan, `/v2/profile` is cheaper, is
explicitly documented as "a great test API", and — unlike a holdings call — tells ATOM **why**
an account is unusable (DDPI inactive, data plan expired) rather than only that it is. The
adapter should prefer it, with holdings as the generic fallback for brokers without an
equivalent.

### 8.4 Forever Order (GTT) — verified payload

`POST /v2/forever/orders` · `PUT /v2/forever/orders/{id}` · `DELETE /v2/forever/orders/{id}` ·
`GET /v2/forever/orders` (and `/v2/forever/all`).

- `orderFlag`: `SINGLE` or `OCO`
- `productType` for Forever Orders: **`CNC` or `MTF` only**
- `orderType`: `LIMIT` or `MARKET`; `validity`: `DAY` or `IOC`
- OCO second leg: `price1`, `triggerPrice1`, `quantity1`
- Modify requires `legName`: `TARGET_LEG` (single, or first OCO leg) or `STOP_LOSS_LEG`
- Status: `TRANSIT` · `PENDING` · `REJECTED` · `CANCELLED` · `TRADED` · `EXPIRED` · `CONFIRM`
- **Requires the whitelisted static IP**

**`correlationId` — up to 30 characters, user-supplied, "for tracking back".** This is how ATOM
identifies its own Forever Orders on Dhan and satisfies D-064's "cancel only ATOM's GTTs".

### 8.5 🟢 Per-trade charges are available from the API

[Source](https://dhanhq.co/docs/v2/statements/) — `GET /v2/trades/{from-date}/{to-date}/{page}`

Each trade carries `sebiTax`, `stt`, `brokerageCharges`, `serviceTax`,
`exchangeTransactionCharges`, `stampDuty` — plus `isin`, `exchangeTradeId`, `exchangeOrderId`.

**This gives the charges-contrast view (D-024, D-105) a ground truth on Dhan rather than a
model.** Estimated-vs-actual can be shown per fill *and per component*. Where other brokers do
not expose this, the view degrades to estimate-only, and that degradation must be visible in the
UI rather than silent.

### 8.6 Ledger

`GET /v2/ledger?from-date=&to-date=` → `narration`, `voucherdate`, `exchange`, `voucherdesc`,
`vouchernumber`, `debit`, `credit`, **`runbal`**.

`runbal` is the reconciliation anchor for the cost-of-capital model — ATOM's computed
`principal_outstanding` can be checked against the broker's own running balance, not only
against its internal ledger. A withdrawal appears as `narration = "FUNDS WITHDRAWAL"` with
`voucherdesc = "PAYBNK"`, which is what D-078 models as a repayment to the firm. The classifier
needs a `voucherdesc` → ATOM event mapping table (**Q-276**).

### 8.7 New open items

| ID | Item |
|---|---|
| Q-268 | Does ATOM need an empanelled Algo ID at 2 OPS on Dhan? |
| Q-276 | Build the `voucherdesc` → ATOM cash-event mapping from a real ledger pull |
