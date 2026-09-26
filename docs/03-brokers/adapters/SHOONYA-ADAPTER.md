# Shoonya (Finvasia / Noren) — Adapter Specification

**Status:** 🟠 Complete for what is published — **GTT surface still unpublished** (Q-271)
**Order of work:** 5th of 5, deliberately last (D-140)
**Pages read:** introduction · API structure · place order · holdings · rate limits ·
IP whitelisting · algo compliance · quick start

> **Why Shoonya is last, and why that was right.** It has the thinnest documentation of the five,
> no idempotency field of any kind, no charges surface, no ledger, a rebuilt OAuth flow whose
> token lifetime is still unpublished, and **no GTT endpoint documentation** — the one operation
> ATOM's sell side depends on. It also has two places where its own documentation contradicts
> itself (§12.1).

---

## 1. Capability profile

```python
SHOONYA = BrokerCapabilities(
    broker_code               = "SHOONYA",

    supports_gtt              = False,         # 🔴 unverified → DAY-limit fallback (D-129/D-164)
    gtt_max_validity_days     = None,
    gtt_carries_client_ref    = False,
    gtt_order_type            = "LIMIT",

    client_ref_field          = "remarks",     # free text, no documented limit
    client_ref_max_len        = 20,            # canonical cap
    client_ref_is_idempotent  = False,         # 🔴 no client-order-id field at all
    lookup_by_client_ref      = False,         # must scan the order book

    provides_trade_charges    = False,
    provides_charge_preview   = False,
    provides_ledger           = False,
    provides_free_quantity    = True,          # derived from 7 fields — §6.1

    requires_static_ip        = True,
    static_ip_scope           = "ALL_CALLS",   # 🟢 gates login itself — fails early
    static_ip_lock_days       = 0,

    token_probe_endpoint      = "HOLDINGS",    # no profile endpoint
    token_revocable           = True,          # POST /Logout

    requires_sell_authorisation = False,       # POA-dependent — see npoadqty, §6.1
    sell_authorisation_scope    = "NONE",

    orders_per_second         = 10,
    quote_batch_size          = None,          # ~1 req/sec per instrument
)
```

**`supports_gtt = False` is a deliberate conservative default, not a finding.** Round 1 confirmed
from Shoonya's FAQ that GTT exists over REST but is absent from the Python SDK; the rebuilt
documentation site publishes no GTT page at all. Until the endpoint and its alert-type enum are
verified (Q-271), the adapter declares no GTT capability and ATOM falls back to placing a plain
**DAY limit sell each morning**, which the broker cancels each evening (D-129, D-164).

That fallback has a real cost worth naming: **positions on Shoonya are unprotected on non-run
days**, which is precisely the gap GTT was reinstated to close (D-063). Shoonya should therefore
not hold positions ATOM considers materially at risk until Q-271 is resolved.

---

## 2. Wire basics

| | |
|---|---|
| REST base | `https://api.shoonya.com/NorenWClientAPI/` |
| WebSocket | `wss://api.shoonya.com/NorenWSAPI/` |
| Historical | `https://api.shoonya.com/chartapi/getdata/` |
| OAuth authorize | `https://api.shoonya.com/OAuthlogin/authorize/oauth?client_id=…` |
| Body | `jData=<JSON payload>` — **plus `jKey=<AccessToken>` on order endpoints** ⚠️ §12.1 |
| Success | `{"stat": "Ok", …}` |
| Failure | `{"stat": "Not_Ok", "emsg": "…"}` — **with HTTP 200** 🔴 §12.2 |

Field names are abbreviated (`tsym`, `qty`, `prc`, `trgprc`, `prd`, `prctyp`, `trantype`, `ret`)
and **numerics are sent as strings inside the JSON**, not as JSON numbers.

---

## 3. Session lifecycle — OAuth 2.0 (the legacy flow is gone)

```
GET  https://api.shoonya.com/OAuthlogin/authorize/oauth?client_id=<CLIENT_ID>
   → operator authenticates, redirect carries `code`
checksum = SHA256(client_id + secret_code + auth_code)
gen_access_token(uid=<USER_ID>, code=<auth_code>, appkey=checksum)
   → susertoken
```

`Client ID` and `Secret Code` both come from the **API Key Generation** screen in the trading
account — the same screen that registers the static IP (§12.3).

This is the authorize-and-paste pattern (D-183), same shape as Upstox: the operator transports the
code by hand, so no registered redirect handler is needed.

