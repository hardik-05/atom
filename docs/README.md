# ATOM — Documentation Index

**A multi-broker, multi-account mean-reversion ETF trading system for the Indian market.**

**Status:** 🟢 **Design complete.** Every document below exists. Remaining work is code, plus the
external blockers in [`DEVELOPMENT-READINESS.md`](00-discovery/DEVELOPMENT-READINESS.md).

---

## Where to start

| If you are | Read, in order |
|---|---|
| **New to the project** | [SYSTEM-OVERVIEW](01-architecture/SYSTEM-OVERVIEW.md) → [RUN-LIFECYCLE](01-architecture/RUN-LIFECYCLE.md) → [DIAGRAMS](12-diagrams/DIAGRAMS.md) |
| **About to write code** | [MODULE-MAP](01-architecture/MODULE-MAP.md) → [DATABASE-SCHEMA](05-data/DATABASE-SCHEMA.md) → [ADAPTER-ENGINE](03-brokers/ADAPTER-ENGINE.md) |
| **Building one broker** | [ADAPTER-ENGINE](03-brokers/ADAPTER-ENGINE.md) → that broker's file in [`03-brokers/adapters/`](03-brokers/adapters/) |
| **Asking "why is it like this?"** | [DECISIONS](00-discovery/DECISIONS.md) — D-001…D-209, in rounds |
| **Operating it** | [RUNBOOK](10-operations/RUNBOOK.md) |
| **Reviewing scope** | [REQUIREMENTS-AS-CAPTURED](00-discovery/REQUIREMENTS-AS-CAPTURED.md) — the contract |

> **[`DECISIONS.md`](00-discovery/DECISIONS.md) is the spine.** Every document traces to it, and it
> records reversals as well as conclusions — including places where an earlier answer of mine was
> wrong and was corrected.

---

## 00 · Discovery

| Document | Contains |
|---|---|
| [REQUIREMENTS-AS-CAPTURED](00-discovery/REQUIREMENTS-AS-CAPTURED.md) | The brief restated verbatim, with 10 identified contradictions |
| [DECISIONS](00-discovery/DECISIONS.md) | **D-001 … D-209** across 31 rounds — the authoritative record |
| [OPEN-QUESTIONS](00-discovery/OPEN-QUESTIONS.md) | The original 127-question bank |
| [PENDING-QUESTIONS](00-discovery/PENDING-QUESTIONS.md) | What is still open |
| [DEVELOPMENT-READINESS](00-discovery/DEVELOPMENT-READINESS.md) | Audit + **external blockers X1…X10** |
| [V2-BACKLOG](00-discovery/V2-BACKLOG.md) | Deliberately deferred, with the trade-off each defers |

## 01 · Architecture

| Document | Contains |
|---|---|
| [SYSTEM-OVERVIEW](01-architecture/SYSTEM-OVERVIEW.md) | The map · five defining properties · layer boundaries · 12 non-negotiables · what ATOM is **not** |
| [RUN-LIFECYCLE](01-architecture/RUN-LIFECYCLE.md) | The seven phases · pre-flight gates · failure taxonomy |
| [MODULE-MAP](01-architecture/MODULE-MAP.md) | Tree · the import rule · forbidden patterns · build order |
| [CONFIGURATION-MODEL](01-architecture/CONFIGURATION-MODEL.md) | Hierarchy · versioning · **no defaults** |
| [EXECUTION-MODES-AND-DRY-RUN](01-architecture/EXECUTION-MODES-AND-DRY-RUN.md) | The `OrderGateway` seam |

## 02 · Infrastructure

| Document | Contains |
|---|---|
| [AWS-TOPOLOGY](02-infrastructure/AWS-TOPOLOGY.md) | VPC · IAM (incl. explicit denies) · lifecycle · what is deliberately absent |
| [STATIC-IP-AND-PROXY](02-infrastructure/STATIC-IP-AND-PROXY.md) | Per-investor egress · why a proxy not source binding · registration ordering |
| [INSTANCE-SIZING-AND-COST](02-infrastructure/INSTANCE-SIZING-AND-COST.md) | Why splitting instances never saves money |
| [LAMBDA-AND-TELEGRAM](02-infrastructure/LAMBDA-AND-TELEGRAM.md) | Control plane · **no trading commands** |
| [DEPLOYMENT](02-infrastructure/DEPLOYMENT.md) | Environments · migrations · domain switch · rebuild |

