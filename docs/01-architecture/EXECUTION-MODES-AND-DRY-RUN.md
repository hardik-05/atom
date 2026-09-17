# Execution Modes and Dry-Run Infrastructure

**Status:** 🟢 Specified
**Implements:** D-041
**Why this is architectural, not a feature:** the dry-run requirement is the reason the
codebase must be modular. It is the single strongest forcing function on the design.

---

## 1. The requirement

> "The whole application, once built, should also have the capability to do a dry run rather
> than making the buy/sell call directly onto the market. Prices should be real, taken from
> the market, but post that we should be able to do an end-to-end dry run. For each account
> they can toggle between dry-run mode, add paper money, and the whole portfolio should mimic
> the way an actual would work — **same logic, same priority, same configs**. Once the person
> agrees the dry run is giving good returns, they switch to the original trading model."

A dry run is **not** a simulation with approximated inputs. It is the *real* engine, on
*real* market data, with *real* configs, differing at exactly one point: where an order would
be sent to a broker, it is instead recorded against a paper portfolio.

---

## 2. The seam — one interface, two implementations

Everything upstream of order placement is shared code with no knowledge of mode:

```
  universe → ranking → NAV gate → holdings check → funds check → sizing
                                    │
                                    ▼
                          ┌───────────────────┐
                          │  OrderGateway     │   ← the only seam
                          └───────────────────┘
                            │               │
              LiveOrderGateway         PaperOrderGateway
              → broker REST API        → paper fill engine + Supabase
```

**The seam is exactly one interface.** If any strategy, ranking, config, logging or
reporting code needs an `if dry_run:` branch, the boundary has been drawn in the wrong place.

| Concern | Live | Dry run |
|---|---|---|
| Market data | Real (D-017) | **Real — identical** |
| Config | Real (D-037) | **Real — identical** |
| Universe, ranking, NAV gate, depth/skip, priority | Shared code | **Shared code** |
| Funds check | Broker funds API | Paper cash balance |
| Holdings check | Broker holdings API | Paper portfolio |
| Order placement | Broker order API | Paper fill engine |
| Order fills | Broker polling | Fill model, §4 |
| Charges | Broker + computed (D-024) | Computed only |
| Logging | Full (D-035) | **Full — identical, tagged `DRY`** |
| Static IP egress | Required | **Depends on the price source — see §3a** |

> **Correction.** An earlier note here claimed a dry run needs no static IP. That is only true
> if prices come from a non-broker source. Broker market-data APIs require a validated token
> and are subject to the broker's own IP policy, so a dry run on broker data needs the same
> IP plumbing as live trading. See §3a.

---

## 3a. Price source is selectable (D-043)

> "For a dry run, give an option for which source needs to be used for prices. We can tap
> into Yahoo Finance or any other free service, and hence the dry run won't require any IP.
> But since Yahoo Finance does not provide prices for all the ETFs, it's better to go with the
> broker. Do give both options."

`price_source ∈ { BROKER, FREE }`, selectable per run:

| | `BROKER` | `FREE` (e.g. Yahoo Finance) |
|---|---|---|
| Token needed | **Yes** — validated before the run | No |
| Static IP needed | **Yes**, per broker policy | **No** |
| ETF coverage | **Complete** — every NSE ETF | **Partial** — many Indian ETFs missing or stale |
| Data quality | Exchange-grade | Best-effort, unadjusted, gaps |
| Use for | Meaningful dry runs, live trading | End-to-end plumbing tests with zero credentials |

**Coverage is the deciding factor.** A free source that silently omits ETFs does not just
lose rows — it **changes the ranking**, because a missing ETF cannot be ranked, and the engine
would buy the wrong instrument while appearing to work perfectly.

Therefore:
1. `FREE` runs must **report coverage explicitly** — how many universe members got a price,
   and which did not — and mark every resulting artefact as coverage-limited.
2. A `FREE` run is a **plumbing test**, not a strategy validation. The UI must say so.
3. `BROKER` is the default selection for any run whose results will inform a real decision.

Q-170 covers which free provider, and whether an unmapped-symbol failure should block the run.

## 3. Mode is per trading account

`execution_mode ∈ { LIVE, DRY }` is a property of a **trading account** (D-037), so Person A
can run Upstox live while Person A · Dhan paper-trades the same strategy — which is also the
cleanest way to compare a config change against the live book.

**Switching modes never migrates state.** A paper portfolio and a live portfolio are separate
books that never merge. Going live means funding the real broker account and starting fresh;
the paper book is retained for its track record.

> ⚠️ A live account must never be able to read a paper holding, or vice versa. Every
> portfolio query is scoped by `(trading_account, execution_mode)`, and this is the single
> most important invariant to test.

---

## 4. The paper fill engine

Dry-run realism lives or dies here. Being optimistic about fills is the classic way paper
results flatter a strategy that then disappoints.

