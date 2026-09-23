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

## 7. Rate limits
❓ **UNVERIFIED.**

## 8. Open items
| ID | Item |
|---|---|
| Q-233 | 🔴 Exact GTT/Smart Order endpoint and payload from Groww's REST docs — the main unknown |
| Q-234 | Does Groww expose a ledger or charges API at all? |
| Q-235 | Rate limits |
| Q-236 | Does Groww support IP whitelisting, and by what procedure? |
