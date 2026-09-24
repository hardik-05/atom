# Broker API Reference — Verified from Vendor Documentation

**Status:** 🟢 Round 2 complete — every fact below was read from the vendor's own developer
documentation on the date shown, not inferred and not carried over from round 1.
**Date fetched:** 2026-09-24
**Supersedes:** the `❓ UNVERIFIED` cells in `BROKER-CAPABILITY-MATRIX.md`

> **Rule for this document.** Each section names the exact page it came from. Where a vendor's
> documentation contradicts what ATOM assumed in an earlier round, the contradiction is stated
> plainly rather than quietly reconciled. Where two vendors describe the same regulation
> differently, both readings are recorded — that divergence is itself a finding.

---

## 0. The headline: three regulatory changes that are already live

This is the most consequential result of the round, and it changes design, not just detail.
All three took effect **1 April 2026** — five months before today's date — so they are current
operating conditions, not upcoming ones.

### 0.1 Static IP registration is mandatory

> "API trading now requires a **registered static IP** and **Algo registration** for strategies
> exceeding **10 orders per second (OPS)**."
> — [Upstox Community, 31 Mar 2026](https://community.upstox.com/t/important-update-regulatory-changes-for-api-and-algo-trading-are-now-live/14874)

Citing SEBI's *Safer participation of retail investors in Algorithmic trading* circular and NSE
circular **NSE/INVG/67858**.

This is the single strongest external validation of ATOM's infrastructure design. The
per-investor static egress IP (D-009 … D-011), the local forward proxy, and
`verify_egress_ip.py` were designed to satisfy a requirement that is now **enforced**, and all
three brokers that document it independently confirm the same shape:

| Broker | Whitelisting surface | Constraint discovered |
|---|---|---|
| **Dhan** | **API** — `POST /v2/ip/setIP`, `PUT /v2/ip/modifyIP`, `GET /v2/ip/getIP` | **Primary + secondary IP.** Each individual needs a **unique** static IP. **Once set, it cannot be changed for 7 days.** IPv4 and IPv6 both accepted. Required for **order placement only** — reads need no whitelisting. |
| **Upstox** | Developer console | Rejection surfaces as error **`UDAPI1154` — "Access to this API is blocked due to static IP restrictions."** |
| **Shoonya** | Trading account → API Key Generation screen | **Primary + backup IP.** Blocks the OAuth flow itself, not just orders — "before you can complete the OAuth login flow **or call any endpoint**". |

Sources: [Dhan authentication](https://dhanhq.co/docs/v2/authentication/),
[Upstox place GTT](https://upstox.com/developer/api-documentation/place-gtt-order/),
[Shoonya IP whitelisting](https://shoonya.com/api-documentation/ip-whitelisting).

**Two design consequences ATOM did not previously account for.**

1. **Dhan's 7-day IP lock makes the Elastic IP non-negotiable and the ordering of setup
   strict.** If an instance is rebuilt and picks up a new address, the account is locked out of
   order placement for up to a week. The AWS design must allocate the Elastic IP *before* the
   IP is registered with any broker, and `verify_egress_ip.py` must run as a **pre-flight gate
   on every run**, not only at onboarding — a silent IP change is a week-long outage, not a
   restartable error.
2. **Dhan distinguishes read from write.** Holdings, order book and trade book work from any
   address; only Orders, Super Order and Forever Order require the whitelisted IP. The D-170
   token probe (which reads holdings) therefore **does not exercise the proxy path on Dhan** —
   a token can probe green and still fail at the first order. The pre-flight must verify
   egress IP *separately* from token validity, not fold one into the other.

### 0.2 Market orders are no longer permitted via API

> "**Market Orders are no longer permitted.** To ensure safer execution, **Market Price
> Protection (MPP)** is now enabled by default for all order placements." — Upstox, as above

Upstox surfaces this as error **`UDAPI1158` — "Market orders are not allowed. Try placing a
limit order."** Zerodha and Upstox both now expose a `market_protection` parameter that converts
a market order into a limit order at a bounded distance from LTP (`-1` = automatic per exchange
guidance, or a custom percentage: Upstox caps at 25%, Zerodha at 100%).

ATOM already places **limit orders only** (D-057, Q-027) — so nothing breaks. But this closes
the question for good: the market-order path is not a fallback ATOM can keep in reserve, and
the adapter contract should not carry a `MARKET` order type at all for the live path. Dhan's
documented behaviour (market → limit with protection) was round 1's hint; it is now the rule
everywhere.

### 0.3 Algo ID — and a genuine disagreement between brokers

Here the two vendors who document it **do not agree**, and ATOM cannot resolve this from
documentation alone.

| Source | Reading |
|---|---|
| **Upstox** | Algo registration required only for strategies **exceeding 10 OPS**. `X-Algo-Name` header is **optional**, "only required if you have an exchange-approved algo strategy". Invalid value → `UDAPI1156`. |
| **Shoonya** | SEBI circular **SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013** requires **every order placed through an API** — "not just orders from registered algo strategies" — to carry a broker-empanelled Algo ID. "Orders placed via the API without a valid, empanelled Algo ID after that date are expected to be **rejected at the exchange level**." A "personal script placing orders via the API" is listed as **requiring** an Algo ID. |

Sources: [Upstox rate limiting](https://upstox.com/developer/api-documentation/rate-limiting/),
[Shoonya SEBI Algo ID framework](https://shoonya.com/api-documentation/algo-compliance).

Shoonya's own page hedges on the field name — "confirm the exact field name with your
onboarding contact, as it is being finalized across the industry".

**This is a live blocker, not a documentation gap.** Under Shoonya's reading, ATOM cannot place
a single order on Shoonya without an empanelled Algo ID, regardless of its 2 OPS ceiling
(D-149). Under Upstox's reading, ATOM at 2 OPS needs nothing. Both may be true — brokers may
be implementing the same circular with different strictness — and it must be settled per broker
before any live order. It is raised as **Q-268** and added to the external blocker list as
**X8**.

The adapter contract must therefore carry an **optional per-account `algo_id` / `algo_name`**
that each adapter maps to its broker's field, defaulting to unset. Building it in now costs
nothing; retrofitting it after a rejection costs a trading day.

---

## 1. Authentication — every flow, verified

Round 1 concluded "the five brokers do not share one flow". Round 2 confirms that, and finds
the picture is **better than feared**: four of the five now offer a non-interactive path
(TOTP or checksum), which means the daily "generate token" step can be automated for most
accounts rather than requiring a human at a browser every morning.

### 1.1 Upstox — three methods

[Source](https://upstox.com/developer/api-documentation/authentication/)

| Method | Shape | Suits ATOM? |
|---|---|---|
| **Authorization code** | `GET https://api.upstox.com/v2/login/authorization/dialog` → single-use `code` at redirect URI → `POST /v2/login/authorization/token` with `code`, `client_id`, `client_secret`, `redirect_uri`, `grant_type=authorization_code` | Yes — needs the hosted redirect |
| **Semi-automated** | App triggers an auth request at a set time; operator approves from a **mobile notification** or the developer dashboard; **the token is then delivered to a notifier URL** configured at app creation | **Strong fit** — approval by phone tap, token arrives at ATOM without a browser |
| **Manual** | Generate and copy from the Upstox Developer Apps dashboard | Paste-in fallback |

TOTP is available for 2FA. Two gotchas worth recording: **redirect URLs ending in `.php` may be
blocked**, and the redirect should not sit at the very end of the URL.

The **semi-automated / notifier-URL** flow is the closest any broker comes to the pattern the
brief asked for — a "generate token" action the operator approves from their phone, with the
token landing in the system by itself.

### 1.2 Dhan — two methods, and TOTP makes one of them fully headless

[Source](https://dhanhq.co/docs/v2/authentication/)

**(a) Direct access token.** Generated from web.dhan.co → My Profile → *Access DhanHQ APIs*.
**Validity 24 hours.** A Postback URL can be set at generation time for order updates.

**With TOTP enabled, this becomes a single API call — no browser at all:**

```
POST https://auth.dhan.co/app/generateAccessToken
     ?dhanClientId=...&pin=...&totp=...
```

returning `accessToken` and an explicit `expiryTime`. There is also a **renew** endpoint
(`GET /v2/RenewToken`) that expires the current token and issues a fresh 24-hour one — it works
only for tokens generated from Dhan Web, and only while the current token is still active.

**(b) API key + secret, OAuth-style, three steps.** Key and secret are **valid 12 months**.

1. `POST https://auth.dhan.co/app/generate-consent?client_id=...` with `app_id` / `app_secret`
   headers → `consentAppId`
2. Browser: `https://auth.dhan.co/login/consentApp-login?consentAppId=...` → 302 redirect to the
   registered URL carrying `tokenId`
3. `POST https://auth.dhan.co/app/consumeApp-consent?tokenId=...` → `accessToken`, `expiryTime`

Limit: **25 `consentAppId` per day**, only one token live at a time.

**Token validity is also directly readable** — `GET /v2/profile` returns `tokenValidity`
alongside `ddpi`, `mtf` and `dataPlan` status. This is a cheaper, more explicit probe than the
holdings call D-170 specifies, and it returns *why* an account is unusable (DDPI inactive, data
plan expired) rather than just that it is.

### 1.3 Zerodha — request token exchange, hard 6 AM expiry

[Source](https://kite.trade/docs/connect/v3/user/)

1. `https://kite.zerodha.com/connect/login?v=3&api_key=xxx`
2. Redirect returns `request_token` (lifetime: **a few minutes**)
3. `POST https://api.kite.trade/session/token` with `api_key`, `request_token`, and
   `checksum` = **SHA-256 of `api_key + request_token + api_secret`**
4. All later calls: `Authorization: token api_key:access_token`

**Token lifetime — now verified, and it is a hard boundary:**

> "Unless this is invalidated using the API, or invalidated by a master-logout from the Kite Web
> trading terminal, it'll **expire at 6 AM on the next day (regulatory requirement)**."

This resolves a `❓ UNVERIFIED` cell and adds a constraint: **a Zerodha token generated before
6 AM dies before the market opens.** The run schedule and the token-generation window must not
straddle 6 AM. `refresh_token` exists but is "only available to certain approved platforms" —
not available to ATOM.

`DELETE /session/token` explicitly invalidates the session, which is exactly the D-170
end-of-run `CLEARED` step. Zerodha is the one broker where ATOM can *actively* destroy the
token rather than merely forgetting it.

An optional `redirect_params` can be appended to the login URL and comes back at the redirect —
useful for carrying `trading_account_id` through the flow so the console knows which account a
returning token belongs to.

### 1.4 Groww — three methods, two of them headless

[Source](https://groww.in/trade-api/docs/curl)

Requires an **active Trading API subscription** (paid — purchased from the Groww profile page).

| Approach | Mechanism | Expiry |
|---|---|---|
| **1. Access token** | Generated in Profile → Settings → Trading APIs | **Expires daily at 6:00 AM** |
| **2. API key + secret** | `POST /v1/token/api/access` with `key_type: "approval"`, a **SHA-256 checksum of `secret + epoch_timestamp`**, and that timestamp (valid 10 minutes) | Requires **daily approval** on the Groww Cloud API Keys page |
| **3. API key + TOTP** | Same endpoint, `key_type: "totp"`, `totp: "123456"` | Requires **daily approval** on the same page |

`/v1/token/api/access` is capped at **150 requests per 24 hours**.

Note the trap in methods 2 and 3: the checksum or TOTP call is headless, but Groww still
requires a **daily human approval** in its web console. So Groww is *not* fully automatable
either — the operator action moves from "copy a token" to "click approve", which is still a
daily touch.

Groww shares Zerodha's **6 AM** expiry boundary.

### 1.5 Shoonya — rebuilt on OAuth 2.0; the old flow is gone

[Source](https://shoonya.com/api-documentation/api-structure),
[quick start](https://shoonya.com/api-documentation/quick-start)

**This supersedes `SHOONYA.md` in full.** Shoonya has migrated from the legacy Noren
`QuickAuth` (userid + password hash + TOTP + vendor code + api secret, token echoed in every
request body) to **OAuth 2.0 with a Bearer header**. The SDK package name changed too:
`NorenRestApiOAuth`, not `NorenRestApiPy`.

| | |
|---|---|
| REST base | `https://api.shoonya.com/NorenWClientAPI/` |
| WebSocket | `wss://api.shoonya.com/NorenWSAPI/` |
| Historical | `https://api.shoonya.com/chartapi/getdata/` |
| Authorize | `https://api.shoonya.com/OAuthlogin/authorize/oauth?client_id=...` |
| Auth header | `Authorization: Bearer <AccessToken>` — **not** repeated in the body |

Flow: authorize URL → capture `code` from redirect → `checksum = SHA-256(client_id +
secret_code + auth_code)` → `gen_access_token(uid, code, appkey=checksum)` → `susertoken`.

Request format is unchanged and still unusual — `Content-Type: text/plain` with a single
`jData=<JSON>` body field:

```bash
curl -X POST https://api.shoonya.com/NorenWClientAPI/PlaceOrder \
  -H "Content-Type: text/plain" \
  -H "Authorization: Bearer <AccessToken>" \
  -d 'jData={"exch":"NSE","tsym":"CANBK-EQ","qty":"1","buy_or_sell":"B"}'
```

Every response carries `stat` = `Ok` / `Not_Ok`, with `emsg` on failure. Field names are
abbreviated (`tsym`, `qty`, `prc`, `trgprc`) and numerics are **strings inside the JSON**, not
JSON numbers — the adapter must serialise carefully.

**Token lifetime remains `❓ UNVERIFIED`** — the `manual-login-oauth` page returned 403 to
automated fetch. Raised as **Q-269**.

### 1.6 What this means for the token console

The brief asked for one common pattern across five brokers. There is no single pattern, but
there are **three**, and the console needs exactly three screens, not five:

| Pattern | Brokers | Operator action each morning |
|---|---|---|
| **A — Headless (TOTP/checksum)** | Dhan, Groww¹, Shoonya² | None, or one approval click (Groww) |
| **B — Hosted redirect** | Upstox, Zerodha, Dhan (key+secret), Shoonya | Click "Login", authenticate, redirect lands token |
| **C — Paste-in** | All five | Copy from broker's site, paste into ATOM |

¹ Groww still needs the daily approval click.
² Shoonya's TOTP setup guide exists, but the OAuth code step still appears interactive.

**Pattern C must be implemented for all five as the guaranteed fallback** — every broker
supports copy-paste, and it is the only path that cannot be broken by a vendor changing its
redirect handling. A and B are optimisations layered on top.

---

## 2. GTT — verified per broker, and the semantics differ more than round 1 suggested

### 2.1 Upstox

[Source](https://upstox.com/developer/api-documentation/place-gtt-order/) — `POST https://api.upstox.com/v3/order/gtt/place`

```json
{
  "type": "SINGLE",
  "quantity": 1,
  "product": "D",
  "rules": [{ "strategy": "ENTRY", "trigger_type": "ABOVE", "trigger_price": 6,
              "market_protection": 0 }],
  "instrument_token": "NSE_EQ|INE669E01016",
  "transaction_type": "BUY"
}
```

- `type`: `SINGLE` (exactly one rule) or `MULTIPLE` (**2–3 rules, no duplicate strategies**)
- `strategy`: `ENTRY` (mandatory) · `TARGET` · `STOPLOSS`
- `trigger_type`: ENTRY may be `ABOVE` / `BELOW` / `IMMEDIATE`; TARGET and STOPLOSS **only**
  `IMMEDIATE`
- `product`: `I` (intraday) · `D` (delivery) · `MTF`
- Returns `data.gtt_order_ids[]` — an **array**, even for a single-leg order
- **Validity: up to one year** from creation
- **"A GTT order is always placed as a LIMIT order upon execution."**

**⚠️ Operational prerequisite ATOM had not captured: EDIS authorization is required for any
GTT with a SELL leg.** It is a one-time flow done from Upstox Web/iOS/Android — "You don't need
to complete the order; simply going through the authorization flow is sufficient" — and once
done on any platform it covers API orders too.

ATOM's entire sell side is GTT sells. **Without EDIS, every sell GTT on Upstox fails.** Added
to onboarding as a hard gate; raised as **Q-270**.

### 2.2 Dhan — "Forever Order"

[Source](https://dhanhq.co/docs/v2/forever/)

| | |
|---|---|
| Create | `POST /v2/forever/orders` |
| Modify | `PUT /v2/forever/orders/{order-id}` |
| Cancel | `DELETE /v2/forever/orders/{order-id}` |
| List | `GET /v2/forever/orders` (and `GET /v2/forever/all`) |

- `orderFlag`: `SINGLE` or `OCO`
- `productType` for Forever Orders: **`CNC` or `MTF` only**
- `orderType`: `LIMIT` or `MARKET`; `validity`: `DAY` or `IOC`
- OCO adds `price1` / `triggerPrice1` / `quantity1` for the second leg
- Modify requires `legName`: `TARGET_LEG` (single, or first OCO leg) or `STOP_LOSS_LEG`
- Status enum: `TRANSIT` · `PENDING` · `REJECTED` · `CANCELLED` · `TRADED` · `EXPIRED` · `CONFIRM`
- **Requires the whitelisted static IP** (per §0.1)

**`correlationId` — up to 30 characters, user-supplied, "for tracking back".** This is Dhan's
answer to "cancel only ATOM's own GTTs" (D-064): ATOM can stamp its own identifier at
placement and read it back from the order list.

### 2.3 Zerodha

[Source](https://kite.trade/docs/connect/v3/gtt/) — `POST /gtt/triggers`

- `type`: `single` (one trigger value) or `two-leg` (OCO — two values, one cancels the other)
- `condition`: `{exchange, tradingsymbol, trigger_values[], last_price}` — **`last_price` must
  be supplied at placement**, so ATOM needs a live quote in hand before it can place a GTT
- `orders[]`: array whose **index determines which order fires for which trigger value**
- `order_type` in a GTT order: **`LIMIT` only**
- Status: `active` · `triggered` · `disabled` · `expired` · `cancelled` · `rejected` · `deleted`
- Retrieval covers active GTTs plus **the previous 7 days** of other states
- Modification is a `PUT` — but the docs recommend fetching by ID first and modifying the
  returned object, which matters because a partial PUT will silently drop fields

**⚠️ Finding that affects D-064 directly.** An *active* Zerodha trigger returns `"meta": {}` or
`null` — there is **no tag or app identifier on the trigger itself**. The `app_id` only appears
inside `orders[].result.meta` *after* the trigger has fired. So on Zerodha, ATOM **cannot**
identify its own GTTs from the broker's data. The cancel-all-first step must work from ATOM's
own `trigger_id` mapping in the database, and a GTT placed by the investor through Kite Web is
indistinguishable from ATOM's until it fires.

This is the strongest case in the matrix for storing every placed `trigger_id` durably: on
Zerodha it is the *only* link between ATOM and its own orders. If that mapping is ever lost,
ATOM can neither cancel its own GTTs nor safely leave the investor's alone.

### 2.4 Groww — "Smart Orders"

[Source](https://groww.in/trade-api/docs/curl/smart-orders) — `POST /v1/order-advance/create`

This resolves the round-1 `❓ UNVERIFIED` Groww GTT payload in full.

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

- `trigger_direction`: `UP` / `DOWN` — an explicit direction field no other broker has
- Prices are **decimal strings**, not numbers
- **`reference_id` is an explicit idempotency key** — 8–20 alphanumeric characters, at most two
  hyphens. Reuse returns `GA007 Duplicate order reference id`.
- **"GTT orders placed via API automatically default to a one-year validity period."**
- `CASH` and `FNO` only — `COMMODITY` unsupported (harmless for NSE-listed commodity ETFs)
- Modify: `PUT /v1/order-advance/modify/{smart_order_id}`. For GTT, quantity, trigger price,
  trigger direction, order type and limit price are modifiable; **duration and product type are
  not** — those need cancel + create
- Cancel: `POST /v1/order-advance/cancel/{segment}/{smart_order_type}/{smart_order_id}`
- List: `GET /v1/order-advance/list` filtered by `segment`, `smart_order_type`, `status`
  (`ACTIVE` / `CANCELLED` / `COMPLETED`) and a time window of **at most one month**
- Response carries `is_cancellation_allowed` and `is_modification_allowed` flags — ATOM should
  read these before attempting either, rather than attempting and handling the failure

### 2.5 Shoonya

Still the weakest row. The rebuilt documentation site does not publish a GTT endpoint page, and
`manual-login-oauth` returns 403 to automated fetch. Round 1's finding stands — GTT exists over
REST but is absent from the Python SDK — and the endpoint and alert-type enum remain
`❓ UNVERIFIED`. D-129's decision (fall back to a DAY limit order on Shoonya if GTD is
unavailable) therefore remains in force as the safe default. Raised as **Q-271**.

### 2.6 GTT summary

| | Upstox | Dhan | Zerodha | Groww | Shoonya |
|---|---|---|---|---|---|
| Endpoint verified | ✅ | ✅ | ✅ | ✅ | ❌ |
| Max validity | 1 year | not stated | `expires_at` returned | **1 year (forced)** | ❓ |
| Order type on trigger | LIMIT (forced) | LIMIT or MARKET | **LIMIT only** | LIMIT / SL | ❓ |
| OCO available | ✅ `MULTIPLE` | ✅ `OCO` | ✅ `two-leg` | ✅ `OCO` | ❓ |
| **Own-order identification** | ❓ | ✅ `correlationId` (30 ch) | ❌ **none until fired** | ✅ `reference_id` (8–20) | ❓ |
| Static IP required | ✅ | ✅ | ❓ | ❓ | ✅ |
| Special prerequisite | **EDIS for SELL** | — | `last_price` at placement | — | — |

---

## 3. Order tagging and idempotency — better than expected

ATOM needs two things from every adapter: a way to recognise its own orders, and a way to make
a retried placement safe. Three brokers give both natively.

| Broker | Field | Constraint | Idempotent? |
|---|---|---|---|
| **Zerodha** | `tag` | alphanumeric, **max 20 chars**; returned in the order book as `tag` and `tags[]` | No — but `guid` is described as a "request id to avoid order duplication" |
| **Groww** | `order_reference_id` | **required**, 8–20 alphanumeric, ≤ 2 hyphens | **Yes** — duplicate → `GA007`; and `GET /v1/order/status/reference/{id}` looks an order up by ATOM's own ID |
| **Dhan** | `correlationId` | max 30 chars | Not stated |
| **Upstox** | `tag` on place order; `X-Algo-Name` header | — | — |
| **Shoonya** | `remarks` on `place_order` | — | — |

**Groww's model is the one to normalise towards.** A required, ATOM-generated reference that
(a) rejects duplicates and (b) can be used to *look up* an order means a network timeout during
placement is fully recoverable: ATOM retries with the same reference and either places the order
or learns it already exists. On brokers without that guarantee the adapter must fall back to
"query the order book by tag before retrying", which is a race, not a guarantee.

The canonical model should carry a single `client_ref` field, generated by ATOM, that each
adapter maps to its broker's field (truncating to 20 characters so one format works everywhere).

---

## 4. Rate limits — all five now verified

### Upstox
[Source](https://upstox.com/developer/api-documentation/rate-limiting/) — explicitly aligned to
NSE circular of 5 May 2025.

| Category | /sec | /min | /30 min |
|---|---|---|---|
| Order placement (place, modify, cancel, multi, GTT) — **regular algos** | 10 | 500 | 2,000 |
| Order placement — **SEBI-registered algos** | 50 | 500 | 2,000 |
| Standard APIs (holdings, positions, funds, candles) | 50 | 500 | 2,000 |
| TOTP login | 1 | 10 | 60 |

### Dhan
[Source](https://dhanhq.co/docs/v2/)

| | /sec | /min | /hour | /day |
|---|---|---|---|---|
| Order APIs | 10 | 250 | 1,000 | 7,000 |
| Data APIs | 5 | — | — | 100,000 |
| **Quote APIs** | **1** | unlimited | unlimited | unlimited |
| Non-trading | 20 | unlimited | unlimited | unlimited |

Plus: **order modifications capped at 25 per order.**

### Groww
[Source](https://groww.in/trade-api/docs/curl)

| Type | /sec | /min |
|---|---|---|
| Authentication | 5 | 30 |
| Orders | 10 | 250 |
| Live Data | 10 | 300 |
| Non Trading (status, lists, positions, holdings, margin) | 20 | 500 |

Limits apply **per type, not per endpoint** — exhausting one endpoint throttles every endpoint
in its group.

### Shoonya
[Source](https://shoonya.com/api-documentation/rate-limits) — deliberately soft:

| Category | Limit |
|---|---|
| Order place/modify/cancel | ~10 req/sec, burst-limited |
| Market data (REST) | ~1 req/sec **per instrument** |
| WebSocket | 1 connection per session |

Throttling returns `{"stat":"Not_Ok","emsg":"Rate_Limited: ..."}`. The docs warn that "exact
numeric ceilings are enforced server-side and may be tuned without notice — treat the table
above as design guidance, not a contract".

### Zerodha
10 req/s per API key; 5,000 orders/day; 400/min (round 1, unchanged).

### What this confirms and what it changes

D-148 ("rate limits do not affect us") **holds for orders** — ATOM places a handful per account
per day against ceilings of 7,000–10,000.

It does **not** hold for quotes. Dhan's **1 quote/second** and Shoonya's **1/second per
instrument** mean pricing a 60-ETF universe from either broker takes a full minute. Combined
with Shoonya's explicit instruction to prefer WebSocket over polling, this settles Q-044 on
hard evidence: **market data comes from one provider for all accounts, not per broker.**

Shoonya's "may be tuned without notice" clause also means the adapter needs a `Rate_Limited`
branch with exponential backoff and jitter regardless of headroom — their docs supply the
pattern, and ATOM should follow it rather than assume its own volume exempts it.

---

## 5. Charges and ledger — the round's best news for reporting

ATOM needs actual, not estimated, charges (D-105, the charges-contrast view). Dhan settles it.

### Dhan — per-trade charges, itemised, from the API

[Source](https://dhanhq.co/docs/v2/statements/) — `GET /v2/trades/{from-date}/{to-date}/{page}`

Each trade returns, alongside price and quantity:

| Field | Meaning |
|---|---|
| `sebiTax` | SEBI turnover charges |
| `stt` | Securities Transaction Tax |
| `brokerageCharges` | Dhan's brokerage |
| `serviceTax` | GST |
| `exchangeTransactionCharges` | Exchange transaction charge |
| `stampDuty` | Stamp duty |

Also `isin`, `exchangeTradeId`, `exchangeOrderId` and `instrument` — so a fill can be reconciled
to the exchange record and to the instrument master by ISIN, not by symbol.

**This means the charges-contrast view has a ground truth on Dhan, not a model.** ATOM can show
estimated-vs-actual per fill and per component, which is exactly what the brief asked for. Where
other brokers do not expose this, the view degrades to estimate-only — and that degradation must
be visible in the UI, not silent.

### Dhan — ledger

`GET /v2/ledger?from-date=&to-date=` returns `narration`, `voucherdate`, `exchange`,
`voucherdesc`, `vouchernumber`, `debit`, `credit`, `runbal`.

`runbal` (running balance) is the reconciliation anchor for the cost-of-capital model: ATOM's
computed `principal_outstanding` can be checked against the broker's own running balance rather
than only against its internal ledger. `narration` = `"FUNDS WITHDRAWAL"` with
`voucherdesc` = `"PAYBNK"` is how a withdrawal appears — which is what D-078 models as a
repayment to the firm. The classifier needs a `voucherdesc` → ATOM event mapping table.

### Groww — holdings carry the lock/pledge breakdown

[Source](https://groww.in/trade-api/docs/curl/portfolio) — `GET /v1/holdings/user` returns
`quantity`, `average_price`, `pledge_quantity`, `demat_locked_quantity`,
`groww_locked_quantity`, `repledge_quantity`, **`t1_quantity`**, `demat_free_quantity`,
`corporate_action_additional_quantity`, `active_demat_transfer_quantity`.

This matters for `HOLDINGS-ATTRIBUTION.md`. The reconciliation identity

```
broker_quantity = Σ open ATOM lots + excluded_quantity + unattributed_quantity
```

needs to know **which** `broker_quantity` it means. A T1 quantity is owned but not yet
deliverable; a pledged quantity cannot be sold at all. Selling against either produces a
rejection ATOM would have to explain after the fact. The sellable figure is
`demat_free_quantity`, not `quantity` — and the attribution document should say so explicitly
rather than leave "broker quantity" undefined. Raised as **Q-272**.

### Zerodha — trades

`GET /trades` returns `trade_id`, `order_id`, `exchange_order_id`, `average_price`, `quantity`,
`fill_timestamp` — **per fill**, which is what D-163's per-fill lot creation needs. No charge
breakdown at trade level; charges come from the separate console reports. Zerodha's live
position on trade-level charges via API remains `❓ UNVERIFIED`.

### Groww and Shoonya — charges

No per-trade charge breakdown found in either vendor's order or trade documentation. Remains
`❓ UNVERIFIED`; assume estimate-only until proven otherwise.

---

## 6. Order placement — the canonical fields, per broker

What the adapter must map. Only fields ATOM actually uses are shown.

| Concept | Upstox | Dhan | Zerodha | Groww | Shoonya |
|---|---|---|---|---|---|
| Endpoint | `POST /v3/order/place` | `POST /v2/orders` | `POST /orders/:variety` | `POST /v1/order/create` | `POST /PlaceOrder` |
| Instrument | `instrument_token` `NSE_EQ\|INE669E01016` | `securityId` (Dhan scrip ID) | `tradingsymbol` + `exchange` | `trading_symbol` + `exchange` | `tsym` (`CANBK-EQ`) + `exch` |
| Side | `transaction_type` BUY/SELL | `transactionType` BUY/SELL | `transaction_type` BUY/SELL | `transaction_type` | `buy_or_sell` **B/S** |
| Qty | `quantity` | `quantity` | `quantity` | `quantity` | `qty` (string) |
| Price | `price` | `price` | `price` | `price` | `prc` (string) |
| Order type | `order_type` | `orderType` | `order_type` | `order_type` | `price_type` **LMT/MKT/SL-LMT** |
| Product (delivery) | `product` = **`D`** | `productType` = **`CNC`** | `product` = **`CNC`** | `product` = **`CNC`** | `product_type` = **`C`** |
| Validity | `validity` DAY/IOC | `validity` DAY/IOC | `validity` DAY/IOC/TTL | `validity` | `retention` DAY |
| ATOM's own ref | `tag` | `correlationId` | `tag` (≤20) | `order_reference_id` (**required**) | `remarks` |

**Five different instrument identifiers.** ISIN is the only key all five can be reconciled
through (Dhan returns `isin` on trades, Groww returns `isin` on holdings and trades). The
instrument master must therefore key on **ISIN** with a per-broker identifier column — which is
what `DATABASE-SCHEMA.md` already does, and this confirms it was the right call.

**Zerodha's `variety` is a path segment, not a body field** — `/orders/regular`,
`/orders/amo`, `/orders/iceberg`. ATOM uses `regular` only, but the adapter must build the URL,
not the payload, from it.

**Zerodha order statuses are not a flat enum.** Beyond `OPEN` / `COMPLETE` / `CANCELLED` /
`REJECTED` there are transient states — `PUT ORDER REQ RECEIVED`, `VALIDATION PENDING`,
`OPEN PENDING`, `MODIFY VALIDATION PENDING`, `TRIGGER PENDING`, `CANCEL PENDING`,
`AMO REQ RECEIVED` — and the docs warn "there may be other values as well". The adapter's
status mapping must have a **default branch that treats unknown states as in-flight**, never as
terminal. Mapping an unrecognised status to "failed" would make ATOM re-place an order that is
about to fill.

Zerodha also returns `status_message` and `status_message_raw` on rejection (e.g. *"Insufficient
funds. Required margin is 95417.84 but available margin is 74251.80"*). D-052's "let the order
fail if money is not present" is satisfied with a human-readable reason to log.

---

## 7. Things found that ATOM had not considered

1. **Dhan's 7-day IP lock** (§0.1) — turns an IP change from an incident into a week-long
   outage. Elastic IP is now mandatory, not preferred.
2. **Upstox EDIS for sell GTTs** (§2.1) — a one-time manual flow that gates ATOM's entire sell
   side on Upstox.
3. **Zerodha's 6 AM token expiry** (§1.3) — a token generated too early is dead before market
   open.
4. **Zerodha GTTs carry no identifier until they fire** (§2.3) — ATOM's database is the only
   link to its own orders.
5. **Groww's mandatory `order_reference_id`** (§3) — a free idempotency key that the canonical
   model should generalise.
6. **Groww's `t1_quantity` / `demat_free_quantity` split** (§5) — "broker quantity" in the
   attribution identity is ambiguous and must be pinned down.
7. **MCX API trading disabled at Upstox** — noted for completeness; ATOM trades NSE-listed
   commodity ETFs in the CASH segment, so it is unaffected. Worth recording because a reader of
   `SECTOR-BUCKETS.md` might reasonably assume otherwise.
8. **Dhan's `GET /v2/profile` returns `tokenValidity`, `ddpi`, `mtf`, `dataPlan`** (§1.2) — a
   better D-170 probe than the holdings call, because it says *why* an account is unusable.
9. **Dhan's `givenPowerOfAttorney` / DDPI flag** on every token response — DDPI status
   determines whether sells need per-trade authorisation. Should be captured at onboarding.

---

## 8. Still unverified after round 2

| Item | Broker | Question |
|---|---|---|
| Algo ID applicability at ATOM's volume | All five | **Q-268** |
| Token lifetime | Shoonya | **Q-269** |
| GTT endpoint + alert-type enum | Shoonya | **Q-271** |
| Per-trade charge breakdown | Zerodha, Groww, Shoonya | Q-273 |
| IP whitelisting procedure | Zerodha, Groww | Q-274 |
| Whether a GTT survives its holding being sold by other means | All five | Q-186 (open since round 1) |
| Data API cost | Dhan (charged), Groww (subscription) | Q-275 |

---

## 9. Sources

All fetched 2026-09-24.

- Upstox — [authentication](https://upstox.com/developer/api-documentation/authentication/) ·
  [place GTT](https://upstox.com/developer/api-documentation/place-gtt-order/) ·
  [rate limiting](https://upstox.com/developer/api-documentation/rate-limiting/) ·
  [regulatory changes](https://community.upstox.com/t/important-update-regulatory-changes-for-api-and-algo-trading-are-now-live/14874)
- Dhan — [introduction](https://dhanhq.co/docs/v2/) ·
  [authentication](https://dhanhq.co/docs/v2/authentication/) ·
  [forever orders](https://dhanhq.co/docs/v2/forever/) ·
  [statements](https://dhanhq.co/docs/v2/statements/)
- Zerodha — [introduction](https://kite.trade/docs/connect/v3/) ·
  [user](https://kite.trade/docs/connect/v3/user/) ·
  [orders](https://kite.trade/docs/connect/v3/orders/) ·
  [GTT](https://kite.trade/docs/connect/v3/gtt/)
- Groww — [introduction](https://groww.in/trade-api/docs/curl) ·
  [orders](https://groww.in/trade-api/docs/curl/orders) ·
  [smart orders](https://groww.in/trade-api/docs/curl/smart-orders) ·
  [portfolio](https://groww.in/trade-api/docs/curl/portfolio)
- Shoonya — [introduction](https://shoonya.com/api-documentation) ·
  [API structure](https://shoonya.com/api-documentation/api-structure) ·
  [rate limits](https://shoonya.com/api-documentation/rate-limits) ·
  [IP whitelisting](https://shoonya.com/api-documentation/ip-whitelisting) ·
  [algo compliance](https://shoonya.com/api-documentation/algo-compliance)
