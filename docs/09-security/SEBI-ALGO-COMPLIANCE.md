# SEBI Retail Algo Trading Compliance

**Status:** 🔴 **Action required — affects who may be onboarded**
**Implements:** R2 (broker T&C review), D-074c
**Date:** 2026-09-20

> This is a design-constraints summary drawn from public sources, **not legal advice**.
> Confirm with each broker's compliance desk before going live.

---

## 1. The framework is already live

| Date | Milestone |
|---|---|
| 4 Feb 2025 | SEBI circular **SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013**, "Safer participation of retail investors in Algorithmic trading" |
| Oct 2025 | Brokers began registering retail algo products with the exchanges |
| 5 Jan 2026 | Non-compliant brokers barred from onboarding new retail API clients |
| **1 Apr 2026** | **Full framework mandatory for all Indian stockbrokers** |

**Today is 20 September 2026 — this framework is in force now**, not a future consideration.
Any API-based system placing orders in Indian markets operates inside it.

---

## 2. The good news — ATOM is almost certainly exempt from registration

### The threshold

Retail investors running **self-developed** algos must register with the exchange through
their broker **only if they exceed the Threshold Orders Per Second (TOPS)**, initially set at
**10 orders per second** per exchange/segment on both NSE and BSE. Below it, API orders are
**not tagged as algo orders** and no registration is required.

### ATOM's actual order rate

| | |
|---|---|
| Orders per run, per account | ~3 sells + ~3 buys = **~6** |
| Accounts | 3 (2 onboarded) |
| **Orders per day, whole system** | **~20** |
| Runs per day | 1 (D-057e) |
| **Peak orders per second** | **< 1** — and D-056b already imposes a rate limiter |

ATOM sits roughly **four orders of magnitude below the threshold.** It is a low-frequency,
once-daily, delivery-only system — close to the opposite of what the framework targets.

> ✅ **Design control (D-088):** the per-broker rate limiter (D-056b) is hereby a **compliance
> control**, not merely politeness. It must be **hard-capped well below 10 OPS** — 2 OPS is
> proposed — and that cap must be non-configurable upward without an explicit, logged override.
> Staying under TOPS is what keeps ATOM outside the registration regime.

---

## 3. 🔴 The constraint that matters — "family" is narrowly defined

SEBI permits a registered or self-developed algo to be used by the investor **and their
family**, and defines family precisely:

> **"'Family' for this purpose would mean self, spouse, dependent children and dependent
> parents."**
> — SEBI circular, 4 Feb 2025

**Not included:** siblings, non-dependent parents, adult independent children, cousins,
in-laws, friends, business partners.

### Why this matters to ATOM

D-004 recorded the posture as "self and family, own accounts", which placed ATOM outside the
compliance surface of an external service. **That conclusion holds only if every onboarded
investor falls inside SEBI's definition.**

> ✅ **Q-192 RESOLVED — the system is for family only, and in practice mostly the operator's
> own accounts across different brokers.**
>
> Multiple accounts belonging to the same person is the **simplest possible case**: "self" is
> unambiguously inside SEBI's definition, with no dependency test to argue about. ATOM is
> comfortably inside the retail self-use exemption.

**Onboarding policy (D-092): family only, as SEBI defines it.** Any future request to onboard
someone outside self / spouse / dependent children / dependent parents is a **regulatory
decision requiring fresh review**, not a configuration change. The onboarding flow should
record the relationship for each investor so this stays visible rather than tribal knowledge.

---

## 4. 🔴 The original brief's ambition conflicts with this

The founding brief stated:

> "We expect to keep the system open for all brokers… anyone having an account with any of
> these five brokers should be able to come on or connect with our utility and we should be
> able to place trades in their accounts as per our logic."

**That is the definition of being an algo provider.** SEBI treats an entity providing algo
trading to others through broker APIs as **acting as an agent of the broker**, requiring
empanelment with the broker, exchange registration of the algo, and Algo ID tagging on every
order. It is not a matter of scale or of charging a fee — it is about *whose* account is being
traded.

**The design is unaffected; the business model is.** The multi-broker, multi-account
architecture is correct and worth building either way. But onboarding investors outside the
family definition is a **regulatory decision, not a configuration change**, and should be
taken deliberately.

*Recommendation: build for family use now, and keep the account-onboarding path clean enough
that a future registered-provider posture is a compliance exercise rather than a rewrite.*

---

## 5. Other framework provisions relevant to the build

| Provision | Effect on ATOM |
|---|---|
| **Open APIs banned** | Use each broker's official, registered API with proper credentials. Already the design (D-056b) |
| **Algo ID tagging** | Every order from a *registered* algo must carry an exchange-assigned Algo ID. **Not applicable below TOPS** — but the order-placement layer should keep a tag field available, so adding it later is a field, not a refactor |
| **Algo providers act as broker agents** | Relevant only if §4 applies |
| **Static IP / API whitelisting** | Already the core of the infrastructure design (D-005, D-007) |
| **Broker-side rate limits** | Dhan 10/s orders, Zerodha 10/s per API key (matrix §3) — consistent with TOPS |

---

## 6. Actions

| # | Action | Owner |
|---|---|---|
| C1 | **Answer Q-192** — Person B's relationship to the operator | Operator |
| C2 | Write to each broker's compliance desk confirming self-use API trading is permitted for the intended accounts. Zerodha directs such queries to `kiteconnect@zerodha.com` | Operator |
| C3 | Implement the hard TOPS cap (D-088) and log peak observed OPS per run | Build |
| C4 | Keep an `algo_id` field in the order schema, unused for now | Build |
| C5 | Read each broker's API terms of service for clauses on third-party account access | Research |

---

## Sources

- [SEBI — Safer participation of retail investors in Algorithmic trading (4 Feb 2025)](https://www.sebi.gov.in/legal/circulars/feb-2025/safer-participation-of-retail-investors-in-algorithmic-trading_91614.html)
- [SEBI — Extension of implementation timeline (Sep 2025)](https://www.sebi.gov.in/legal/circulars/sep-2025/extension-of-timeline-for-implementation-of-sebi-circular-dated-february-04-2025-on-safer-participation-of-retail-investors-in-algorithmic-trading-_96979.html)
- [NSE circular — Investigation department](https://nsearchives.nseindia.com/content/circulars/INVG67858.pdf)
- [Zerodha Z-Connect — Explaining the latest SEBI algo trading regulations](https://zerodha.com/z-connect/business-updates/explaining-the-latest-sebi-algo-trading-regulations)
- [Kite Connect forum — algo provider permissions](https://kite.trade/forum/discussion/13595/about-taking-permission-from-any-authority-to-providing-services-of-algotrading-by-using-zerodha-api)
- [AlgoIP — TOPS threshold summary](https://algoip.in/compliance)
