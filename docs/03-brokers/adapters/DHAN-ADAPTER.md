# DhanHQ v2 — Adapter Specification

**Status:** 🟢 Complete — traced to DhanHQ v2 pages read 2026-09-24 / 2026-09-26
**Order of work:** 4th of 5 (see [`../ADAPTER-ENGINE.md`](../ADAPTER-ENGINE.md) §9)
**Pages read:** introduction · authentication · orders · forever orders · portfolio ·
statements · instruments · annexure

> **Why Dhan matters most.** It is the **only** broker of the five that gives ATOM all four of:
> per-trade itemised charges, a real ledger with a running balance, a fully headless token flow,
> and lookup of an order by ATOM's own reference. It is also the only one whose static IP is
> **locked for 7 days** once set, which makes it the broker that punishes an infrastructure
> mistake hardest.

---

## 1. Capability profile

```python
DHAN = BrokerCapabilities(
    broker_code               = "DHAN",

    supports_gtt              = True,          # "Forever Order"
    gtt_max_validity_days     = None,          # not stated (Q-301)
    gtt_carries_client_ref    = True,          # 🟢 correlationId
    gtt_order_type            = "LIMIT_OR_MARKET",   # ATOM uses LIMIT (D-174)

    client_ref_field          = "correlationId",
    client_ref_max_len        = 30,             # canonical generator caps at 20
    client_ref_is_idempotent  = False,          # duplicates not rejected (Q-302)
    lookup_by_client_ref      = True,           # 🟢 GET /v2/orders/external/{correlation-id}

    provides_trade_charges    = True,           # 🟢 per trade, itemised — §5.5
    provides_charge_preview   = False,
    provides_ledger           = True,           # 🟢 the only one — §5.6
    provides_free_quantity    = True,           # 🟢 availableQty, direct

    requires_static_ip        = True,
    static_ip_scope           = "ORDERS_ONLY",  # 🔴 reads work from any IP — §12.2
    static_ip_lock_days       = 7,              # 🔴 §12.1

    token_probe_endpoint      = "PROFILE",      # 🟢 GET /v2/profile returns tokenValidity
    token_revocable           = False,          # no documented revoke

    requires_sell_authorisation = False,        # DDPI reported, not enforced by ATOM (Q-303)
    sell_authorisation_scope    = "NONE",

    orders_per_second         = 10,
    quote_batch_size          = None,           # quote API capped at 1 req/sec
)
```

---

## 2. Wire basics

| | |
|---|---|
| Base URL | `https://api.dhan.co/v2` · auth at `https://auth.dhan.co` |
| Auth | **`access-token: <JWT>`** header — *not* `Authorization: Bearer` |
| Headers | `Content-Type: application/json` · `Accept: application/json` |
| Encoding | JSON on POST/PUT; query or path params on GET |
| Success | HTTP 200/202 with a JSON body |
| Failure | `{"errorType": "", "errorCode": "", "errorMessage": ""}` |

⚠️ **The auth header is `access-token`, not `Authorization`.** Dhan is the only one of the five
that does not use a Bearer header. Most requests also carry `dhanClientId` **in the body**, which
means the adapter needs the client id as well as the token — it comes back from the token
exchange and is stored on `trading_account`.

---

## 3. Session lifecycle — 🟢 fully headless

### 3.1 TOTP token generation — no browser at all

```
POST https://auth.dhan.co/app/generateAccessToken
       ?dhanClientId=…&pin=…&totp=…
→ { accessToken, expiryTime, dhanClientId, dhanClientName,
    dhanClientUcc, givenPowerOfAttorney }
```

**24-hour validity, `expiryTime` returned explicitly.** This is the best automation story of the
five: with TOTP enabled the morning token needs no human at all, which makes Dhan the natural
first candidate for an unattended run.

`GET /v2/RenewToken` expires the current token and issues a fresh 24-hour one — **only** for
tokens generated from Dhan Web, and **only** while the current token is still active.

### 3.2 API key + secret (alternative)

Keys valid **12 months**. Three steps: `POST /app/generate-consent` → browser
`/login/consentApp-login?consentAppId=…` (302 with `tokenId`) → `POST /app/consumeApp-consent`.
Capped at **25 `consentAppId` per day**, one live token at a time.

