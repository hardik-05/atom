# Upstox API v3/v2 — Adapter Specification

**Status:** 🟢 Complete — traced to Upstox developer pages read 2026-09-24 / 2026-09-26
**Order of work:** 3rd of 5 (see [`../ADAPTER-ENGINE.md`](../ADAPTER-ENGINE.md) §9)
**Pages read:** authentication · place order v3 · place GTT · rate limiting · get holdings ·
instruments · trade charges · error codes · regulatory announcement

> **Why Upstox third.** It is the only broker that identifies instruments by **ISIN directly** —
> `instrument_key` is literally `NSE_EQ|INE669E01016` — which makes resolution trivial. Its
> awkwardness is elsewhere: a one-time EDIS gate on the entire sell side, and charges that come
> as a **period total with components** rather than per order.

---

## 1. Capability profile

```python
UPSTOX = BrokerCapabilities(
    broker_code               = "UPSTOX",

    supports_gtt              = True,
    gtt_max_validity_days     = 365,
    gtt_carries_client_ref    = False,         # no tag field on GTT payload (Q-297)
    gtt_order_type            = "LIMIT",       # "always placed as a LIMIT order upon execution"

    client_ref_field          = "tag",         # regular orders only
    client_ref_max_len        = 20,            # canonical ceiling; Upstox limit unstated
    client_ref_is_idempotent  = False,
    lookup_by_client_ref      = False,

    provides_trade_charges    = False,         # period totals, not per order — see §5.4
    provides_charge_preview   = False,
    provides_ledger           = False,
    provides_free_quantity    = True,          # derived, §6.1

    requires_static_ip        = True,          # 🔴 enforced — UDAPI1154
    static_ip_scope           = "ALL_CALLS",
    static_ip_lock_days       = 0,

    token_probe_endpoint      = "PROFILE",     # GET /v2/user/profile
    token_revocable           = True,          # POST /v2/logout

    requires_sell_authorisation = True,        # 🔴 EDIS
    sell_authorisation_scope    = "ONE_TIME",  # contrast Zerodha's PER_SESSION

    orders_per_second         = 10,
    quote_batch_size          = 500,
)
```

---

## 2. Wire basics

| | |
|---|---|
| Base URL | `https://api.upstox.com` — **v3 for orders and GTT, v2 for portfolio/charges** |
| Auth | `Authorization: Bearer {access_token}` |
| Headers | `Accept: application/json` · `Content-Type: application/json` |
| Encoding | JSON |
| Success | `{"status": "success", "data": {…}, "metadata": {"latency": 88}}` |
| Failure | `{"status": "error", "errors": [{"errorCode","message",…}]}` |
| Optional | `X-Algo-Name` header — **not sent** (D-181) |

⚠️ **Version is split across the API.** Orders and GTT are `/v3`; holdings, charges and profile
are `/v2`. The adapter carries a per-endpoint version rather than one base path, and the
round-trip tests assert the version on each route — a `/v3/portfolio/...` call 404s.

---

## 3. Session lifecycle — authorize-and-paste (D-183)

The operator's chosen flow, which is how they ran Upstox on the earlier system:

```
[Authorize] on ATOM's token screen
  → browser opens  https://api.upstox.com/v2/login/authorization/dialog
                     ?client_id=…&redirect_uri=…&response_type=code
  → operator enters credentials + 2FA (TOTP available)
  → Upstox returns a single-use `code`
  → operator copies it into ATOM's screen
  → ATOM POSTs /v2/login/authorization/token with
       code, client_id, client_secret, redirect_uri, grant_type=authorization_code
  → access_token
```

**This needs no registered redirect handler and no public callback**, which sidesteps both
documented pitfalls: redirect URLs ending in `.php` may be blocked, and the redirect should not
sit at the very end of the URL. Neither matters when the operator transports the code by hand.

The **semi-automated notifier-URL** flow (operator approves on mobile, token delivered to a URL
ATOM owns) stays documented as a future optimisation, not v1.

| Canonical | Upstox |
|---|---|
| `build_auth_url` | `/v2/login/authorization/dialog?client_id=…&redirect_uri=…&response_type=code` |
| `exchange_code` | `POST /v2/login/authorization/token` |
| `probe_token` | `GET /v2/user/profile` |
| `revoke_token` | `POST /v2/logout` |

