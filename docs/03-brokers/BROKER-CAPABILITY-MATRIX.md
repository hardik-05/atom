# Broker Capability Matrix

**Status:** 🟡 Research round 1 — verified facts only, gaps explicitly marked
**Date:** 2026-09-16
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

## 2. Authentication

| Broker | Token lifetime | Flow | Source |
|---|---|---|---|
| **Upstox** | Access token **regenerated daily**; separate long-lived *analytics* token needs no daily re-auth | OAuth → Get Token API | [API overview](https://upstox.com/developer/api-documentation/api-overview/) |
| **Dhan** | **24 hours**, explicitly aligned to exchange/SEBI guidance on API access management | Token generated from account | [Dhan support](https://dhan.co/support/platforms/dhanhq-api/how-can-i-place-an-order-using-an-api-access-token/) |
| **Zerodha** | Daily | `request_token` → exchange for `access_token` | ❓ verify in round 2 |
| **Groww** | **Access token with daily expiry**; generated in Profile → Settings → Trading APIs → Generate API Keys | Bearer token on `POST https://api.groww.in/v1/order/create` | [docs](https://groww.in/trade-api/docs/curl/orders) |
| **Shoonya** | ❓ UNVERIFIED | NorenApi login | [GitHub SDK](https://github.com/Shoonya-Dev/ShoonyaApi-py) |

**Design consequence for Q-022 (daily token flow).** The five brokers do **not** share one
flow. Groww issues a token from a settings page (paste-in works); Upstox and Zerodha use an
OAuth redirect (a hosted redirect URI works better); Dhan is token-from-account. The console
will need a **per-broker token acquisition strategy**, not one shared screen — this changes
the Screen 1 design and is worth confirming before I write it.

---

## 3. Rate limits

| Broker | Limits | Source |
|---|---|---|
| **Dhan** | Non-trading 20/s · **Orders 10/s** · Data 5/s · Quote 1/s. Day cap **5,000 orders**, 25/s, 250/min | [rate limits](https://docs.dhanhq.co/api/v2/guides/rate-limits) |
| **Zerodha** | **10 req/s per API key** (enforced at key level). Day cap **5,000 orders**, **400/min** | [forum](https://kite.trade/forum/discussion/15398/api-rate-limits), [support](https://support.zerodha.com/category/trading-and-markets/alerts-and-nudges/kite-error-messages/articles/order-rate-limits-on-kite) |
| **Upstox** | ❓ UNVERIFIED | |
| **Groww** | ❓ UNVERIFIED | |
| **Shoonya** | ❓ UNVERIFIED | |

ATOM's order volume is tiny (a handful per account per day), so order-rate caps are not a
constraint. **The real exposure is data**: Dhan's *Quote API at 1 request per second* would
make quoting a 60-ETF universe take a full minute per account. This is an argument for
Q-044's single-data-source design — pull market data once from one provider, not per broker.

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

## 5. Round 2 plan

For each broker, fetch and snapshot into `docs/99-vendor-docs/<broker>/` (dated), then fill:

1. Auth: exact endpoints, token lifetime, refresh semantics, redirect URI requirements,
   **static-IP whitelisting procedure** (critical for Q-010/Q-011)
2. Orders: place/modify/cancel payloads, product types (CNC), validity, tick/price rules
3. GTT: full semantics, limits, modification rules
4. Portfolio: holdings vs positions shape, average-cost field, quantity fields
5. Funds: available-margin field names and their exact meaning
6. Market data: historical candles, quotes, instrument master
7. Ledger and charges: what is exposed, in what form, at what latency (feeds Q-100)
7a. **Funds credit events (D-050):** does the broker expose the actual date funds from a sale
   land in the account, and is the credit attributable to a specific trade or only to a
   ledger line? Where it is not attributable, FIFO matching is required. **No adapter may
   assume T+1** — a Friday sale credits Monday at the earliest, and holidays extend it
8. Errors: codes, rate-limit responses, retry guidance

---

## Sources

- [Upstox — Place GTT Order](https://upstox.com/developer/api-documentation/place-gtt-order/)
- [Upstox — API Overview](https://upstox.com/developer/api-documentation/api-overview/)
- [Upstox — Place Order V3](https://upstox.com/developer/api-documentation/v3/place-order/)
- [DhanHQ v2 — Forever Order](https://dhanhq.co/docs/v2/forever/)
- [DhanHQ v2 — Orders](https://dhanhq.co/docs/v2/orders/)
- [DhanHQ — Rate Limits](https://docs.dhanhq.co/api/v2/guides/rate-limits)
- [Zerodha — Kite Connect](https://zerodha.com/products/api/)
- [Zerodha — Order rate limits](https://support.zerodha.com/category/trading-and-markets/alerts-and-nudges/kite-error-messages/articles/order-rate-limits-on-kite)
- [Groww — Trade API](https://groww.in/trade-api)
- [Groww — Smart Orders (GTT)](https://groww.in/trade-api/docs/python-sdk/smart-orders)
- [Groww — Orders (cURL)](https://groww.in/trade-api/docs/curl/orders)
- [Shoonya — API documentation](https://shoonya.com/api-documentation)
- [Shoonya — GTT via API FAQ](https://faq.shoonya.com/api/can-i-place-a-gtt-good-till-trigger-order-through-apis/)
- [Shoonya — Python SDK](https://github.com/Shoonya-Dev/ShoonyaApi-py)

---

## 7. Consolidated matrix — verified from SDK source, 2026-09-23

Per-broker detail in [`UPSTOX.md`](./UPSTOX.md) · [`DHAN.md`](./DHAN.md) ·
[`ZERODHA.md`](./ZERODHA.md) · [`GROWW.md`](./GROWW.md) · [`SHOONYA.md`](./SHOONYA.md).

| | **Upstox** | **Dhan** | **Zerodha** | **Groww** | **Shoonya** |
|---|---|---|---|---|---|
| **Auth** | OAuth redirect | Token from account | `request_token`→`access_token` | Paste-in from app | Noren login |
| **Token life** | Daily (+ long-lived analytics token) | **24 h** | Daily | Daily | ❓ |
| **GTT in SDK** | ✅ v3 API | ✅ Forever Order | ✅ `/gtt/triggers` | ⚠️ constants only, **no methods** | ❌ **absent** |
| **GTT in REST** | ✅ | ✅ | ✅ | ✅ (docs) | ✅ (FAQ) |
| **Ledger API** | ⚠️ P&L charges | ✅ `/ledger` dated | ⚠️ via charges | ❌ none found | ❌ none found |
| **Charges API** | ✅ `/v2/charges/brokerage`, `/trade/profit-loss/charges` | ❌ | ✅ **`/charges/orders`** | ❌ | ❌ |
| **Egress IP self-check** | ✅ **`/v2/user/ip`** | ✅ **`/ip/getIP`** | ❌ | ❓ | ❓ |
| **IP whitelist API** | ❌ | ✅ **`/ip/setIP`** | ❌ | ❓ | ❓ |
| **Rate limits** | ❓ | ✅ orders 10/s · **quote 1/s** | ✅ 10/s per key · 5,000/day | ❓ | ❓ |
| **Per-instance proxy** | ✅ | ⚠️ auth leaks | ✅ cleanest | ❌ impossible | ❌ impossible |
| **Instrument master** | CDN `.json.gz` | CDN `.csv` | `/instruments` | CDN `.csv` | `searchscrip` |
| **Adapter risk** | Low | Low–medium | Medium | Medium | **High** |

### What the matrix shows

1. **Charge visibility is uneven and decides the reporting design.** Upstox and Zerodha expose
   charges directly; Dhan exposes a dated ledger; **Groww and Shoonya appear to expose neither.**
   The computed-vs-reported contrast (D-024) will therefore be genuinely two-sided for three
   brokers and computed-only for two — with manual statement upload the fallback (Q-234, Q-238).
2. **Two brokers can verify their own egress IP.** `/v2/user/ip` and `/ip/getIP` turn the hardest
   infrastructure assumption (D-005) into a startup assertion. Build that health check first.
3. **Dhan can set the whitelist by API** — useful for *reading* it as a check; writing it should
   stay manual (Q-229).
4. **GTT exists everywhere in REST but only partially in SDKs** — which is the whole basis of
   D-135.