### 3.3 Probe — 🟢 `GET /v2/profile`, the best of the five

```json
{"dhanClientId":"1100003626","tokenValidity":"30/03/2025 15:37",
 "activeSegment":"Equity, Derivative, Currency, Commodity",
 "ddpi":"Active","mtf":"Active","dataPlan":"Active",
 "dataValidity":"2024-12-05 09:37:52.0"}
```

D-178 prefers a profile probe where one exists, and this is why: it is documented as "a great
test API" and it says **why** an account is unusable — DDPI inactive, data plan expired, segment
not activated — rather than only that it is. A holdings probe returns an empty list for all three
of those and for a genuinely empty account alike.

`givenPowerOfAttorney` (from the token response) and `ddpi` (from profile) are both captured at
onboarding: they determine whether sells need per-trade authorisation.

⚠️ **`tokenValidity` is `DD/MM/YYYY HH:MM`** while `expiryTime` from the token endpoint is
ISO-8601 and `dataValidity` is `YYYY-MM-DD HH:MM:SS.S`. Three date formats in one API. The adapter
parses each explicitly rather than guessing.

### 3.4 Revoke

No documented revoke endpoint. ATOM deletes the SSM parameter and marks the session `CLEARED`.
`RenewToken` invalidates the old token as a side effect but issues a new one, so it is not a
revoke.

---

## 4. Instrument master

**Public CSV, no authentication. Two variants — only one carries ISIN:**

| | URL | ISIN? |
|---|---|---|
| **Detailed** | `https://images.dhan.co/api-data/api-scrip-master-detailed.csv` | ✅ **use this** |
| Compact | `https://images.dhan.co/api-data/api-scrip-master.csv` | ❌ |

Also `GET /v2/instrument/{exchangeSegment}` for one segment at a time.

| Detailed column | → `CanonicalInstrument` |
|---|---|
| **`ISIN`** | **`isin`** 🟢 |
| `SECURITY_ID` *(implied)* | `broker_token` — the id orders take |
| `SYMBOL_NAME` | `broker_symbol` · `DISPLAY_NAME` | `name` |
| `EXCH_ID` | `exchange` · `SEGMENT` | `E` = Equity |
| `LOT_SIZE` | `lot_size` · `TICK_SIZE` | `tick_size` |
| `SERIES` | `broker_flags` · `INSTRUMENT` | `instrument_type` (`EQUITY`) |
| **`ASM_GSM_FLAG`** | `broker_flags` | 🟢 §6.3 |
| **`BUY_SELL_INDICATOR`** | `tradable` | 🟢 §6.3 |
| `MTF_LEVERAGE` | `broker_flags` | |

⚠️ **Use the detailed CSV.** The compact variant has no ISIN column, which would force the
Zerodha seed-and-confirm workaround (D-187) for no reason.

### 4.1 🟢 `ASM_GSM_FLAG` — a surveillance signal no other broker publishes

`N` not under surveillance · `Y` in ASM/GSM · `R` removed from the block, with
`ASM_GSM_CATEGORY` giving the tier.

ASM (Additional Surveillance Measure) and GSM (Graded Surveillance Measure) instruments carry
restricted trading and often 100% margin. This is a genuine input to
`EXCLUSION-AND-FREEZE.md` that ATOM did not previously have a source for: an instrument entering
ASM/GSM is a reason to **freeze new buys** while leaving existing holdings alone.

Proposed: `ASM_GSM_FLAG = 'Y'` sets `instrument.status = 'REVIEW'` for the operator to confirm,
rather than auto-blocking — consistent with D-091's three-stage corporate-action lifecycle.
Raised as **Q-304** because it is a new strategy input, not just an adapter field.

---

## 5. Inbound mappings

### 5.1 Holdings — `GET /v2/holdings`

```json
[{"exchange":"ALL","tradingSymbol":"HDFC","securityId":"1330",
  "isin":"INE001A01036","totalQty":1000,"dpQty":1000,"t1Qty":0,
  "availableQty":1000,"collateralQty":0,"avgCostPrice":2655.0}]
```

