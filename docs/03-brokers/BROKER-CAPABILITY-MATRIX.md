# Broker Capability Matrix

**Status:** 🟢 Round 2 complete — all round-1 `❓ UNVERIFIED` cells now filled from vendor
documentation, except those listed in §6. Detailed evidence, payloads and sources live in
[`API-REFERENCE-VERIFIED.md`](API-REFERENCE-VERIFIED.md); this file stays the one-page summary.
**Date:** 2026-09-16 · **round 2: 2026-09-24**
**Scope:** All five brokers are confirmed as **fully built and tested in v1** (Q-020).

> **Rule for this document:** every cell is either (a) sourced from vendor documentation with
> a link, or (b) marked `❓ UNVERIFIED`. Nothing is inferred from another broker's behaviour.
> Round 1 establishes the shape; round 2 fetches each vendor's full reference and fills gaps.

---

## 1. GTT IS REQUIRED — place and cancel only (D-063, supersedes D-060)

GTT was briefly removed and is now **reinstated**, because it is what protects a position on
days the engine is not run. The staleness problem is solved procedurally instead: **every run
cancels all ATOM-placed GTTs first**, verifies the book is clean, then re-places from freshly
computed averages.

**Required GTT surface per adapter — deliberately minimal:**

| Method | Needed | Note |
|---|---|---|
| `place_gtt` | ✅ | One per sellable holding, each run |
| `cancel_gtt` | ✅ | The cancel-all-first step; **must return the broker order ID at placement so only ATOM's own orders are cancelled** |
| `get_gtt_orders` | ✅ | To verify the book is clean before proceeding |
| `modify_gtt` | ❌ | **Not required** — ATOM cancels and re-places, never modifies |

**Still to verify per broker:** whether cancellation is synchronous or needs re-polling
(Q-185), maximum validity, and whether a GTT survives its underlying holding being sold by
other means.

## 1a. Finding — GTT is available everywhere, but not uniformly

Decision Q-055 chose "GTT where supported, DAY fallback". Round 1 confirms **all five brokers
expose a GTT-style facility**, so the fallback path may be needed far less than assumed —
but the semantics differ enough that the adapter must normalise them.