Token lifetime: regenerated daily. No 6 AM boundary is documented, unlike Zerodha and Groww.

---

## 4. Instrument master — 🟢 ISIN *is* the key

**Public gzipped JSON, no authentication:**
`https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz`

```json
{
  "segment": "NSE_EQ", "name": "JOCIL LIMITED", "exchange": "NSE",
  "isin": "INE839G01010", "instrument_type": "EQ",
  "instrument_key": "NSE_EQ|INE839G01010",
  "lot_size": 1, "freeze_quantity": 100000.0, "exchange_token": "16927",
  "tick_size": 5.0, "trading_symbol": "JOCIL", "short_name": "JOCIL",
  "security_type": "NORMAL", "cas_eligible": true
}
```

| Field | → `CanonicalInstrument` |
|---|---|
| **`isin`** | **`isin`** 🟢 |
| **`instrument_key`** | **`broker_token`** — `NSE_EQ\|<ISIN>`, so the token *contains* the ISIN |
| `trading_symbol` | `broker_symbol` |
| `name` | `name` · `exchange` | `exchange` |
| `lot_size` | `lot_size` · `tick_size` | `tick_size` ⚠️ §12.3 |
| `security_type` | `broker_flags` |
| `instrument_type` | `instrument_type` — NSE series codes (`EQ`, `BE`, …) |

**Upstox is the only broker where the order key and the join key are the same thing.** No
seed-and-confirm compromise (Zerodha, D-187), no symbol-as-token (Groww). Resolution is a direct
ISIN match.

### 4.1 🟢 A dedicated suspended-instruments file

`https://assets.upstox.com/market-quote/instruments/exchange/suspended-instrument.json.gz`

This is Upstox's equivalent of Groww's `buy_allowed`/`sell_allowed` flags and Dhan's
`ASM_GSM_FLAG`: a pre-flight tradability signal that lets ATOM drop a candidate **before**
placing an order that would be rejected. The adapter fetches it alongside the BOD file and sets
`tradable = False` for every ISIN in it.

A **held** instrument appearing in the suspended list is a warning on the reconciliation row —
ATOM holds something it cannot currently exit.

⚠️ **CSV is deprecated.** Use JSON; the docs state the CSV `tradingsymbol` format is inconsistent
between weekly and monthly contracts and that "these inconsistencies have been resolved in the
JSON version". Files refresh daily **around 6 AM**, so the instrument sync runs after that.

⚠️ `exchange_token` "may be reused by the exchange for a different instrument after its expiry" —
same warning Zerodha gives. ATOM never keys on it; `instrument_key` is stable because it is the
ISIN.

---

## 5. Inbound mappings

### 5.1 Holdings — `GET /v2/portfolio/long-term-holdings`

| Upstox field | → Canonical | Note |
|---|---|---|
| `isin` | *(join key)* | 🟢 |
| `instrument_token` | *(join key)* | `NSE_EQ\|INE…` |
| `quantity` | `total_quantity` | "The total holding qty" |
| `t1_quantity` | `unsettled_quantity` | |
| `cnc_used_quantity` | *(input to §6.1)* | "blocked towards open or completed order" |
| `collateral_quantity` | `pledged_quantity` | |
| `collateral_update_quantity` | `broker_flags` | |
| `collateral_type` / `haircut` | `broker_flags` | RMS collateral category |
| `average_price` | `average_price` | |
| `last_price` | `last_price` | 🟢 present |
| `exchange` | *(join key)* | 🟢 present — unlike Groww and Dhan |
| `company_name` | — | |
| `pnl`, `day_change*`, `close_price` | — | **dropped**, ATOM computes its own (D-156/D-166) |

⚠️ The response carries **both `trading_symbol` and `tradingsymbol`** with identical values — an
apparent legacy duplication. The adapter reads `trading_symbol` and ignores the other.

### 5.2 Orders — `GET /v2/order/retrieve-all`, fills via `GET /v2/order/trades/get-trades-for-day`

Standard shape: `order_id`, `status`, `filled_quantity`, `pending_quantity`,
`average_price`, `status_message`, `tag`.

### 5.3 Quotes

`GET /v2/market-quote/ltp?instrument_key=NSE_EQ|INE…` — batched, and the **Other Standard APIs**
rate bucket allows 50/s, which is far more generous than Zerodha's and Dhan's 1/s quote ceilings.
D-044 still stands: one data provider for all accounts.

