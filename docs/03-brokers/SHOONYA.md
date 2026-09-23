# Shoonya (Finvasia) — Broker Adapter Specification

**Status:** 🟠 SDK fully inspected · REST specifics still needed
**Role in ATOM:** trading account
**Priority:** Phase E — **last, deliberately** (D-140)
**Source:** `NorenRestApiPy` 0.0.22 (PyPI), Shoonya API documentation

---

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

## 5. Auth
`login` / `set_session` with the Noren session model. Token lifetime ❓ **UNVERIFIED**.

## 6. Proxy behaviour — ❌ cannot comply
26 bare `requests.post` calls, no session anywhere. Raw HTTP is mandatory.

## 7. Rate limits
❓ **UNVERIFIED.**

## 8. Open items
| ID | Item |
|---|---|
| Q-237 | 🔴 Shoonya GTT: exact REST endpoint, payload and alert-type enum — blocking for Phase E |
| Q-238 | Does Shoonya expose a ledger or charges API? |
| Q-239 | Token lifetime and refresh semantics |
| Q-240 | Rate limits |
| Q-241 | IP whitelisting procedure |
