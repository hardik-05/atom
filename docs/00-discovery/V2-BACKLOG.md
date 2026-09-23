# ATOM — Version 2 Backlog

**Status:** Parked, deliberately out of v1 scope
**Purpose:** Items considered and consciously deferred, so they are not silently forgotten or
accidentally built.

| # | Item | Why deferred | Notes for when it is built |
|---|---|---|---|
| V2-1 | **Backtest harness** | Not needed to go live; the strategy parameters are being validated by dry run instead | The 8 quarters of price history (D-058a) are already stored, so the data requirement is satisfied. Would let lookback, depth and target % be chosen from evidence rather than intuition |
| V2-2 | **Dry-run vs live P&L comparison** | Dry run is a phase, not a permanent parallel system — it runs for a month or two and is then retired | Only worth building if dry run is ever revived for testing strategy changes against a live book |
| V2-3 | **Benchmark comparison (NIFTY 50)** | Not required for v1 reporting | Schema does not preclude it |
| V2-4 | **Corporate-action data feed** | The detect-and-deactivate approach (D-064) covers the risk without one | Would close the small-ratio-split blind spot (Q-186), e.g. a 4:5 split at exactly −20% |
| V2-5 | **Investor-facing read-only access** | v1 is admin-only (D-040) | Supabase RLS is being designed from day one (Q-074) specifically so this is not a rewrite |
| V2-6 | **Automated harvest execution** | Harvesting stays human-approved by design | |
| V2-7 | **Intraday price polling** | Daily snapshots are sufficient (D-041) | |
| V2-8 | **BSE support** | NSE only in v1 (D-056b) | Schema carries an exchange column |
| V2-9 | **Advance-tax instalment tracking** | Volumes are far too small to trigger a meaningful instalment obligation | Instalments fall due 15 Jun / 15 Sep / 15 Dec / 15 Mar at 15/45/75/100%, with interest under s.234B and s.234C if underpaid. Becomes relevant once annual realised gains are large enough that the interest exceeds the nuisance of tracking it |
| V2-10 | **s.94(7) dividend-stripping check on harvests** | Not worth the complexity at current volume | If a harvest sale falls within 3 months either side of a distribution record date, the loss is **disallowed to the extent of the dividend** — silently defeating the harvest. Needs ETF record-date data, which no current source provides. Revisit when harvest volume makes a disallowed loss material |
| V2-11 | **s.94(8) bonus stripping** | Same reasoning as V2-10 | Rarer for ETFs than dividend stripping |
| V2-12 | **Dividend income in the tax view** | Out of scope by design (D-099, D-128) | Dividends are *income from other sources* at slab rate. They do **not** consume the capital-gains exemption or set-off pools, so excluding them leaves the capital-gains computation correct. Only relevant if ATOM ever reports total tax rather than capital-gains tax |

*Add to this list rather than dropping an idea in conversation — a deferred item with a
recorded reason is recoverable; one that was merely mentioned is not.*
