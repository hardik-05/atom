# ATOM — Documentation Index

**A multi-broker, multi-account mean-reversion ETF trading system for the Indian market.**

---

## Reading order

Start here, in this order:

1. [`00-discovery/REQUIREMENTS-AS-CAPTURED.md`](./00-discovery/REQUIREMENTS-AS-CAPTURED.md)
   — the brief, restated faithfully. **The contract.** Every other document traces back to it.
2. [`00-discovery/OPEN-QUESTIONS.md`](./00-discovery/OPEN-QUESTIONS.md)
   — 127 numbered questions with proposed defaults. **Design is blocked on the 🔴 items.**

---

## Planned document set

Documents are written **after** the question bank is answered, in the batches below. Nothing
below exists yet; this is the map, so you can tell me now if a document is missing, wrongly
scoped, or not worth writing.

### Batch 1 — Architecture (written first, revised as later batches land)

| # | Document | Covers |
|---|---|---|
| 01 | `01-architecture/SYSTEM-OVERVIEW.md` | Context diagram, components, trust boundaries, the full request path from Telegram to broker |
| 02 | `01-architecture/RUN-LIFECYCLE.md` | End-to-end sequence of one execution run, with failure branches |
| 03 | `01-architecture/MODULE-MAP.md` | Python package layout, module boundaries, what may import what |
| 04 | `01-architecture/CONFIGURATION-MODEL.md` | Every config value, its scope, defaults, validation, versioning and audit |

### Batch 2 — Infrastructure

| # | Document | Covers |
|---|---|---|
| 05 | `02-infrastructure/AWS-TOPOLOGY.md` | VPC, subnets, security groups, IAM roles, EC2 lifecycle |
| 06 | `02-infrastructure/STATIC-IP-DESIGN.md` | Per-account source-IP egress: ENIs, policy routing or per-IP proxies; verification procedure |
| 07 | `02-infrastructure/INSTANCE-SIZING-AND-COST.md` | Instance type vs Elastic IP capacity vs ap-south-1 cost, at 2 / 5 / 10 / 25 accounts; one-big-box vs split-box analysis |
| 08 | `02-infrastructure/LAMBDA-AND-TELEGRAM-BOT.md` | Bot command surface, authorisation, Lambda→EC2 start/stop, status reporting |
| 09 | `02-infrastructure/DEPLOYMENT-AND-RELEASE.md` | Image build, deploy to EC2, Render site deploy, rollback |

### Batch 3 — Brokers

| # | Document | Covers |
|---|---|---|
| 10 | `03-brokers/BROKER-ADAPTER-CONTRACT.md` | The interface every broker must implement; canonical models; error taxonomy; how to onboard broker #6 |
| 11 | `03-brokers/UPSTOX.md` | Auth flow, endpoints, order semantics, GTT support, rate limits, quirks |
| 12 | `03-brokers/DHAN.md` | Same |
| 13 | `03-brokers/ZERODHA.md` | Same |
| 14 | `03-brokers/GROWW.md` | Same |
| 15 | `03-brokers/SHOONYA.md` | Same |
| 16 | `03-brokers/BROKER-CAPABILITY-MATRIX.md` | Side-by-side: order types, GTT/GTC, holdings shape, ledger access, charges exposure, rate limits |
| — | `99-vendor-docs/` | Raw vendor documentation snapshots, dated |

### Batch 4 — Strategy

| # | Document | Covers |
|---|---|---|
| 17 | `04-strategy/UNIVERSE-CONSTRUCTION.md` | ETF discovery, categorisation, the weekly volume job, thresholds, snapshots |
| 18 | `04-strategy/MEAN-REVERSION-ENGINE.md` | Lookback, mean/median, deviation ranking, worked examples with numbers |
| 19 | `04-strategy/BUY-LOGIC.md` | Depth/skip rules, category priority, funds checks, sizing, enable/disable |
| 20 | `04-strategy/SELL-LOGIC.md` | Target computation, tick rounding, GTT vs DAY, duplicate prevention |
| 21 | `04-strategy/AVERAGING.md` | Loss buckets, one-click average, weighted-average recomputation, sell-order replacement |
| 22 | `04-strategy/TAX-LOSS-HARVESTING.md` | Gains computation, correlation model, proxy selection, synthetic cost basis, approval flow, partial-failure handling |
| 23 | `04-strategy/ORDER-LIFECYCLE.md` | Placement, polling, partial fills, rejections, reconciliation across engine restarts |

### Batch 5 — Data

| # | Document | Covers |
|---|---|---|
| 24 | `05-data/DATABASE-SCHEMA.md` | Every table, column, type, constraint and index, with an ER diagram |
| 25 | `05-data/DATA-DICTIONARY.md` | Field-by-field meaning and provenance |
| 26 | `05-data/MARKET-DATA-PIPELINE.md` | Source, backfill, corporate actions, gap detection |
| 27 | `05-data/TRACEABILITY.md` | How to answer "why was this trade made?" purely from SQL |

### Batch 6 — Web console

| # | Document | Covers |
|---|---|---|
| 28 | `06-web-app/UI-ARCHITECTURE.md` | Where the console runs, routing, state, API contract |
| 29 | `06-web-app/SCREEN-SPECS.md` | Every screen: purpose, data sources, actions, empty/error states, what it explicitly does not do |
| 30 | `06-web-app/DESIGN-SYSTEM.md` | Navy-blue financial theme: palette, type, components, tables, status colours |
| 31 | `06-web-app/AUTH-AND-SESSIONS.md` | Login, roles, token handling, engine-liveness gating |

### Batch 7 — Observability, reporting, security, operations

| # | Document | Covers |
|---|---|---|
| 32 | `07-observability/LOGGING-SPEC.md` | Event taxonomy, the human-readable `.txt` format with a full worked sample, redaction |
| 33 | `07-observability/LOG-ARCHIVAL.md` | S3 lifecycle, Google Drive archive, Telegram delivery, naming |
| 34 | `08-reporting/CHARGES-MODEL.md` | Brokerage, STT, exchange, SEBI, stamp duty, GST, DP — per broker, computed vs fetched |
| 35 | `08-reporting/UNIFIED-PNL-MODEL.md` | Normalising P&L and ledger across brokers into one model |
| 36 | `08-reporting/REPORT-SPECS.md` | Every report, its columns, and its CSV export |
| 37 | `09-security/THREAT-MODEL.md` | Assets, adversaries, controls, kill switch, spend caps |
| 38 | `09-security/SECRETS-AND-CREDENTIALS.md` | Where every secret lives and how it rotates |
| 39 | `10-operations/RUNBOOK.md` | Daily operating procedure, and what to do when each thing breaks |
| 40 | `10-operations/TESTING-STRATEGY.md` | Unit, contract, dry-run, phased go-live |

### Diagrams

`diagrams/` holds the Mermaid sources and rendered exports for: system context, run
sequence, buy decision tree, sell/averaging state machine, harvesting flow, ER diagram,
network/IP topology, and the Telegram→Lambda→EC2 lifecycle.

---

## Status

| Batch | Status |
|---|---|
| 00 — Discovery | ✅ Complete, awaiting your answers |
| 01–07 | ⏸ Blocked on the 🔴 questions |

*Last updated: 2026-09-16*
