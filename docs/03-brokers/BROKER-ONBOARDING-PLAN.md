# Broker Onboarding Plan

**Status:** 🟢 Plan · execution follows the design freeze (D-087)
**Covers:** Upstox · Dhan · Zerodha · Groww · Shoonya
**Builds on:** [`SDK-EVALUATION.md`](./SDK-EVALUATION.md) · [`BROKER-CAPABILITY-MATRIX.md`](./BROKER-CAPABILITY-MATRIX.md)

---

## 1. What "onboarding a broker" actually means

Two different things share the phrase, and keeping them apart is what makes the fifth broker
cheap:

| | **Building an adapter** | **Connecting an account** |
|---|---|---|
| Who | Developer, once per broker | Operator, once per investor per broker |
| Output | A module implementing the contract | Credentials, a whitelisted IP, a daily token |
| Frequency | 5 times, ever | Every time someone joins |
| Covered in | §3–§6 | §7 |

The goal of the architecture is that **adding broker #6 touches no application code** — only a
new adapter module and a config entry.

---

## 2. Architecture — one HTTP core, five thin adapters

```
        strategy engine  (knows nothing about brokers)
                 │
        ┌────────▼─────────┐
        │  BrokerAdapter   │   17-method contract (D-066)
        │    (abstract)    │
        └────────┬─────────┘
                 │
   ┌──────┬──────┼──────┬───────┐
 Upstox  Dhan  Zerodha Groww Shoonya      ← per-broker: endpoints, payloads, enums, errors
   └──────┴──────┼──────┴───────┘
                 │
        ┌────────▼─────────┐
        │    HttpCore      │   ← ONE place: proxy, retries, rate limit, logging, redaction
        └────────┬─────────┘
                 │
     per-account forward proxy → investor's static IPv4 (D-005/D-007)
```

**Everything shared lives in `HttpCore`.** Each adapter is then only: base URL, auth handshake,
endpoint paths, request/response mapping, and an error table. That is what makes five adapters
tractable and a sixth routine.

### The non-negotiable

```python
class BrokerAdapter(ABC):
    def __init__(self, credentials: Credentials, proxy_url: str):
        if not proxy_url:
            raise ConfigurationError("proxy_url is mandatory — refusing to use the default route")
```

Per D-136, and directly because three of five vendor SDKs leak. A test asserts that **no code
path reaches a broker without a proxy** — mock the socket layer, run every adapter method,
fail if any connection is attempted outside the proxy.

---

## 3. The eight stages, per broker

Each stage is independently verifiable; a broker can sit part-built without blocking the others.

| # | Stage | Output | Needs the operator? |
|---|---|---|---|
| **1** | **Commercials and T&C** | API subscription active; T&C confirms automated placement is permitted (**D-074c, blocking**) | ✅ |
| **2** | **Developer app** | API key/secret, redirect URI registered | ✅ |
| **3** | **IP whitelisting** | Investor's static IPv4 registered with the broker | ✅ |
| **4** | **Auth handshake** | `authenticate()` returns a working token via the proxy | |
| **5** | **Read-only surface** | `get_funds`, `get_holdings`, `get_positions`, `get_quote`, `get_historical_candles` | |
| **6** | **Order surface** | `place_order`, `cancel_order`, `get_order_status`, `get_order_book`, `get_trade_book` | |
| **7** | **GTT surface** | `place_gtt`, `cancel_gtt`, `get_gtt_orders` | |
| **8** | **Money surface** | `get_ledger`, `get_charges`, `get_funds_credits` (D-050) | |

**Stages 5 and 8 are worth more than they look.** Stage 5 alone makes a broker usable as a
**data source** (D-017) — an account can feed prices to the whole system without ever placing an
order. Stage 8 is what the charges model and cost-of-capital depend on, and it is where brokers
differ most.

### Certification — a broker is "done" when

1. Every contract method returns the canonical model, with responses recorded as test fixtures.
2. The proxy test passes: no call escapes the account's IP.
3. A **dry run** completes end to end against live data (D-041).
4. A **₹1,000 live round trip** — buy, GTT sell, cancel, reconcile — with charges tying to the
   contract note.
5. The capability matrix row is filled with no `❓ UNVERIFIED` cells.

---

## 4. Sequencing — and why this order

```
Phase A   Upstox        data + trading   ── unblocks everything
Phase B   Dhan          trading          ── second live account
Phase C   Zerodha       trading          ── account exists, no data subscription
Phase D   Groww         trading
Phase E   Shoonya       trading          ── hardest, deliberately last
```