### 5.4 🟡 Charges — components, but not per order

`GET /v2/trade/profit-loss/charges?segment=EQ&financial_year=2324&from_date=…&to_date=…`

```json
{"charges_breakdown": {
  "total": 154.23, "brokerage": 97.23,
  "taxes":   {"gst": 20.93, "stt": 15, "stamp_duty": 2},
  "charges": {"transaction": 0.56, "clearing": 0, "ipft": null,
              "others": 0, "sebi_turnover": 0.01, "demat_transaction": 18.5}}}
```

| Upstox | → `CanonicalCharges` | → `charge.charge_type` |
|---|---|---|
| `brokerage` | `brokerage` | `BROKERAGE` |
| `taxes.stt` | `stt` | `STT` |
| `taxes.gst` | `gst` | `GST` |
| `taxes.stamp_duty` | `stamp` | `STAMP` |
| `charges.transaction` + `clearing` + `ipft` + `others` | `exchange` | `EXCHANGE` |
| `charges.sebi_turnover` | `sebi` | `SEBI` |
| **`charges.demat_transaction`** | **`dp`** | **`DP`** 🟢 |

**🟢 Upstox is the only broker that exposes DP charges as a named field.** `atom.charge` already
has a `DP` type and Q-178 asked where DP charges surface — this answers it for Upstox.

**🔴 But the figures are a period total, not per order.** `segment` + `financial_year` +
optional date range; there is no `order_id` in the request or the response. So Upstox and Groww
have **exactly opposite gaps**:

| | Per-order attribution | Component breakdown |
|---|---|---|
| **Dhan** | ✅ per trade | ✅ |
| **Zerodha** | ✅ `/charges/orders` | ✅ |
| **Upstox** | ❌ period total | ✅ (incl. DP) |
| **Groww** | ✅ per order | ❌ aggregate only |
| **Shoonya** | ❌ | ❌ |

On Upstox the charges contrast (D-024, D-179) works at the **period level**: ATOM's summed
computed charges against Upstox's reported total and components, for a date range. Per-fill
contrast is not possible. That is a real degradation and it is labelled as such in the UI —
the per-order column shows *computed* with no broker counterpart, and a period reconciliation
panel carries the broker figures.

Practical consequence: run the charges pull **once per period** (month or FY-to-date), not per
run. `ipft` can be `null`, so the adapter coalesces to zero.

### 5.5 Ledger — not available

No ledger endpoint. Same as Zerodha and Groww; only Dhan provides one (D-179). Q-279 extends here.

---

## 6. Stage-3 normalisation

### 6.1 `free_quantity`

```python
total_quantity = quantity + t1_quantity
free_quantity  = max(0, quantity - cnc_used_quantity - collateral_quantity)
```

`cnc_used_quantity` is documented as "quantity either blocked towards open or completed order",
so it covers both a resting sell and one already filled today — exactly what must come off the
sellable figure. `t1_quantity` is in `total_quantity` but never in `free_quantity`.

### 6.2 GTT ownership

No `tag` on the GTT payload, so — as on Zerodha — `is_ours` is decided **solely** from ATOM's
stored `gtt_order_ids`. The `place_gtt` response returns `data.gtt_order_ids[]`, an **array even
for a single-leg order**; the adapter persists every element before returning (D-176). Raised as
Q-297 in case a tag field exists and is simply undocumented.

### 6.3 Tradability

```python
tradable = isin not in suspended_instrument_set
```

---

## 7. Outbound mappings

### 7.1 `OrderIntent` → `POST /v3/order/place`

| Canonical | Upstox | Value |
|---|---|---|
| `instrument_id` → resolve | `instrument_token` | `NSE_EQ\|<ISIN>` |
| `side` | `transaction_type` | `BUY` / `SELL` |
| `quantity` | `quantity` | |
| `limit_price` | `price` | |
| `order_kind` | `order_type` | **`LIMIT`** (D-174) |
| `product` | `product` | **`D`** (delivery) |
| `validity` | `validity` | `DAY` |
| `client_ref` | `tag` | ≤ 20 chars |
| — | `disclosed_quantity` | `0` |
| — | `trigger_price` | `0` |
| — | `is_amo` | `false` |
| — | `slice` | **`false`** |