## 03 · Brokers

| Document | Contains |
|---|---|
| [ADAPTER-ENGINE](03-brokers/ADAPTER-ENGINE.md) | **The two-way translation layer** · 8 canonical models · capability profile · error taxonomy |
| [BROKER-CAPABILITY-MATRIX](03-brokers/BROKER-CAPABILITY-MATRIX.md) | One-page comparison of all five |
| [API-REFERENCE-VERIFIED](03-brokers/API-REFERENCE-VERIFIED.md) | Round-2 research, every claim citing its vendor page |
| [BROKER-ONBOARDING-PLAN](03-brokers/BROKER-ONBOARDING-PLAN.md) | Phased onboarding |
| [SDK-EVALUATION](03-brokers/SDK-EVALUATION.md) | Why raw HTTP, not vendor SDKs |
| [adapters/ZERODHA](03-brokers/adapters/ZERODHA-ADAPTER.md) | Hardest identity · **per-session** sell authorisation |
| [adapters/GROWW](03-brokers/adapters/GROWW-ADAPTER.md) | Strongest identity · required idempotency key |
| [adapters/UPSTOX](03-brokers/adapters/UPSTOX-ADAPTER.md) | ISIN *is* the token · EDIS gate · tick-size trap |
| [adapters/DHAN](03-brokers/adapters/DHAN-ADAPTER.md) | Best surface · 7-day IP lock · writes-only whitelisting |
| [adapters/SHOONYA](03-brokers/adapters/SHOONYA-ADAPTER.md) | Weakest · self-contradicting docs · GTT unpublished |
| Round-1 notes | [UPSTOX](03-brokers/UPSTOX.md) · [DHAN](03-brokers/DHAN.md) · [ZERODHA](03-brokers/ZERODHA.md) · [GROWW](03-brokers/GROWW.md) · [SHOONYA](03-brokers/SHOONYA.md) |

## 04 · Strategy

| Document | Contains |
|---|---|
| [DEVIATION-METRIC-ANALYSIS](04-strategy/DEVIATION-METRIC-ANALYSIS.md) | Percentage vs rupee, with the 83× dispersion evidence |
| [SELL-LOGIC](04-strategy/SELL-LOGIC.md) | GTT · cancel-all-first · **tranches** |
| [HARVEST-COST-BASIS](04-strategy/HARVEST-COST-BASIS.md) | **The synthetic basis in full** — three worked cases, tranches, no chaining |
| [NAV-PREMIUM-CHECK](04-strategy/NAV-PREMIUM-CHECK.md) | The gate that disables global ETFs at 2% |
| [SECTOR-BUCKETS](04-strategy/SECTOR-BUCKETS.md) | Three-tier taxonomy |
| [BUCKET-MANAGEMENT](04-strategy/BUCKET-MANAGEMENT.md) | Classification lifecycle |
| [CORPORATE-ACTIONS](04-strategy/CORPORATE-ACTIONS.md) | Splits, bonuses, the three-stage lifecycle |
| [EXCLUSION-AND-FREEZE](04-strategy/EXCLUSION-AND-FREEZE.md) | Block → review → release |

## 05 · Data

| Document | Contains |
|---|---|
| [DATABASE-SCHEMA](05-data/DATABASE-SCHEMA.md) | **38 tables**, full DDL, invariants as CHECK constraints |
| [HOLDINGS-ATTRIBUTION](05-data/HOLDINGS-ATTRIBUTION.md) | The reconciliation identity · ownership vs sellability |

## 06 · Web

| Document | Contains |
|---|---|
| [UI-ARCHITECTURE](06-web/UI-ARCHITECTURE.md) | Static bundle + thin API · offline as the normal state |
| [DESIGN-SYSTEM](06-web/DESIGN-SYSTEM.md) | Navy, light **and** dark · number rendering · no bare P&L |
| [SCREEN-SPECS](06-web/SCREEN-SPECS.md) | **13 screens**, field by field |
| [AUTH-AND-ACCESS](06-web/AUTH-AND-ACCESS.md) | One admin · TOTP · what a session cannot do |

## 07 · Logging

| Document | Contains |
|---|---|
| [LOGGING-SPEC](07-logging/LOGGING-SPEC.md) | Two tiers · why the decision record is **not** a log |
| [ARCHIVAL](07-logging/ARCHIVAL.md) | Retention · four permanent copies · tamper resistance |

