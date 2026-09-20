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

*Add to this list rather than dropping an idea in conversation — a deferred item with a
recorded reason is recoverable; one that was merely mentioned is not.*
