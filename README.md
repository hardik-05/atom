# ATOM

A multi-broker, multi-account automated **mean-reversion ETF trading system** for the
Indian market.

> **Status: design phase.** No application code yet. The system is being specified in full
> before implementation begins.

## What it does

- Ranks a liquidity-filtered universe of NSE ETFs — **equity**, **metals** and **global** —
  by how far each has deviated below its own rolling mean.
- Buys the most oversold candidate in each enabled category, skipping anything already
  held, up to a configurable depth.
- Places a matching limit sell order at a configurable profit target as soon as a buy fills.
- Supports one-click position averaging, with automatic recomputation and replacement of
  the resting sell order.
- Proposes human-approved **tax-loss harvesting** using correlation-matched proxy ETFs, so
  sector exposure is preserved while losses are booked against short-term gains.
- Produces month-on-month financials net of Indian brokerage, depository and statutory
  charges, per broker and consolidated per investor.

## How it runs

Telegram bot → AWS Lambda → on-demand EC2 (carrying one static IP per investor, as SEBI
requires) → broker APIs. The instance is brought down after each session to control cost.
An always-on static site on Render fronts the console. Supabase is the system of record.

## Documentation

**Start at [`docs/README.md`](./docs/README.md).**

The brief is captured in
[`docs/00-discovery/REQUIREMENTS-AS-CAPTURED.md`](./docs/00-discovery/REQUIREMENTS-AS-CAPTURED.md);
everything still undecided is in
[`docs/00-discovery/OPEN-QUESTIONS.md`](./docs/00-discovery/OPEN-QUESTIONS.md).

## Disclaimer

This software places real orders in real brokerage accounts. Nothing in this repository is
investment or tax advice.