| Dhan field | → Canonical | Note |
|---|---|---|
| `isin` | *(join key)* | 🟢 |
| `securityId` | *(join key)* | |
| `totalQty` | `total_quantity` | 🟢 unambiguous name |
| **`availableQty`** | **`free_quantity`** | 🟢 "Quantity available for transaction" — direct |
| `t1Qty` | `unsettled_quantity` | |
| `dpQty` | `broker_flags` | Delivered to demat |
| `collateralQty` | `pledged_quantity` | |
| `avgCostPrice` | `average_price` | |
| — | `last_price` | ❌ not returned — quotes fetched separately |
| `exchange` | ⚠️ **`"ALL"`** | 🔴 §12.4 |

**Dhan and Groww are the two brokers that hand ATOM the sellable quantity directly.** No
derivation, no four-field arithmetic (contrast Zerodha §6.1 and Shoonya §6.1).

### 5.2 Positions — `GET /v2/positions`

`netQty`, `buyAvg`, `costPrice`, `realizedProfit`, `unrealizedProfit`, `positionType`
(`LONG`/`SHORT`/`CLOSED`), carry-forward and day breakdowns. Read for reconciliation only;
`realizedProfit` is **not ingested** (ATOM computes per lot per universe, D-156/D-166).

> 🔴 **`DELETE /v2/positions` exits every position and cancels every open order.** The adapter
> **does not implement it**. It is not in the `BrokerAdapter` protocol, so it cannot be called by
> mistake — the safest way to handle a destructive endpoint is to have no code path to it.

### 5.3 Orders — `GET /v2/orders` · `GET /v2/orders/{order-id}` · 🟢 `GET /v2/orders/external/{correlation-id}`

| Dhan | → `OrderState` |
|---|---|
| `orderId` | `broker_order_id` |
| `correlationId` | `client_ref` 🟢 |
| `orderStatus` | `status` (§8) |
| `filledQty` | `filled_quantity` |
| `remainingQuantity` | `pending_quantity` |
| `averageTradedPrice` | `average_price` |
| `omsErrorCode` + `omsErrorDescription` | `reject_reason` |
| `algoId` | `broker_flags` — "Exchange Algo ID for Dhan", populated by Dhan, not ATOM |

🟢 **`GET /v2/orders/external/{correlation-id}`** — "In case the user has missed order id due to
unforeseen reason, this API retrieves the order status using a tag called correlation id specified
by users themselves."

This upgrades `lookup_by_client_ref` to **True** (round 2 recorded it as unknown). A network
timeout during placement is recoverable: query by `correlationId` and learn whether the order
exists. It is not full idempotency — Dhan does not document rejecting a duplicate
`correlationId` (Q-302) — but it removes the order-book scan.

🟢 **`omsErrorCode` / `omsErrorDescription`** give a structured rejection reason, which is better
than the prose-only rejections on Upstox and Groww.

### 5.4 Fills — ⚠️ two different `/trades` routes

| Route | Returns | Charges? |
|---|---|---|
| `GET /v2/trades` | today's trades | ❌ |
| `GET /v2/trades/{order-id}` | trades for one order | ❌ |
| **`GET /v2/trades/{from-date}/{to-date}/{page}`** | historical, paginated | ✅ **itemised** |

⚠️ **`/v2/trades/{order-id}` and `/v2/trades/{from}/{to}/{page}` are different endpoints whose
paths overlap in shape.** A single-segment path is an order id; a three-segment path is a date
range plus page. The adapter builds each explicitly and never by string concatenation.

| Field | → `CanonicalFill` |
|---|---|
| `exchangeTradeId` | `broker_trade_id` |
| `orderId` | `broker_order_id` |
| `tradedQuantity` | `quantity` |
| `tradedPrice` | `fill_price` |
| `exchangeTime` | `filled_at` |

### 5.5 🟢 Charges — per trade, itemised

From the historical route, each trade carries:

| Dhan | → `CanonicalCharges` | → `charge_type` |
|---|---|---|
| `brokerageCharges` | `brokerage` | `BROKERAGE` |
| `stt` | `stt` | `STT` |
| `exchangeTransactionCharges` | `exchange` | `EXCHANGE` |
| `sebiTax` | `sebi` | `SEBI` |
| `stampDuty` | `stamp` | `STAMP` |
| `serviceTax` | `gst` | `GST` |