⚠️ **`slice` is explicitly `false`.** With slicing enabled the response shape changes to a
per-slice array; ATOM's ETF quantities never approach a freeze limit, so it is pinned off and an
array response is treated as a fault.

### 7.2 `GttIntent` → `POST /v3/order/gtt/place`

```json
{"type": "SINGLE", "quantity": 100, "product": "D",
 "instrument_token": "NSE_EQ|INE…", "transaction_type": "SELL",
 "rules": [{"strategy": "ENTRY", "trigger_type": "ABOVE", "trigger_price": 72.50}]}
```

- `type`: `SINGLE` (exactly one rule) · `MULTIPLE` (2–3 rules, no duplicate strategies)
- `strategy`: `ENTRY` mandatory; `TARGET` / `STOPLOSS` optional and **`IMMEDIATE` only**
- ATOM uses `SINGLE` + `ENTRY` + `ABOVE` for a sell trigger
- **Validity up to one year**; execution is **always LIMIT**
- Returns `data.gtt_order_ids[]`

⚠️ `market_protection` defaults to `-1` (automatic). It is **ignored for LIMIT orders**, which is
all ATOM places, so it is omitted. Setting `0` would cause rejection under the
no-market-orders rule.

### 7.3 Cancel

`DELETE /v3/order/cancel?order_id=…` · GTT: `DELETE /v3/order/gtt/cancel` with the GTT id.

---

## 8. Status map

Upstox order statuses map conventionally; the D-180 default branch is mandatory as everywhere.

| Upstox | → Canonical |
|---|---|
| `complete` | `FILLED` |
| `rejected` | `REJECTED` |
| `cancelled` | `CANCELLED` |
| `open` | `PLACED` (`PARTIAL` if `filled_quantity > 0`) |
| `trigger pending` · `open pending` · `modify pending` · `cancel pending` · `after market order req received` · `validation pending` · `put order req received` | `IN_FLIGHT` |
| **anything else** | **`IN_FLIGHT`** |

GTT: `SCHEDULED` / `active` → `ACTIVE`; `TRIGGERED` → `TRIGGERED`; `CANCELLED` → `CANCELLED`;
`EXPIRED` → `EXPIRED`; else `UNKNOWN`. Q-298 — the GTT status enum is not published as a table.

---

## 9. Error map

| Upstox | → Canonical | Behaviour |
|---|---|---|
| **`UDAPI1154`** static IP restriction | **`IpBlockedError`** | 🔴 Halt everything, **never retry** — infrastructure fault (D-173) |
| **`UDAPI1158`** market orders not allowed | `ValidationError` | Should be unreachable; if seen, a bug (D-174) |
| `UDAPI1156` invalid Algo name | `ValidationError` | Config fault — ATOM sends no `X-Algo-Name` (D-181) |
| `UDAPI100016` invalid credentials · `UDAPI100050` invalid token · `UDAPI100073` client_id inactive | `AuthError` | Halt account |
| `UDAPI100015` API version missing | `ValidationError` | Bug — the version header is mandatory |
| `UDAPI10005` too many requests · HTTP 429 | `RateLimitError` | Backoff with jitter |
| `UDAPI100036` / `UDAPI100038` invalid input · `UDAPI1126`–`UDAPI1143` GTT rule violations | `ValidationError` | Bug, fail loudly |
| `UDAPI1176` / `UDAPI1177` market protection | `ValidationError` | Config fault |
| `UDAPI100500` / HTTP 500 | `UnknownError` | Halt, preserve payload |
| HTTP 503 | `TransientError` | Retry |
| HTTP 403 (on a sell GTT) | **`AuthorisationRequiredError`** | ⚠️ see §12.1 |

Upstox publishes no distinct margin or holdings error code, so an insufficient-funds rejection
arrives as a generic input or order error with the reason in `message`. Kept verbatim in
`reject_reason` (D-042) and **not** parsed into a subtype — string-matching a broker's prose
breaks silently when they reword it. Q-299.

---

## 10. Rate limits

| Category | /sec | /min | /30 min |
|---|---|---|---|
| Order placement (place, modify, cancel, multi, **GTT**) | 10 | 500 | 2,000 |
| Standard APIs (holdings, positions, funds, candles) | 50 | 500 | 2,000 |
| TOTP login | 1 | 10 | 60 |