| Broker | GTT facility | Notes |
|---|---|---|
| **Upstox** | ✅ Dedicated GTT API, `POST /v3/order/gtt/place`, plus modify and details endpoints | Active until expiry date; intraday GTTs valid only for the day ([docs](https://upstox.com/developer/api-documentation/place-gtt-order/)) |
| **Dhan** | ✅ "Forever Order" | Long-validity order triggered on price condition; price, qty, order type, disclosed qty, trigger price and validity are all modifiable ([docs](https://dhanhq.co/docs/v2/forever/)) |
| **Zerodha** | ✅ GTT via Kite Connect | Place/modify/cancel alongside regular, AMO and cover orders ([docs](https://zerodha.com/products/api/)) |
| **Groww** | ✅ GTT under "Smart Orders" | Valid **up to 1 year**; states ACTIVE / TRIGGERED / CANCELLED / EXPIRED / FAILED / COMPLETED; COMMODITY segment unsupported ([docs](https://groww.in/trade-api/docs/python-sdk/smart-orders)) |
| **Shoonya** | ⚠️ GTT via **REST only — not in the Python SDK** | Alert-type parameters (e.g. `LTP_A_O` for "LTP above") drive the trigger ([FAQ](https://faq.shoonya.com/api/can-i-place-a-gtt-good-till-trigger-order-through-apis/)) |

**With GTT reinstated, the Shoonya row matters again:** its Python SDK cannot place the order
this strategy depends on, while its REST API can. That settles the raw-HTTP decision (D-056b)
on capability grounds, not just preference.

**Design consequence.** The Shoonya row is the first hard evidence for the Q-026 proposal to
implement **raw HTTP rather than vendor SDKs**: Shoonya's own Python SDK cannot place the
GTT order this strategy depends on. Building on the SDK would mean the fallback path for
Shoonya alone — while the REST API supports it perfectly well.

**Still to verify for every broker:** maximum GTT validity period, whether a GTT survives a
holdings change, whether quantity is validated at placement or at trigger, and what happens
to a GTT when the underlying holding is sold by other means. `❓ UNVERIFIED`

---

## 2. Authentication — ✅ all five verified (2026-09-24)

| Broker | Token lifetime | Headless path? | Flow |
|---|---|---|---|
| **Upstox** | Daily | ⚠️ **Semi-automated** — operator approves on mobile, token delivered to a **notifier URL** | OAuth code → `POST /v2/login/authorization/token` |
| **Dhan** | **24 h**, `expiryTime` returned explicitly | ✅ **Yes** — `POST auth.dhan.co/app/generateAccessToken` with PIN + TOTP | Direct token, or 3-step key+secret consent (keys valid **12 months**) |
| **Zerodha** | **Expires 6 AM next day** — stated as a regulatory requirement | ❌ No — `refresh_token` exists but is "only available to certain approved platforms" | `request_token` → `checksum = SHA-256(api_key + request_token + api_secret)` → `/session/token` |
| **Groww** | **Expires daily at 6:00 AM** | ⚠️ Checksum/TOTP call is headless but **still needs a daily approval click** in Groww's console | Token from settings, or `POST /v1/token/api/access` with `key_type` `approval` \| `totp` |
| **Shoonya** | ❓ (Q-269 — page 403s to automated fetch) | ❓ | **OAuth 2.0** — authorize → code → `SHA-256(client_id + secret + code)` → `gen_access_token`, Bearer header |

Sources: [Upstox](https://upstox.com/developer/api-documentation/authentication/) ·
[Dhan](https://dhanhq.co/docs/v2/authentication/) ·
[Zerodha](https://kite.trade/docs/connect/v3/user/) ·
[Groww](https://groww.in/trade-api/docs/curl) ·
[Shoonya](https://shoonya.com/api-documentation/api-structure)

**Two findings that change scheduling and one that changes SHOONYA.md.**

- **Zerodha and Groww both expire at 6 AM.** A token generated before 6 AM is dead before the
  market opens. The token-generation window and the run window must both sit **after 06:00 IST**.
- **Shoonya has migrated from the legacy Noren `QuickAuth` to OAuth 2.0.** Package name, auth
  model and token transport all changed. `SHOONYA.md` §0 records the before/after.
- **Zerodha alone lets ATOM actively destroy the token** (`DELETE /session/token`). D-170's
  end-of-run `CLEARED` step should call it there, and merely forget the token elsewhere.

**Design consequence for Q-022 — revised.** Round 1 concluded the console needs a per-broker
screen. It does not: it needs **three patterns**, not five.

| Pattern | Brokers | Operator action each morning |
|---|---|---|
| **A — Headless** (TOTP / checksum) | Dhan, Groww¹, Shoonya² | None, or one approval click |
| **B — Hosted redirect** | Upstox, Zerodha, Dhan (key+secret), Shoonya | Click "Login", authenticate, redirect lands the token |
| **C — Paste-in** | **All five** | Copy from the broker's site, paste into ATOM |

¹ Groww still requires its daily approval click.  ² Shoonya's code step still appears interactive.

**Pattern C is implemented for all five as the guaranteed fallback** — every broker supports
copy-paste, and it is the only path a vendor cannot break by changing its redirect handling.
A and B are optimisations layered on top, added per broker as they are proven.

---

## 3. Rate limits — ✅ all five verified (2026-09-24)

| Broker | Orders | Data | Other |
|---|---|---|---|
| **Upstox** | 10/s · 500/min · 2,000/30 min (unregistered algos; 50/s if SEBI-registered) | Standard APIs 50/s · 500/min | TOTP login 1/s · 10/min · 60/30 min |
| **Dhan** | 10/s · 250/min · 1,000/hr · **7,000/day**; **max 25 modifications per order** | Data 5/s · 100,000/day · **Quote 1/s** | Non-trading 20/s |
| **Zerodha** | 10/s per API key · 400/min · 5,000/day | — | — |
| **Groww** | 10/s · 250/min | Live data 10/s · 300/min | Auth 5/s · 30/min, **150/day** on `/v1/token/api/access`; non-trading 20/s · 500/min. **Limits apply per *type*, not per endpoint** |
| **Shoonya** | ~10/s, burst-limited | **~1/s per instrument** | 1 WebSocket connection per session; `Rate_Limited` in `emsg`; "ceilings may be tuned without notice" |

Sources: [Upstox](https://upstox.com/developer/api-documentation/rate-limiting/) ·
[Dhan](https://dhanhq.co/docs/v2/) · [Groww](https://groww.in/trade-api/docs/curl) ·
[Shoonya](https://shoonya.com/api-documentation/rate-limits)

**D-148 ("rate limits do not affect us") holds for orders and fails for quotes.** ATOM places a
handful of orders per account per day against ceilings of 7,000–10,000. But **Dhan's 1 quote per
second** and **Shoonya's 1 per second per instrument** mean pricing a 60-ETF universe from either
broker takes a full minute per account. Shoonya's own documentation instructs readers to prefer
WebSocket over polling.

This settles **Q-044 on evidence rather than preference: market data is pulled once, from one
provider, for all accounts — never per broker.**

Shoonya's "may be tuned without notice" clause means the adapter implements a `Rate_Limited`
branch with **exponential backoff and jitter** regardless of headroom. Their docs supply the
pattern; ATOM follows it rather than assuming its low volume is an exemption.

---

## 4. Notable per-broker behaviours found so far

- **Dhan converts MARKET orders to LIMIT with market price protection.** Directly relevant
  to Q-027 (market vs limit buys) — on Dhan the question is partly moot, and a limit order
  with a buffer is closer to what actually happens.
  ([support](https://dhan.co/support/platforms/open-api/how-many-orders-can-i-placed-using-dhan-api/))
- **Upstox `X-Algo-Name` header** is optional, required only for exchange-approved algo
  strategies. Needs a compliance read in round 2 — an automated strategy placing orders may
  fall under exchange algo rules.
  ([docs](https://upstox.com/developer/api-documentation/place-gtt-order/))
- **Groww Smart Orders exclude COMMODITY.** Irrelevant for ETFs, but it tells us the Smart
  Order surface is segment-restricted, so equity/ETF eligibility must be confirmed.

---

## 5. Round 2 — done

All four items on the original plan are complete and written up in
[`API-REFERENCE-VERIFIED.md`](API-REFERENCE-VERIFIED.md): auth endpoints and lifetimes, order
payloads and product types, GTT semantics, and portfolio shapes. Vendor pages were read on
**2026-09-24**; every claim in that document names the page it came from.

### What round 2 changed, not just confirmed

| Finding | Effect |
|---|---|
| **Static IP is now mandatory** (SEBI + NSE/INVG/67858, live since 1 Apr 2026) | Validates D-009…D-011 outright — the design anticipated a rule that is now enforced |
| **Dhan locks a registered IP for 7 days** | Elastic IP becomes mandatory; an instance rebuild without it is a **week-long outage**, and `verify_egress_ip.py` must gate every run |
| **Dhan whitelists writes only** | The D-170 holdings probe does **not** exercise the proxy path on Dhan — egress IP must be verified as a **separate** pre-flight gate |
| **Market orders no longer permitted via API** | ATOM already places limits only; the `MARKET` type should be removed from the live adapter surface entirely |
| **Upstox needs EDIS for any sell GTT** | A one-time manual step that gates ATOM's **entire sell side** on Upstox (Q-270) |
| **Zerodha token dies at 6 AM; Groww too** | Token generation and runs must both sit after 06:00 IST |
| **Zerodha GTTs carry no ATOM identifier until fired** | ATOM's own `trigger_id` mapping is the **only** link to its orders there — it must be persisted before `place_gtt` returns |
| **Groww's `order_reference_id` is a required idempotency key** | Generalised into a canonical `client_ref` (≤ 20 chars) across all five adapters |
| **Dhan returns itemised per-trade charges** | The charges-contrast view has a ground truth on Dhan, not a model |
| **Groww splits `t1_quantity` / `demat_free_quantity`** | "broker quantity" in the attribution identity is ambiguous and must be pinned to the sellable figure (Q-272) |

### The one genuine disagreement

**Upstox** says Algo registration is required only above **10 OPS**. **Shoonya** says SEBI
circular *SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013* requires a broker-empanelled Algo ID on
**every** API order, with non-compliant orders "expected to be rejected at the exchange level".

ATOM runs at 2 OPS (D-149), so it is unaffected under Upstox's reading and **blocked under
Shoonya's**. Documentation cannot settle this — it must be confirmed with each broker before the
first live order. Tracked as **Q-268** and external blocker **X8**.

The adapter contract carries an **optional per-account `algo_id` / `algo_name`**, defaulting to
unset, that each adapter maps to its broker's field. Building it now costs nothing; retrofitting
it after a rejection costs a trading day.

---

## 6. Still unverified after round 2

| Item | Broker | Question |
|---|---|---|
| ~~Algo ID applicability at 2 OPS~~ | ~~All five~~ | ✅ **Q-268 closed 2026-09-24** — no Algo ID required, verified by the operator (D-181) |
| Access-token lifetime | Shoonya | **Q-269** |
| GTT endpoint + alert-type enum | Shoonya | **Q-271** (was Q-237) 🔴 |
| Per-trade charge breakdown | ~~Zerodha~~, Groww, Shoonya | Q-273 — **Zerodha resolved:** `POST /charges/orders` (D-186) |
| Static-IP whitelisting procedure | Zerodha, Groww | Q-274 |
| Does a GTT survive its holding being sold by other means? | All five | Q-186 (open since round 1) |
| Data-API / subscription cost | Dhan, Groww | Q-275 |

Nothing in this list blocks the adapter engine or the per-broker adapter documents. Q-271 blocks
Phase E only.

### The disagreement, resolved

Q-268 is **closed and out of scope**. The operator verified directly that no Algo ID is required:
they continued trading through the earlier system after the circular took effect, ATOM does not
fall within the registration regime, and ~1 order per second is far below the 10 OPS threshold.
**Shoonya's documentation overstates the requirement.** External blocker X8 is withdrawn and no
letters go to broker compliance desks on this point (D-181).

---

## 7. Next: the adapter engine

The framework is specified in [`ADAPTER-ENGINE.md`](ADAPTER-ENGINE.md) — two directions, five
stages each, eight canonical models, one capability profile, one error taxonomy.

Per-broker mappings live in [`adapters/`](adapters/), written one broker at a time after its
developer documentation has been read end to end:

| # | Broker | Status |
|---|---|---|
| 1 | **Zerodha** | ✅ [`adapters/ZERODHA-ADAPTER.md`](adapters/ZERODHA-ADAPTER.md) |
| 2 | Groww | ⏳ next |
| 3 | Upstox | ⏳ |
| 4 | Dhan | ⏳ |
| 5 | Shoonya | ⏳ last (GTT surface unpublished, Q-271) |