Plus `isin`, `exchangeOrderId`, `instrument`. **This is the ground truth for D-179's
charges-contrast view** — estimated vs actual, per fill *and* per component. Only Zerodha also
manages this, and Zerodha's route is a calculator rather than a record of what was charged.

⚠️ `serviceTax` is GST. The naming predates GST and the adapter maps it accordingly rather than
inventing a `SERVICE_TAX` type.

### 5.6 🟢 Ledger — the only one of the five

`GET /v2/ledger?from-date=YYYY-MM-DD&to-date=YYYY-MM-DD`

| Dhan | → `CanonicalCashEvent` |
|---|---|
| `voucherdate` | `event_date` |
| `debit` / `credit` | `amount` (signed) |
| `narration` | `narration` |
| **`runbal`** | **`running_balance`** |
| `vouchernumber` | `broker_ref` |
| `voucherdesc` | *(classification input)* |

`runbal` is the reconciliation anchor for `COST-OF-CAPITAL.md`: ATOM's computed
`principal_outstanding` can be checked against the broker's own running balance rather than only
against its internal ledger. A withdrawal appears as `narration = "FUNDS WITHDRAWAL"` with
`voucherdesc = "PAYBNK"` — which D-078 models as a repayment to the firm.

The `voucherdesc → event_type` mapping must be built from a real pull (Q-276); `PAYBNK` is the
only value observed in the documentation. Unmapped values become `UNKNOWN`, never guessed.

---

## 6. Stage-3 normalisation

### 6.1 `free_quantity` — 🟢 no derivation

```python
total_quantity = totalQty
free_quantity  = availableQty
```

### 6.2 GTT ownership

```python
is_ours = (correlationId is not None and correlationId in atom_known_refs)
```

Answerable from broker data, like Groww. The DB mapping stays primary; Dhan's field is the
cross-check that would catch an orphan.

### 6.3 Tradability

```python
tradable = (BUY_SELL_INDICATOR == 'A') and ASM_GSM_FLAG != 'Y'
```

`BUY_SELL_INDICATOR = 'A'` means both buy and sell are allowed. Combined with `ASM_GSM_FLAG`,
Dhan gives the richest pre-flight tradability signal of the five — better even than Groww's
boolean pair, because the ASM/GSM category carries severity.

---

## 7. Outbound mappings

### 7.1 `OrderIntent` → `POST /v2/orders`  🔴 *requires whitelisted IP*

| Canonical | Dhan | Value |
|---|---|---|
| — | `dhanClientId` | from `trading_account` |
| `client_ref` | `correlationId` | ≤ 30 chars (canonical ≤ 20) |
| `side` | `transactionType` | `BUY` / `SELL` |
| `instrument_id` → resolve | `securityId` | Dhan security id |
| — | `exchangeSegment` | **`NSE_EQ`** |
| `product` | `productType` | **`CNC`** |
| `order_kind` | `orderType` | **`LIMIT`** (D-174) |
| `validity` | `validity` | `DAY` |
| `quantity` | `quantity` | |
| `limit_price` | `price` | |
| — | `afterMarketOrder` | `false` |

Not sent: `disclosedQuantity`, `triggerPrice`, `amoTime`, `boProfitValue`, `boStopLossValue`.

⚠️ `POST /v2/orders/slicing` exists for freeze-limit quantities. **Not implemented** — ATOM's ETF
quantities never approach a freeze limit, and an unimplemented endpoint cannot be called by
accident.

### 7.2 `GttIntent` → `POST /v2/forever/orders`  🔴 *requires whitelisted IP*

```json
{"dhanClientId":"…","correlationId":"atom-20260926-071",
 "orderFlag":"SINGLE","transactionType":"SELL","exchangeSegment":"NSE_EQ",
 "productType":"CNC","orderType":"LIMIT","validity":"DAY",
 "securityId":"1330","quantity":100,"price":72.45,"triggerPrice":72.50}
```

- `orderFlag`: `SINGLE` (ATOM) or `OCO`
- `productType` for Forever Orders: **`CNC` or `MTF` only**
- Status: `TRANSIT` · `PENDING` · `REJECTED` · `CANCELLED` · `TRADED` · `EXPIRED` · `CONFIRM`
- List: `GET /v2/forever/orders` (also `/v2/forever/all`)