**Upstox first**, because it is the designated market-data source (D-058i). Its stage 5 alone
lets the universe job, the ranking engine, the NAV gate and the entire paper-trading path be
built and validated — **before any other broker exists, before the static IPs are registered,
and before a single rupee is at risk.** Nothing else unblocks as much.

**Dhan second** — the other live account, and its capability matrix row is already the
best-researched.

**Zerodha third.** The account exists but has no data API subscription, making it the first
real test of the decoupling in D-017: data from Upstox, orders to Zerodha. That interaction is
worth exercising early rather than discovering late.

**Groww fourth, Shoonya last.** Both are new accounts with no existing relationship, and
Shoonya is the hardest on every axis — GTT is REST-only, its SDK is unusable, and its
documentation is the thinnest of the five.

---

## 5. Per-broker notes from the research so far

| | Auth | Token life | GTT | Rate limits | Adapter risk |
|---|---|---|---|---|---|
| **Upstox** | OAuth 2.0 redirect | Daily; separate long-lived analytics token | `POST /v3/order/gtt/place`, modify + details | ❓ | **Low** — cleanest docs, v3 API |
| **Dhan** | Token from account | **24h**, per SEBI guidance | "Forever Order", incl. OCO | Orders 10/s · data 5/s · **quote 1/s** | **Low–medium** |
| **Zerodha** | `request_token` → `access_token` | Daily | GTT place/modify/cancel | 10/s per API key; 5,000 orders/day, 400/min | **Medium** — most documented, subscription cost |
| **Groww** | Token from settings page, Bearer | Daily expiry | "Smart Orders", up to **1 year**; no COMMODITY | ❓ | **Medium** — newest API |
| **Shoonya** | NorenApi login | ❓ | ⚠️ **REST only, absent from SDK** | ❓ | **High** — thinnest docs, alert-type semantics (`LTP_A_O`) |

> ⚠️ **Dhan's quote API at 1 request/second** is the sharpest constraint found so far. Pricing a
> 60-ETF universe serially would take a minute per account. It is a strong argument for the
> single-data-source design (D-017) and means Dhan should never be the price source.

### Commercials — verify before committing (Q-224)

Public sources disagree, and the numbers move. Reported: **Zerodha Kite Connect around
₹2,000/month**; **Dhan's data pack around ₹499/month**; Upstox, Groww and Shoonya variously
described as free. **Confirm each on the broker's own developer page before subscribing** — at
five brokers this is a recurring monthly cost that could rival the entire AWS bill (~₹755).

*Note the asymmetry this creates: a broker may be free for **orders** but charged for **data**.
Since ATOM needs data from only one broker (D-017), the others can stay on order-only access.
That could be the difference between one subscription and five.*

---

## 6. Effort shape

Once `HttpCore` and the contract exist, per-broker work is mostly mapping, not engineering:

| Work | Where it lands |
|---|---|
| **One-time** | `HttpCore` (proxy, retries, rate limiting, redaction, logging), the abstract contract, canonical models, the fixture harness |
| **Per broker** | Auth handshake · endpoint map · request/response mapping · error table · fixtures |

The first adapter is the expensive one because it builds the shared core with it. Adapters two
through five are progressively cheaper — provided nothing broker-specific leaks upward, which
is exactly what the review rule guards.

---

## 7. Connecting an account (operator-facing, per investor per broker)

1. Investor opens/holds the broker account.
2. Operator creates the developer app, notes key and secret.
3. Operator **registers the investor's static IPv4** with that broker (D-007) — manual, per
   broker, and never automated.
4. Credentials stored in SSM Parameter Store (D-079).
5. Account row created; `investor_id` assigned (D-128).
6. **All configs supplied** — the pre-flight check blocks the account until complete (D-038/D-067).
7. **Pre-existing holdings auto-excluded, once** (D-137).
8. Daily token flow tested end to end.
9. Dry run, then a small live trade.

Steps 1–3 are the long pole: they involve a third party and cannot be parallelised away.

---

## 8. Open items

| ID | Item |
|---|---|
| Q-224 | Confirm API subscription cost per broker on their own developer pages |
| Q-225 | Should stage 5 (read-only) ship for all five early, so any account can serve as a data fallback, or only for Upstox? *(Rec: all five — it is cheap, needs no order permissions, and removes a single point of failure on market data)* |
| Q-185 | Per broker: is GTT cancellation synchronous, or must the order book be re-polled? |
| Q-178 | Per broker: where and when DP charges surface |
| Q-175 | Per broker: `funds_credited_date` exposure and trade-attributability |
| Q-179 | Is ₹0.01 the universal NSE ETF tick, or does it vary by price band? |
