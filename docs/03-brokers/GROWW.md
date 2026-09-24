# Groww — Broker Adapter Specification

**Status:** 🟠 Partially verified — SDK inspected, endpoints not fully exposed in source
**Role in ATOM:** trading account
**Priority:** Phase D (D-140)
**Source:** `growwapi` 1.5.0 (PyPI), Groww Trade API documentation

---

## 1. Auth
- Access token generated in the app: **Profile → Settings → Trading APIs → Generate API Keys →
  Access Token**.
- **Daily expiry.**
- Passed as `Authorization: Bearer {ACCESS_TOKEN}`.
- Order endpoint documented as `POST https://api.groww.in/v1/order/create`.

This is the **paste-in** token model rather than an OAuth redirect (D-012) — simplest of the five
to implement, but it requires a manual step in the app each day with no scope for a hosted flow.

## 2. SDK method surface (verified)

```
place_order · get_order_detail · get_order_list · get_order_status
get_order_status_by_reference · get_trade_list_for_order
get_holdings_for_user · get_position_for_trading_symbol · get_positions_for_user
get_available_margin_details
get_quote · get_ltp · get_ohlc · get_greeks · get_option_chain
get_all_instruments · get_instrument_by_exchange_and_trading_symbol
get_instrument_by_groww_symbol · get_instrument_by_exchange_token
```

## 3. GTT — constants present, methods absent

The SDK defines Smart Order constants:

```python
SMART_ORDER_TYPE_GTT = "GTT"
SMART_ORDER_TYPE_OCO = "OCO"
SMART_ORDER_STATUS_ACTIVE / TRIGGERED / CANCELLED / EXPIRED / FAILED / COMPLETED
```

…but **no `place_smart_order` / GTT method appears in the SDK's method list.** Documentation
describes GTT as available with up to **1 year validity** (COMMODITY unsupported).

> ⚠️ **Same shape as Shoonya: the capability exists in the API but not in the Python client.**
> Since ATOM uses raw HTTP (D-135) this is not a blocker, but the exact GTT endpoint and payload
> must come from Groww's REST documentation, not the SDK. **This is the largest unknown for this
> adapter** and should be resolved before Phase D starts. (Q-233)

## 4. ⚠️ No ledger or charges endpoint found
Nothing in the SDK exposes a ledger, contract note or charge breakdown. If Groww has no charges
API, the computed-vs-reported contrast (D-024) degrades to computed-only for this broker, and
DP-charge attribution (Q-178) would rely on manual statement upload (D-072c fallback). (Q-234)

## 5. Instrument master
`https://growwapi-assets.groww.in/instruments/instrument.csv` — unauthenticated CDN file.

## 6. Proxy behaviour — ❌ cannot comply
**Zero sessions; 5 module-level `requests` calls** (D-139). No per-instance object exists to
attach a proxy to. Raw HTTP is mandatory here, not optional.

## 7. Rate limits — ✅ verified 2026-09-24