⚠️ `validity: "DAY"` here refers to the order placed **when the trigger fires**, not the Forever
Order's own life — the same trap as Groww's `duration` field. The Forever Order's validity is not
documented (Q-301).

### 7.3 Cancel

Order: `DELETE /v2/orders/{order-id}` → **202 Accepted**.
Forever: `DELETE /v2/forever/orders/{order-id}`.

⚠️ 202 means *accepted*, not *cancelled*. Q-185 (is cancellation synchronous?) is answered for
Dhan: **it is not**. The cancel-all-first step must re-poll `GET /v2/forever/orders` to verify
the book is clean before proceeding, exactly as D-063's step 2 requires.

---

## 8. Status map

The **orders page** and the **annexure** publish different enums. The adapter maps the **union**.

| Dhan | → Canonical | Source |
|---|---|---|
| `TRADED` | `FILLED` | both |
| `PART_TRADED` | `PARTIAL` | orderbook, annexure |
| `REJECTED` | `REJECTED` | both |
| `CANCELLED` | `CANCELLED` | both |
| `EXPIRED` | `CANCELLED` | orders page only |
| `PENDING` | `PLACED` | both |
| `CONFIRM` | `ACTIVE` (Forever) | forever page |
| `TRANSIT` | `IN_FLIGHT` | "Did not reach the exchange server" |
| `TRIGGERED` | `IN_FLIGHT` | annexure — Super Order leg |
| `CLOSED` | `FILLED` | annexure — Super Order complete |
| **anything else** | **`IN_FLIGHT`** | D-180 |

⚠️ **`TRANSIT` is not terminal.** "Did not reach the exchange server" reads like a failure but
describes an in-flight state. Mapping it to `REJECTED` would make ATOM re-place an order that is
still on its way — the D-180 failure mode, with a name that actively invites it.

---

## 9. Error map

| Dhan | → Canonical | Behaviour |
|---|---|---|
| `DH-901` invalid/expired token | `AuthError` | Halt account |
| `DH-902` not subscribed / no access | `AuthError` | Halt — check `dataPlan` via profile |
| `DH-903` user account (segments not activated) | `AuthError` | Halt, surface `activeSegment` |
| `DH-904` rate limit | `RateLimitError` | Backoff with jitter |
| `DH-905` input exception | `ValidationError` | Bug, fail loudly |
| `DH-906` order error | `UnknownError` | Halt, preserve payload |
| `DH-907` data error | `TransientError` | Retry bounded |
| `DH-908` internal server error | `TransientError` | Retry |
| `DH-909` network error | `TransientError` | Retry |
| `DH-910` others | `UnknownError` | Halt |
| Data API `807`/`809` token expired/invalid · `808` auth failed · `810` invalid client id | `AuthError` | |
| Data API `805` too many requests | `RateLimitError` | ⚠️ "further requests may result in the user being **blocked**" — back off hard |
| Data API `806` not subscribed | `AuthError` | |
| Data API `813` invalid securityId | `ValidationError` | Instrument-resolution bug |

🔴 **No distinct IP-blocked code is published.** Upstox has `UDAPI1154`; Dhan does not document an
equivalent, so an order from a non-whitelisted IP most likely arrives as `DH-903` or `DH-906`.
Since ATOM cannot distinguish it from a genuine account problem, **egress IP is verified
pre-flight and independently** (§12.2) rather than inferred from a rejection. Q-305.

---

## 10. Rate limits

| | /sec | /min | /hour | /day |
|---|---|---|---|---|
| Order APIs | 10 | 250 | 1,000 | 7,000 |
| Data APIs | 5 | — | — | 100,000 |
| **Quote APIs** | **1** | unlimited | unlimited | unlimited |
| Non-trading | 20 | unlimited | unlimited | unlimited |

Plus **max 25 modifications per order**. Irrelevant — ATOM cancels and re-places (D-063).

**Quote at 1/sec** is the tightest data ceiling alongside Zerodha's, and together they settle
D-044: one data provider for all accounts.

---

## 11. Postback

A Postback URL can be set at token generation for order updates. Not used in v1 (D-053).

---

## 12. Broker-specific hazards

### 12.1 🔴 The static IP is locked for 7 days