**Token lifetime remains unpublished (Q-269)** — the `manual-login-oauth` page returns 403 to
automated fetch. Under D-170 this costs nothing operationally: validity is **tested by probing**,
never computed from a documented lifetime. It does mean ATOM cannot warn the operator in advance
that a token is about to expire.

Probe: `POST /Holdings` (no profile endpoint exists). Revoke: `POST /Logout`.

---

## 4. Instrument master

`Symbol Master` — a per-exchange download, referenced throughout the docs but whose URL and
column list are not published on the pages read. `tsym` format is `RELIANCE-EQ` (symbol + `-EQ`
series suffix), and Shoonya provides a `SearchScrip` endpoint to resolve a symbol to a `tsym`.

🔴 **ISIN availability in the Symbol Master is unverified (Q-306).** This matters because
holdings return **no ISIN either** (§5.1) — so if the master also lacks it, Shoonya is the one
broker where ATOM has *no* ISIN path at all and instrument resolution must run entirely through
the curated reference set on `(symbol, exchange)`, as Zerodha does (D-187) but without the
holdings cross-check that validates Zerodha's mapping.

⚠️ Shoonya's own guidance: "Validate `tsym` against a freshly-fetched Symbol Master immediately
before placing F&O orders — don't cache symbols across expiries." ATOM trades only cash-segment
ETFs, where symbols are stable, so the daily sync is sufficient. Recorded because the warning is
explicit.

⚠️ Symbols need URL encoding — the docs call out `M&M` as an example. ATOM's ETF symbols are
alphanumeric, but the adapter encodes unconditionally.

---

## 5. Inbound mappings

### 5.1 Holdings — `POST /Holdings`

```json
[{"stat":"Ok",
  "exch_tsym":[{"exch":"NSE","token":"22","tsym":"ABB-EQ"}],
  "holdqty":"20","colqty":"0","btstqty":"0","btstcolqty":"0",
  "usedqty":"0","upldprc":"1800.00"}]
```

| Shoonya field | → Canonical | Note |
|---|---|---|
| `exch_tsym[]` | *(join key)* | ⚠️ **an array** — §12.4 |
| `holdqty` | *(input)* | Core demat holding |
| `dpqty` | *(input)* | DP holding quantity |
| `npoadqty` | *(input)* | **Non-POA display quantity** — see below |
| `btstqty` / `btstcolqty` | *(input)* | Buy-today-sell-tomorrow |
| `colqty` / `brkcolqty` | `pledged_quantity` | Collateral |
| `unplgdqty` | *(input)* | Unpledged |
| `benqty` | *(input)* | Beneficiary |
| `usedqty` | *(input)* | **Already used/sold today** |
| `upldprc` | `average_price` | "Average cost price uploaded" |
| — | `isin` | 🔴 **not returned** |
| — | `last_price` | ❌ not returned |

**`npoadqty` is the POA signal.** The docs describe it as "relevant when POA isn't set up on the
account" — so a non-zero `npoadqty` diverging from `dpqty` indicates the account lacks POA/DDPI,
which is the same condition that makes Zerodha's sell authorisation a daily step
(`ZERODHA-ADAPTER.md` §12.2). Captured into `broker_flags` at onboarding.

### 5.2 Orders — `POST /OrderBook`

`norenordno` is the order id. Statuses per §8.

### 5.3 Charges and ledger — neither exists

Nothing in the SDK or the published REST surface exposses a ledger, contract note or charge
breakdown. So on Shoonya:

- `atom.charge` carries **only** `source = 'COMPUTED'` rows. The charges-contrast view (D-024,
  D-179) degrades to **computed-only with no broker counterpart at all** — the weakest of the
  five, and the UI must say so rather than showing an empty broker column that reads as zero.
- `atom.cash_ledger` is populated from ATOM's own fills plus manual statement upload.

The fallback of manual statement upload (Q-238) is therefore load-bearing on Shoonya, not
optional.

---

## 6. Stage-3 normalisation

### 6.1 `free_quantity` — 🟢 Shoonya publishes the formula

Uniquely among the five, Shoonya gives the arithmetic explicitly:

```
Valuation = btstqty + holdqty + brkcolqty + unplgdqty + benqty + max(npoadqty, dpqty) − usedqty
Salable   = btstqty + holdqty + unplgdqty + benqty + dpqty − usedqty
```

