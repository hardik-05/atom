# Shoonya (Finvasia) — Broker Adapter Specification

**Status:** 🟠 SDK fully inspected · **auth section rewritten 2026-09-24 — Shoonya migrated to OAuth 2.0** · GTT still unverified
**Role in ATOM:** trading account
**Priority:** Phase E — **last, deliberately** (D-140)
**Source:** `NorenRestApiPy` 0.0.22 (PyPI) for the SDK audit;
[Shoonya API documentation](https://shoonya.com/api-documentation) fetched 2026-09-24 for
everything else. Full detail in [`API-REFERENCE-VERIFIED.md`](API-REFERENCE-VERIFIED.md).

---

## 0. ⚠️ Shoonya rebuilt its API — the legacy Noren flow is gone

The documentation this file was first written against described the legacy `QuickAuth` login
(user id + SHA-256 password + TOTP + vendor code + API secret, with the session token echoed in
**every request body**). **That is no longer how Shoonya works.** As of the documentation fetched
2026-09-24:

| | Legacy (what this file assumed) | Current (verified) |
|---|---|---|
| Auth model | Noren `QuickAuth` | **OAuth 2.0** |
| SDK package | `NorenRestApiPy` | **`NorenRestApiOAuth`** |
| Token transport | `jKey` in every request body | **`Authorization: Bearer <AccessToken>` header only** |
| Authorize URL | — | `https://api.shoonya.com/OAuthlogin/authorize/oauth?client_id=...` |
| Token exchange | `login()` | `gen_access_token(uid, code, appkey=checksum)` where<br>`checksum = SHA-256(client_id + secret_code + auth_code)` |

Base URLs: REST `https://api.shoonya.com/NorenWClientAPI/` · WebSocket
`wss://api.shoonya.com/NorenWSAPI/` · historical `https://api.shoonya.com/chartapi/getdata/`.

Request format is unchanged and still unusual — `Content-Type: text/plain` with a single
`jData=<JSON>` body field, abbreviated field names (`tsym`, `qty`, `prc`, `trgprc`), and
**numerics sent as strings inside the JSON**. Every response carries `stat` = `Ok` / `Not_Ok`,
with `emsg` on failure.

**The SDK audit in §2 below is still accurate for the legacy package and its conclusions still
hold** (no GTT, no sessions, so no per-instance proxy) — but the adapter will be written against
the OAuth REST surface, which is what D-056b already decided.

## 1. Why Shoonya is hardest, and last

Three independent problems, each verified:

1. **No GTT in the SDK.** The complete method list contains `place_order`, `modify_order`,
   `cancel_order`, `exit_order` — and **nothing for GTT or alerts**. ATOM's sell logic is
   GTT-based (D-063), so the SDK cannot express the core operation.
2. **Per-instance proxy is impossible.** **26 module-level `requests.post` calls, zero
   sessions** (D-139). Nothing to attach a proxy to.
3. **Thinnest documentation of the five**, with unusual semantics (alert types such as
   `LTP_A_O` for "LTP above") rather than a conventional GTT payload.

None of these blocks ATOM — raw HTTP over the REST API solves 1 and 2 — but each costs research
time, which is why it goes last rather than first.

## 2. Complete SDK method list (verified)

```
login · logout · set_session · forgot_password
place_order · modify_order · cancel_order · exit_order · single_order_history
get_order_book · get_trade_book · get_positions · get_holdings · get_limits
get_quotes · get_time_price_series · get_daily_price_series · get_security_info · searchscrip
get_option_chain · option_greek · span_calculator · position_product_conversion
get_watch_list · get_watch_list_names · add_watch_list_scrip · delete_watch_list_scrip
start_websocket · subscribe · unsubscribe · subscribe_orders · close_websocket
```

**Absent:** anything GTT, alert, ledger, charges or contract-note related.

## 3. GTT — REST only

Confirmed by Shoonya's own FAQ: GTT orders **can** be placed through the API, but the feature is
**not included in the Python SDK**. Community implementations show a `gttOrder` / `cancelGtt`
pair and alert-type parameters (`LTP_A_O` = LTP above, and equivalents).

> 🔴 **This is the single most important unknown in the broker layer.** The exact endpoint,
> payload and alert-type enumeration must come from Shoonya's REST documentation or their API
> support desk (`apisupport@shoonya.com`, 0172-4740000) before Phase E begins. (Q-237)

## 4. ⚠️ No ledger or charges surface
Nothing in the SDK exposes a ledger, contract note or charge breakdown. As with Groww, the
computed-vs-reported contrast (D-024) may degrade to computed-only, with manual statement upload
as the fallback (Q-238).

## 5. Auth — OAuth 2.0 (see §0)

Verified: authorize URL → `code` from redirect → SHA-256 checksum → `gen_access_token` →
`susertoken`, carried as a Bearer header. `Client ID` and `Secret Code` are both read from the
**API Key Generation** screen in the trading account — the same screen that registers the static
IP.

**Token lifetime remains ❓ UNVERIFIED** (Q-269) — the `manual-login-oauth` page returns 403 to
automated fetch and must be read by hand or confirmed with API support.

## 6. Proxy behaviour — ❌ cannot comply
26 bare `requests.post` calls, no session anywhere. Raw HTTP is mandatory.

## 7. Rate limits — verified

[Source](https://shoonya.com/api-documentation/rate-limits)

| Category | Limit |
|---|---|
| Order place / modify / cancel | ~10 req/sec, burst-limited, **per user** |
| Market data (REST) | **~1 req/sec per instrument** |
| WebSocket connect | 1 connection per session |
| Historical data | lower burst allowance |

Throttling returns `{"stat":"Not_Ok","emsg":"Rate_Limited: too many requests, retry after
backoff"}`. Shoonya states plainly that "exact numeric ceilings are enforced server-side and may
be tuned without notice — treat the table above as design guidance, not a contract", and
prescribes **exponential backoff with jitter**. The adapter implements that branch regardless of
ATOM's low volume.

The **1 req/sec per instrument** data ceiling is a second, independent argument (alongside
Dhan's 1 quote/sec) for sourcing market data from one provider rather than per broker.

## 7a. Static IP whitelisting — verified, and it gates *everything*

[Source](https://shoonya.com/api-documentation/ip-whitelisting)

Registered on the **API Key Generation** screen: a **Primary IP** and an optional **Backup IP**,
IPv4 or IPv6. Unlike Dhan, where whitelisting gates only order placement, Shoonya states the IP
must be registered "before you can complete the OAuth login flow **or call any endpoint**" —
so on Shoonya a wrong egress IP fails at login, which at least fails loudly and early.

The screen also carries an **"Applicable for more than 10 orders per second"** checkbox. Shoonya
is explicit that this is **not a self-service throttle raise** — without a corresponding
exchange-approved Algo ID it "does not raise your actual throughput". ATOM leaves it unchecked.

## 7b. SEBI Algo ID — Shoonya reads the circular strictly

[Source](https://shoonya.com/api-documentation/algo-compliance)

Shoonya states that SEBI circular **SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013** requires
**every** API order — "not just orders from registered algo strategies" — to carry a
broker-empanelled Algo ID, with full enforcement from **1 April 2026** and non-compliant orders
"expected to be rejected at the exchange level". A "personal script placing orders via the API"
is listed as requiring one.

**This directly contradicts Upstox's reading**, which requires registration only above 10 OPS.
Both readings are recorded in `API-REFERENCE-VERIFIED.md` §0.3. Until settled per broker
(**Q-268**), assume Shoonya's stricter reading applies to Shoonya.

## 8. Open items
| ID | Item |
|---|---|
| Q-237 | 🔴 Shoonya GTT: exact REST endpoint, payload and alert-type enum — blocking for Phase E |
| Q-238 | Does Shoonya expose a ledger or charges API? |
| Q-239 | Token lifetime and refresh semantics — **superseded by Q-269** |
| Q-240 | Rate limits — ✅ **closed 2026-09-24**, see §7 |
| Q-241 | IP whitelisting procedure — ✅ **closed 2026-09-24**, see §7a |
| Q-268 | 🔴 Does ATOM need an empanelled Algo ID on Shoonya at 2 OPS? Shoonya says yes for any API order |
| Q-269 | Shoonya OAuth access-token lifetime — page returns 403 to automated fetch |
| Q-271 | Shoonya GTT endpoint and alert-type enum (restates Q-237 against the rebuilt docs) |