`POST /v2/ip/setIP` · `PUT /v2/ip/modifyIP` · `GET /v2/ip/getIP`, with
`{dhanClientId, ip, ipFlag: PRIMARY|SECONDARY}`. IPv4 and IPv6 both accepted.

> "Once an IP is whitelisted, it cannot be edited for the next 7 days or as recommended by the
> exchange." · "Each individual needs to have a unique static IP."

`getIP` returns `modifyDatePrimary` / `modifyDateSecondary` — the earliest date each may change.

**An instance rebuild that picks up a fresh address is a week-long outage on Dhan**, not a
restartable error. Consequences already recorded as D-173: the Elastic IP is mandatory, and it
must be allocated *before* the address is registered. The secondary IP slot is the failover and
should be populated at onboarding, not left empty.

### 12.2 🔴 Whitelisting gates writes only — so the token probe does not exercise it

> "Static IP is only required while using Order Placement APIs including Orders, Super Order,
> Forever Order. While fetching order details or trade details, no such IP whitelisting is
> required."

The D-170/D-178 probe reads **profile**, which works from any address. **A token can probe green
and the first order still fail on IP.** Egress-IP verification is therefore a **separate
pre-flight gate**, run on every run (`verify_egress_ip.py`), never folded into token validity.

Combined with §9's missing IP error code, this is the one broker where an IP fault is both
invisible to the probe *and* hard to identify from the rejection. The pre-flight check is the only
reliable defence.

### 12.3 ⚠️ `access-token` header, and `dhanClientId` in the body

Not `Authorization: Bearer`. And most calls need the client id as a payload field, so the adapter
carries both credentials.

### 12.4 🔴 Holdings return `exchange: "ALL"`

Not `NSE` or `BSE`. `atom.instrument` is keyed `UNIQUE (isin, exchange)`, so a dual-listed ISIN
cannot be disambiguated from the holdings response — worse than Groww §6.2, where the field is
merely absent rather than actively unhelpful.

**Resolution:** match on ISIN; where more than one instrument row matches, resolve via
`broker_instrument` on `securityId`, which *is* segment-specific. If ambiguity survives, the
account's run **blocks** rather than guessing. ATOM's ETF universe is NSE-only so this should
never fire, and "should never" is not "cannot".

### 12.5 ⚠️ Three date formats in one API

`expiryTime` ISO-8601 · `tokenValidity` `DD/MM/YYYY HH:MM` · `dataValidity`
`YYYY-MM-DD HH:MM:SS.S` · ledger `voucherdate` `"Jun 22, 2022"`. Four, counting the ledger. Each
parsed explicitly.

### 12.6 ⚠️ Overlapping `/trades` paths

§5.4. Build paths explicitly.

### 12.7 ⚠️ Cancellation is 202 Accepted, not confirmed

§7.3. Re-poll to verify.

---

## 13. Open questions

| ID | Question | Blocks |
|---|---|---|
| Q-301 | Forever Order maximum validity — not documented | GTT staleness policy |
| Q-302 | Does a duplicate `correlationId` get rejected? If yes, `client_ref_is_idempotent` flips to True | Retry safety |
| Q-303 | With `ddpi: "Active"`, is any per-trade sell authorisation still needed? | Sell pass |
| **Q-304** | Should `ASM_GSM_FLAG = 'Y'` set `instrument.status = 'REVIEW'` and freeze new buys? A new strategy input, not just an adapter field | Exclusion model |
| **Q-305** 🔴 | Which error code does an order from a non-whitelisted IP return? No documented equivalent of `UDAPI1154` | IP fault diagnosis |
| Q-276 | Build the `voucherdesc` → cash-event mapping from a real ledger pull | Cost-of-capital classifier |
| Q-275 | Data API plan cost per account | Running-cost model |

---

## 14. Sources

[introduction](https://dhanhq.co/docs/v2/) ·
[authentication](https://dhanhq.co/docs/v2/authentication/) ·
[orders](https://dhanhq.co/docs/v2/orders/) ·
[forever orders](https://dhanhq.co/docs/v2/forever/) ·
[portfolio](https://dhanhq.co/docs/v2/portfolio/) ·
[statements](https://dhanhq.co/docs/v2/statements/) ·
[instruments](https://dhanhq.co/docs/v2/instruments/) ·
[annexure](https://dhanhq.co/docs/v2/annexure/)