```python
total_quantity = btstqty + holdqty + brkcolqty + unplgdqty + benqty \
                 + max(npoadqty, dpqty) - usedqty          # "Valuation"
free_quantity  = btstqty + holdqty + unplgdqty + benqty + dpqty - usedqty   # "Salable"
```

Seven fields for the sellable figure — the most derived of the five, against Dhan's and Groww's
single field. The difference between the two formulas is exactly `brkcolqty` (broker collateral,
owned but pledged) and `max(npoadqty, dpqty)` versus `dpqty`.

Shoonya's own instruction is worth quoting because it is D-182 in the vendor's words: "Use the
salable-quantity formula above before placing a sell order against holdings — **don't sell against
raw `holdqty`**, since pledged/used portions aren't available to trade."

⚠️ All values arrive as **strings** and some fields are absent from the sample response
(`dpqty`, `npoadqty`, `brkcolqty`, `unplgdqty`, `benqty` are documented but not shown). The
adapter coerces each with a default of `0` and logs when a documented field is missing — silently
defaulting a missing `usedqty` to zero would **overstate** the sellable quantity, which is the
dangerous direction.

### 6.2 `client_ref` — a race, and the vendor says so

Shoonya has **no client-order-id field**. Its own best practice:

> "On a network timeout, don't assume the order failed. Shoonya has no dedicated
> idempotency/client-order-ID field, so tag every order with a unique `remarks` value at send
> time, then reconcile against Order Book by matching `tsym` + `qty` + `remarks` before deciding
> whether to resend."

That is exactly the fallback `ADAPTER-ENGINE.md` §3 described as "a race, not a guarantee" — and
here it is the vendor's prescribed approach. The adapter implements it: `client_ref` → `remarks`,
and recovery scans the order book on `(tsym, qty, remarks)`.

**The race is real and must be documented for the operator**, not hidden: if a timeout occurs
*and* the order book has not yet reflected the order, ATOM cannot distinguish "not placed" from
"placed, not yet visible". ATOM's rule in that case is **do not re-place** — leave the intent as
`INTENT`, halt the account, and let the next run reconcile. A duplicate buy is worse than a missed
one.

### 6.3 Tradability