## 08 · Reporting

| Document | Contains |
|---|---|
| [UNIFIED-PNL](08-reporting/UNIFIED-PNL.md) | **Three numbers**, why none can be collapsed |
| [CHARGES-MODEL](08-reporting/CHARGES-MODEL.md) | Components · contrast · 🔴 **provisional STT rates** |
| [COST-OF-CAPITAL](08-reporting/COST-OF-CAPITAL.md) | Three buckets · Actual/365 |
| [TAXATION-MODEL](08-reporting/TAXATION-MODEL.md) | Indian ETF taxation by asset class |
| [TAX-ENGINE](08-reporting/TAX-ENGINE.md) | Tax FIFO · set-off · exemption |
| [REPORT-SPECS](08-reporting/REPORT-SPECS.md) | **12 reports**, each naming the tables it reads |

## 09 · Security

| Document | Contains |
|---|---|
| [THREAT-MODEL](09-security/THREAT-MODEL.md) | 10 threats by severity · **where the design is weakest** |
| [SECRETS-MANAGEMENT](09-security/SECRETS-MANAGEMENT.md) | Paths not secrets · daily destruction · 🔴 **X1** |
| [SEBI-ALGO-COMPLIANCE](09-security/SEBI-ALGO-COMPLIANCE.md) | The framework · why no Algo ID is required |

## 10 · Operations

| Document | Contains |
|---|---|
| [RUNBOOK](10-operations/RUNBOOK.md) | Daily routine · 9 incident procedures · **3 things never to do** |
| [TESTING-STRATEGY](10-operations/TESTING-STRATEGY.md) | Layer by layer · the two mandatory adapter tests |

## 11–12 · Prior art and diagrams

| Document | Contains |
|---|---|
| [EXISTING-SYSTEM-ANALYSIS](11-prior-art/EXISTING-SYSTEM-ANALYSIS.md) | The archived MetaAlgo system — dead code, reference only |
| [DIAGRAMS](12-diagrams/DIAGRAMS.md) | 9 Mermaid diagrams, each answering what prose answers badly |

---

## Scripts and data

| Path | Contains |
|---|---|
| `scripts/build_etf_buckets.py` | Three-tier taxonomy generator |
| `scripts/fetch_etf_reference_data.py` | 4 independent sources + local fallback |
| `scripts/verify_egress_ip.py` | **Fails closed**; detects shared addresses |
| `data/reference/` | 311/311 ETF ISINs resolved — the authoritative tick-size source (D-209) |
| `data/buckets/` | 311 classified ETFs |

---

## The ten things that define this system

If you read nothing else:

1. **Percentage deviation, not rupee** — 83× price dispersion inside one bucket makes rupees meaningless (D-149)
2. **The universe is a first-class entity** — named, configured, run and compared independently (D-156)
3. **One lot per fill, and two different FIFOs** — universe FIFO ≠ tax FIFO (D-166, D-167)
4. **Two cost bases per lot** — synthetic drives strategy, actual drives tax (D-188…D-206)
5. **Brokers are normalised at one boundary** — nothing broker-shaped leaks past the adapter (D-185)
6. **Limit orders only, delivery only, no margin** (D-174, D-207)
7. **Per-investor static egress IP** — designed before regulation required it, now mandatory (D-173)
8. **Dry and live share every line of code** — which is what makes dry-run output mean something (D-045)
9. **Every decision is reconstructible from SQL** — the rationale lives in `run_candidate`, not in a log (D-035)
10. **No defaults anywhere** — an unset value blocks the run rather than guessing (D-037)

---

## Still open

| | |
|---|---|
| 🔴 **X1** | Exposed Upstox credentials, **unrotated** |
| 🔴 **X2** | Broker T&C review — governs whether API access is permitted at all |
| 🔴 **Q-313** | STT rate for ETF units — possibly 100× wrong, affects every `unit_cost` |
| 🔴 **Q-271** | Shoonya GTT surface unpublished |
| 🔴 **Q-310** | Shoonya token transport — its own docs contradict each other |
| **X3…X10** | Supabase · AWS · Elastic IPs · credentials · slab · EDIS · DDPI |

Full list in [`DEVELOPMENT-READINESS.md`](00-discovery/DEVELOPMENT-READINESS.md) and
[`PENDING-QUESTIONS.md`](00-discovery/PENDING-QUESTIONS.md).