Aligned to the NSE circular of 5 May 2025. ATOM's ~1 OPS is far below the unregistered ceiling
(D-181).

---

## 11. Webhooks / WebSocket

Order and GTT updates are available over **Webhook** and **portfolio WebSocket stream**. Not used
in v1 — orders rest and are reconciled next run (D-053), and a webhook receiver is a public HTTPS
endpoint for no gain at one run a day.

---

## 12. Broker-specific hazards

### 12.1 🔴 EDIS authorisation gates the entire sell side

> "To place GTT orders with a SELL leg, **EDIS authorization is required**. You can authorize EDIS
> from any of our platforms — Web, iOS, or Android — by placing a GTT order. Once authorized on
> any one platform, it will also be valid for API-based orders. You don't need to complete the
> order; simply going through the authorization flow is sufficient."

**Without EDIS, every sell GTT on Upstox fails** — and ATOM's whole sell side is sell GTTs
(D-063). It is `ONE_TIME` (contrast Zerodha's `PER_SESSION`, which is a *daily* step), performed
manually inside Upstox's own app, with **no API**. Community reports show it surfacing as a
**403 Forbidden on the GTT sell call**, which is why §9 maps that case to
`AuthorisationRequiredError` rather than `AuthError`.

It belongs on the onboarding checklist as a hard gate before the first live run (X9 / Q-270).

**This is not the same thing as the token code.** The code the operator pastes in §3 is an OAuth
authorization code. EDIS is a depository authorisation with no code and no endpoint. Both begin
with a login, which is the only thing they share (D-183a).

### 12.2 ⚠️ Mixed API versions

`/v3` for orders and GTT, `/v2` for portfolio, charges and auth. See §2.

### 12.3 🔴 `tick_size` appears to be in paise in the JSON master

The JSON sample gives `"tick_size": 5.0` for an NSE equity. The deprecated **CSV** sample gives
`0.05` for the equivalent field. Both cannot be rupees.

Reading `5.0` as rupees would make ATOM round every limit price to ₹5 increments — mispricing
every order on a ₹70 ETF by up to ₹5, roughly 7%. **The adapter treats JSON `tick_size` as paise
and divides by 100**, and a startup assertion checks that the derived tick for a known ETF is
≤ ₹0.05. Raised as **Q-300**; it interacts with the already-open Q-179 on ETF tick sizes.

This is the single most dangerous field in this adapter.

### 12.4 ⚠️ GTT response is always an array

`data.gtt_order_ids[]`, even for `SINGLE`. Persist every element before returning (D-176).

### 12.5 ⚠️ MCX API trading is disabled

Noted for completeness. ATOM's commodity ETFs are NSE CASH instruments, so no impact.

---

## 13. Open questions

| ID | Question | Blocks |
|---|---|---|
| **Q-300** 🔴 | Is JSON `tick_size` in paise? A misread mis-rounds every limit price (§12.3) | Order pricing |
| **Q-270** 🔴 | EDIS authorisation per Upstox account — who does it, when (X9) | Upstox sell side |
| Q-274 | Static-IP whitelisting procedure — where in the console is it registered? | Live trading |
| Q-297 | Does the GTT payload accept a tag? If so, `gtt_carries_client_ref` flips to True | GTT identification |
| Q-298 | Full GTT status enum — not published as a table | Status mapping |
| Q-299 | Which error code carries an insufficient-funds rejection, and is the reason machine-readable? | Funds handling |
| Q-279 | No ledger endpoint — how are deposits/withdrawals captured? | Cost of capital |

---

## 14. Sources

[authentication](https://upstox.com/developer/api-documentation/authentication/) ·
[place order v3](https://upstox.com/developer/api-documentation/v3/place-order/) ·
[place GTT](https://upstox.com/developer/api-documentation/place-gtt-order/) ·
[rate limiting](https://upstox.com/developer/api-documentation/rate-limiting/) ·
[get holdings](https://upstox.com/developer/api-documentation/get-holdings/) ·
[instruments](https://upstox.com/developer/api-documentation/instruments/) ·
[trade charges](https://upstox.com/developer/api-documentation/get-trade-charges/) ·
[error codes](https://upstox.com/developer/api-documentation/error-codes/) ·
[regulatory announcement](https://community.upstox.com/t/important-update-regulatory-changes-for-api-and-algo-trading-are-now-live/14874)