No per-instrument buy/sell permission flag is published (contrast Groww's `buy_allowed`, Dhan's
`BUY_SELL_INDICATOR`, Upstox's suspended file). Pre-flight tradability checks are **not available**
on Shoonya; a rejection is the only signal. Q-307.

---

## 7. Outbound mappings

### 7.1 `OrderIntent` → `POST /PlaceOrder`

| Canonical | Shoonya | Value |
|---|---|---|
| — | `uid` / `actid` | account id, both required |
| — | `exch` | `NSE` |
| `instrument_id` → resolve | `tsym` | e.g. `GOLDBEES-EQ` (URL-encoded) |
| `quantity` | `qty` | **string** |
| `limit_price` | `prc` | **string** |
| `product` | `prd` | **`C`** (CNC) |
| `order_kind` | `prctyp` | **`LMT`** |
| `side` | `trantype` | **`B`** / **`S`** |
| `validity` | `ret` | `DAY` |
| `client_ref` | `remarks` | free text |
| — | **`ordersource`** | **`API`** — required |
| — | `algo_id` | **omitted** (§12.5) |

Not sent: `trgprc` (SL-LMT only), `dscqty`.

🟢 **`MKT` orders are rejected outright** — "only `LMT` and `SL-LMT` are accepted". Shoonya
enforces at the broker what D-174 decided at the strategy level, and its own advice matches
ATOM's: "Since `MKT` isn't supported, price `LMT` orders with a small buffer beyond the current
LTP for reliable fills."

`CO` and `BO` are also unavailable as `prd` values — irrelevant, ATOM uses `C` only.

### 7.2 GTT — not implemented

`supports_gtt = False` until Q-271 resolves. The engine's DAY-limit fallback path handles Shoonya
(D-129, D-164): a plain `LMT` sell placed each morning at the tranche target, cancelled by the
broker each evening.

### 7.3 Cancel

`POST /CancelOrder` with `norenordno`. Q-185 (synchronous or must re-poll?) unverified for
Shoonya — the adapter re-polls the order book regardless, which is correct under either answer.

---

## 8. Status map

Shoonya publishes lifecycle **states** in prose rather than a code enum:

| State | → Canonical |
|---|---|
| `COMPLETE` | `FILLED` |
| Partially Filled | `PARTIAL` |
| `OPEN` | `PLACED` |
| Pending Validation | `IN_FLIGHT` |
| Trigger Pending | `IN_FLIGHT` |
| `REJECTED` | `REJECTED` |
| `CANCELED` / `CANCELLED` | `CANCELLED` |
| **anything else** | **`IN_FLIGHT`** |

⚠️ The exact string values returned by `OrderBook` are not tabulated in the documentation, only
described. The D-180 default branch therefore carries more weight here than on any other broker,
and the adapter logs every unrecognised status string once so the map can be completed from
observation. Q-308.

⚠️ "Cancelled by client, session logout, or **EOD (for DAY orders)**" — a DAY order cancelled at
end of day is indistinguishable from an operator cancellation. With the GTT fallback placing DAY
sells daily, ATOM must treat an overnight `CANCELLED` on a DAY sell as **expected**, not as an
anomaly.

---

## 9. Error map

Shoonya returns prose in `emsg`, not codes. This is the coarsest error surface of the five.

| `emsg` pattern | → Canonical | Behaviour |
|---|---|---|
| `Rate_Limited: …` | `RateLimitError` | 🟢 the one machine-readable prefix — backoff with jitter |
| `Session Expired` / invalid `jKey` | `AuthError` | Halt account |
| `RMS:Margin Exceeds` | `InsufficientFundsError` | Record verbatim, continue (D-052) |
| `Invalid Symbol` | `ValidationError` | Instrument-resolution bug |
| `Invalid Quantity` | `ValidationError` | Bug |
| `Price Outside Circuit Limit` | `ValidationError` | Pricing bug — fetch circuit band first |
| `Freeze Quantity Exceeded` | `ValidationError` | Not reachable for ETF quantities |
| Auth/IP failure at login | `IpBlockedError` | 🔴 Halt everything, never retry (§12.3) |
| anything else | `UnknownError` | Halt, preserve `emsg` |

⚠️ **Only `Rate_Limited` has a documented machine-readable form.** Everything else is
string-matched against prose, which will break when Shoonya rewords a message. The adapter keeps
`emsg` verbatim in `reject_reason` (D-042), treats an unmatched message as `UnknownError` — which
**halts rather than retries** — and logs it for the map to be extended. Guessing is worse than
halting. Q-309.

---

## 10. Rate limits

| Category | Limit |
|---|---|
| Order place / modify / cancel | ~10 req/sec, burst-limited, per user |
| Market data (REST) | **~1 req/sec per instrument** |
| WebSocket connect | 1 connection per session |
| Historical data | lower burst allowance |

> "Exact numeric ceilings are enforced server-side and may be tuned without notice — treat the
> table above as design guidance, not a contract."

Shoonya prescribes **exponential backoff with jitter**, and warns that a fixed retry interval
"synchronizes retries across your own threads and makes bursts worse". The adapter implements it
regardless of ATOM's low volume, because the ceilings can move without notice.

**1 req/sec *per instrument*** is the tightest data limit of the five — pricing a 60-ETF universe
from Shoonya would take a minute. Third independent argument for D-044.

---

## 11. Order update feed

A WebSocket order-update feed exists and Shoonya recommends it over polling. Not used in v1
(D-053).

---

## 12. Broker-specific hazards

### 12.1 🔴 Shoonya's own documentation contradicts itself, twice

Both contradictions are between the **API Structure** page and the **Place Order** page, and both
would produce a failure that looks like something else.

| | API Structure page | Place Order page |
|---|---|---|
| **Token transport** | "the token is **not** repeated inside the request body — only in the header" · `Authorization: Bearer <AccessToken>` | `jData=<JSON>&jKey=<AccessToken>` — **token in the body** |
| **Content-Type** | `text/plain` | `application/x-www-form-urlencoded` |

The holdings page also uses the `jKey`-in-body, form-urlencoded form, which suggests the Place
Order page reflects current reality and the API Structure page describes the intended OAuth-era
convention.

**The adapter sends both**: `Authorization: Bearer` header *and* `jKey` in the body, with
`Content-Type: application/x-www-form-urlencoded`. Sending a token twice is harmless; sending it
in the wrong place fails as an auth error that looks like an expired token and would send someone
hunting the session logic instead of the transport. Raised as **Q-310** to confirm with API
support.

This is the clearest illustration of why Shoonya is scheduled last.

### 12.2 🔴 HTTP 200 on rejection

> "The OMS returns `HTTP 200` for both accepted and rejected orders — rejection is signalled in
> the JSON body via `stat`, not the HTTP status code. **Always parse `stat`; never treat a 200 as
> confirmation of order placement.**"

Every response is checked for `stat == "Ok"` before any other field is read. An adapter that
branches on HTTP status would record rejected orders as placed — and then ATOM's books would
claim holdings it does not have, which the attribution reconciliation would surface the next day
as a negative residual and a blocked run. A confusing, day-late failure from a one-line mistake.

### 12.3 🟢 Static IP gates login itself — which is the good kind of strict

> "Before you can complete the OAuth login flow **or call any endpoint**, you need to whitelist
> the static IP."

Unlike Dhan, where whitelisting gates only order placement (`DHAN-ADAPTER.md` §12.2), a wrong
egress IP on Shoonya fails at **login** — loudly, immediately, before any order is attempted.
`static_ip_scope = "ALL_CALLS"` is therefore *safer* than `ORDERS_ONLY`, even though it sounds
stricter.

Primary + Backup IP, IPv4 or IPv6, set on the API Key Generation screen. The screen also carries
an **"Applicable for more than 10 orders per second"** checkbox which Shoonya states does **not**
raise throughput without an exchange-approved Algo ID. ATOM leaves it unchecked.

### 12.4 ⚠️ `exch_tsym` is an array

"A holding can map to more than one exchange/token pair for dually-listed scrips." So a single
holdings row may carry both an NSE and a BSE token. ATOM resolves the **NSE** entry and, if none
exists, blocks that instrument's reconciliation row rather than picking arbitrarily.

### 12.5 🟢 `algo_id` is explicitly optional — Shoonya's own pages disagree, in ATOM's favour

The **Place Order** page documents `algo_id` as:

> "Exchange-approved Algo ID. Mandatory for orders placed under a registered algo strategy per
> SEBI's algo trading framework; **omit for manual/non-algo orders**."

This **directly contradicts** Shoonya's own SEBI Algo ID Framework page, which states that every
API order — "not just orders from registered algo strategies" — requires an empanelled Algo ID.

The operator verified independently that no Algo ID is required (D-181). **Shoonya's place-order
page agrees with the operator; only its compliance page overstates it.** ATOM omits `algo_id`
entirely, and this contradiction is the documentary support for that choice.

### 12.6 ⚠️ Strings everywhere

`qty`, `prc`, and every holdings quantity arrive and depart as strings. Decimal parsing and
serialisation are explicit, and `Decimal` is used throughout rather than float.

---

## 13. Open questions

| ID | Question | Blocks |
|---|---|---|
| **Q-271** 🔴 | GTT endpoint, payload and alert-type enum — still unpublished. Until resolved Shoonya has **no GTT**, so positions are unprotected on non-run days | Shoonya sell side |
| **Q-310** 🔴 | Token in header, body, or both? And `text/plain` or form-urlencoded? Two pages disagree (§12.1) | Every Shoonya call |
| Q-306 | Does the Symbol Master carry ISIN? Holdings do not, so if the master also lacks it Shoonya has no ISIN path at all | Instrument resolution |
| Q-269 | OAuth access-token lifetime — page returns 403 to automated fetch | Operator warning only (D-170 probes) |
| Q-307 | Any per-instrument buy/sell permission flag? None found | Pre-flight tradability |
| Q-308 | Exact `OrderBook` status strings — described in prose, never tabulated | Status mapping |
| Q-309 | Are error codes available anywhere, or is `emsg` prose the only surface? | Error mapping robustness |
| Q-238 | Any ledger or charges surface at all? None found — manual upload becomes load-bearing | Charges contrast, cost of capital |
| Q-185 | Is cancellation synchronous, or must the order book be re-polled? | Cancel-all-first step |

---

## 14. Sources

[introduction](https://shoonya.com/api-documentation) ·
[API structure](https://shoonya.com/api-documentation/api-structure) ·
[quick start](https://shoonya.com/api-documentation/quick-start) ·
[place order](https://shoonya.com/api-documentation/place-order) ·
[holdings](https://shoonya.com/api-documentation/holdings) ·
[rate limits](https://shoonya.com/api-documentation/rate-limits) ·
[IP whitelisting](https://shoonya.com/api-documentation/ip-whitelisting) ·
[algo compliance](https://shoonya.com/api-documentation/algo-compliance)