| Order | Rule |
|---|---|
| **Buy (limit at LTP + buffer)** | Fills at the limit price if the day's `LOW ≤ limit`, else remains pending |
| **Sell (limit at target)** | Fills at the limit price if the day's `HIGH ≥ limit`, else remains pending |
| **GTT sell** | Rests indefinitely; evaluated against each day's HIGH until triggered (mirrors D-003/D-029) |
| **Unfilled buy** | Expires at end of day, exactly as a real DAY order (D-029) |
| **Charges** | Computed from the broker's fee schedule (D-024) and deducted from paper cash — **brokerage, STT, exchange and SEBI fees, stamp duty, GST and DP charges on sells** |

**Deliberately conservative choices** — all open for discussion (Q-158):

1. Fills are evaluated against **daily OHLC**, not tick data, because that is what the daily
   snapshot cadence provides.
2. A fill is assumed at the **limit price**, never better — no favourable slippage.
3. **No partial fills** in v1; an order fills fully or not at all.
4. **No market-impact model.** Justified by the ₹10,000 order size against the 1-lakh-unit
   liquidity floor, but it is an assumption worth stating.

**Charges are mandatory in dry run, not optional** (D-044). The stated requirement: dry-run
results must include brokerage, DP charges, STT, GST and the rest, so that the output is
comparable to reality rather than a naive sell-price-minus-buy-price figure. A dry run also
accrues **cost of capital** (D-045), so paper returns are judged on exactly the same basis as
live ones.

---

## 5. Cadence — once a day, not live-polling

> "We need not make it very interactive, pulling the price every five minutes. Once a day —
> a snapshot of the dry portfolio at the start of the day and at the end of the day."

| Point | Captured |
|---|---|
| **Start of day** | Paper cash, holdings, each position's cost and quantity, opening prices, portfolio value |
| **Run** | The full decision trace (D-035) — ranking, gates, orders raised |
| **End of day** | Closing prices, fills resolved, realised and unrealised P&L, cash, portfolio value |

Two snapshot rows per account per day. That builds the equity curve the whole exercise
exists to produce, at negligible storage cost and without a live price feed.

---

## 6. Paper money

- The operator **adds paper money** to a dry-run account explicitly — an amount and a date,
  recorded as a `PAPER_FUNDING` ledger entry.
- Paper cash behaves exactly as real cash: buys debit it, sells credit it, computed charges
  debit it, and the **funds check blocks a buy when paper cash is short** just as it would
  live. That is precisely the behaviour the category-priority ordering exists to handle, so
  it must be exercised, not bypassed.
- Multiple funding events over time are supported, so returns can be measured against
  time-weighted capital rather than a single starting balance.

---

## 7. What the operator still has to do in dry-run mode

Dry run removes broker *order* credentials, not *data* credentials:

1. **Data API tokens must still be supplied and verified** — the requirement explicitly says
   the user still verifies the APIs for fetching data. Real prices are the point.
2. Configs must be complete and pass the pre-flight check (D-038) — **no defaults**, exactly
   as live.
3. The run is triggered the same way, through the same screen.

---

## 8. The Dry Run screen

| Section | Contents |
|---|---|
| **Mode banner** | Unmistakable `DRY RUN` marking, distinct colour, always visible |
| **Paper funding** | Current paper cash, add-funds control, funding history |
| **Portfolio** | Holdings with quantity, average cost, LTP, unrealised P&L %, resting sell target |
| **Equity curve** | Portfolio value over time from the daily snapshots |
| **Performance** | Realised P&L, unrealised P&L, total return, win rate, average holding period, computed charges paid |
| **Daily status** | The same ranked lists and gate outcomes as the live Daily Status screen |
| **Run log** | The same `.txt` log as live, tagged `DRY` |

**Every dry-run artefact is visually and textually marked `DRY`** — screens, logs, Telegram
messages, CSV exports and filenames. A paper result must never be mistakable for a real one.

---

## 9. Consequences for the build

This requirement **reorders the delivery plan in your favour**:

1. The paper gateway is the **natural first implementation**. The entire strategy engine can
   be built, run against live market data and validated end-to-end **before** a single broker
   order adapter is finished, before the static IPs exist, and before SEBI IP registration
   completes.
2. It gives the strategy maths a **test harness for free** — deterministic, repeatable, no
   money at risk.
3. It is the concrete reason for the modularity mandate. The rule to enforce in review:
   *no module below the gateway may know which mode it is running in.*

---

## 10. Open items

| ID | Item |
|---|---|
| Q-158 | Confirm the fill model in §4 — particularly no partial fills and no favourable slippage |
| Q-159 | Should dry-run and live P&L be comparable side by side on the reports screen? |
| Q-160 | Retention for paper portfolios — indefinite, or purge after going live? |
| Q-161 | Should a dry run be startable without the EC2 engine (it needs no static IP), e.g. on a schedule? |