[Source](https://groww.in/trade-api/docs/curl)

| Type | /sec | /min |
|---|---|---|
| Authentication (generate access token) | 5 | 30 |
| Orders (create, modify, cancel) | 10 | 250 |
| Live Data (quote, LTP, OHLC) | 10 | 300 |
| Non Trading (order status, lists, trades, positions, holdings, margin) | 20 | 500 |

Plus a hard cap of **150 requests per 24 hours** on `/v1/token/api/access`.

**Limits apply per *type*, not per endpoint** — exhausting one endpoint throttles every endpoint
in its group. ATOM's volume is far below all of these.

## 8. Open items
| ID | Item |
|---|---|
| Q-233 | 🔴 Exact GTT/Smart Order endpoint and payload from Groww's REST docs — the main unknown |
| Q-234 | Does Groww expose a ledger or charges API at all? |
| Q-235 | Rate limits |
| Q-236 | Does Groww support IP whitelisting, and by what procedure? |

---

## 9. Round 2 — verified from vendor documentation (2026-09-24)

Full cross-broker detail in [`API-REFERENCE-VERIFIED.md`](API-REFERENCE-VERIFIED.md).

### 9.1 GTT is fully documented — §3's "constants present, methods absent" is resolved

[Source](https://groww.in/trade-api/docs/curl/smart-orders) — Groww calls them **Smart Orders**,
`POST /v1/order-advance/create`, with `smart_order_type` of `GTT` or `OCO`.

```json
{
  "reference_id": "sref-unique-123",
  "smart_order_type": "GTT",
  "segment": "CASH",
  "trading_symbol": "TCS",
  "quantity": 10,
  "trigger_price": "3985.00",
  "trigger_direction": "DOWN",
  "order": { "order_type": "LIMIT", "price": "3990.00", "transaction_type": "BUY" },
  "product_type": "CNC",
  "exchange": "NSE",
  "duration": "DAY"
}
```

- **`trigger_direction`: `UP` / `DOWN`** — an explicit direction field no other broker has. ATOM
  sets `UP` for sell triggers above the average, which removes the ambiguity other brokers leave
  to inference from trigger price versus LTP.
- **Prices are decimal strings, not JSON numbers.**
- **"GTT orders placed via API automatically default to a one-year validity period."**
- `CASH` and `FNO` only — `COMMODITY` unsupported, which is harmless: ATOM's commodity ETFs are
  NSE CASH instruments.
- Modify (`PUT /v1/order-advance/modify/{id}`) allows quantity, trigger price, trigger direction,
  order type and limit price. **Duration and product type are not modifiable** — those need
  cancel + create. ATOM cancels and re-places anyway (D-063), so this costs nothing.
- Cancel: `POST /v1/order-advance/cancel/{segment}/{smart_order_type}/{smart_order_id}`
- List: `GET /v1/order-advance/list` filtered by `segment`, `smart_order_type`, `status`
  (`ACTIVE` / `CANCELLED` / `COMPLETED`) and a time window of **at most one month**
- Responses carry **`is_cancellation_allowed`** and **`is_modification_allowed`** — ATOM should
  read these before attempting either, rather than attempting and handling the failure.

### 9.2 🟢 `order_reference_id` is a required, native idempotency key

On `POST /v1/order/create` it is **required**: 8–20 alphanumeric characters, at most two hyphens.
A reused value returns **`GA007 Duplicate order reference id`**. And
`GET /v1/order/status/reference/{order_reference_id}` looks an order up by **ATOM's own
identifier**.

This is the best order-safety story of the five brokers. A network timeout during placement is
fully recoverable: ATOM retries with the same reference and either places the order or learns it
already exists — no race, no duplicate. Smart Orders use the same mechanism under the name
`reference_id`.

**The canonical adapter model should generalise this** as a single ATOM-generated `client_ref`,
mapped per broker (`tag` on Zerodha and Upstox, `correlationId` on Dhan, `remarks` on Shoonya),
truncated to 20 characters so one format satisfies every broker's constraint.

### 9.3 Three auth methods — two headless, but a daily click remains

[Source](https://groww.in/trade-api/docs/curl)

| Approach | Mechanism | Catch |
|---|---|---|
| **1. Access token** | Profile → Settings → Trading APIs | **Expires daily at 6:00 AM** |
| **2. API key + secret** | `POST /v1/token/api/access`, `key_type: "approval"`, `checksum = SHA-256(secret + epoch_seconds)`, timestamp valid 10 minutes | **Requires daily approval** on the Groww Cloud API Keys page |
| **3. API key + TOTP** | Same endpoint, `key_type: "totp"` | **Requires daily approval** on the same page |

So Groww is *not* fully automatable: the operator action moves from "copy a token" to "click
approve", which is still a daily touch. Note the same **6 AM** boundary as Zerodha.

Groww also requires an **active paid Trading API subscription** — the only broker of the five
that charges for order APIs at all.

### 9.4 Holdings expose the lock/pledge breakdown — and this affects attribution

[Source](https://groww.in/trade-api/docs/curl/portfolio) — `GET /v1/holdings/user` returns
`quantity`, `average_price`, `pledge_quantity`, `demat_locked_quantity`, `groww_locked_quantity`,
`repledge_quantity`, **`t1_quantity`**, **`demat_free_quantity`**,
`corporate_action_additional_quantity`, `active_demat_transfer_quantity`.

`HOLDINGS-ATTRIBUTION.md` asserts

```
broker_quantity = Σ open ATOM lots + excluded_quantity + unattributed_quantity
```

but does not say **which** quantity that is. A T1 quantity is owned and not yet deliverable; a
pledged quantity cannot be sold at all. Selling against either produces a rejection ATOM would
have to explain after the fact rather than prevent. **The sellable figure is
`demat_free_quantity`, not `quantity`** — and the attribution document must say so. Raised as
**Q-272**.

### 9.5 Error codes

| Code | Meaning |
|---|---|
| `GA000` | Internal error |
| `GA001` | Bad request |
| `GA003` | Unable to serve request currently |
| `GA004` | Requested entity does not exist |
| `GA005` | User not authorised for this operation |
| `GA006` | Cannot process this request |
| `GA007` | **Duplicate order reference id** — the idempotency signal, not a failure |

`GA007` must be handled as *success, already placed* — not as an error — or ATOM's retry logic
will report a false failure on a perfectly good order.

### 9.6 Open items updated

| ID | Item |
|---|---|
| Q-268 | Does ATOM need an empanelled Algo ID at 2 OPS on Groww? |
| Q-272 | Pin `broker_quantity` in the attribution identity to `demat_free_quantity` |
| Q-273 | Does Groww expose per-trade charges? None found in orders, trades or portfolio docs |
| Q-274 | Groww static-IP whitelisting procedure — not found in the developer docs |
| Q-275 | Groww Trading API subscription cost per account |
