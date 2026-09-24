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

> ⚠️ **Read §7 before relying on §2.** Broker documentation fetched 2026-09-24 shows the five
> brokers do **not** agree on whether the TOPS threshold is the only trigger for registration.
> Section 2's conclusion is sound on Upstox's reading and **wrong on Shoonya's**. The section is
> left standing as written so the change is visible; §7 supersedes it where they conflict.

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
| C4 | Keep an `algo_id` field in the order schema, unused for now — **upgraded by C6** | Build |
| C6 | 🔴 **Ask each of the five brokers directly whether an empanelled Algo ID is required for API orders at < 10 OPS** (Q-268 / X8). Documentation does not settle it | Operator |
| C7 | Complete **EDIS authorization** on each Upstox account before the first live sell (Q-270) | Operator |
| C8 | Register the static egress IP with each broker, and record the earliest permitted change date (Dhan locks for 7 days) | Operator |
| C5 | Read each broker's API terms of service for clauses on third-party account access | Research |

---

## Sources

- [SEBI — Safer participation of retail investors in Algorithmic trading (4 Feb 2025)](https://www.sebi.gov.in/legal/circulars/feb-2025/safer-participation-of-retail-investors-in-algorithmic-trading_91614.html)
- [SEBI — Extension of implementation timeline (Sep 2025)](https://www.sebi.gov.in/legal/circulars/sep-2025/extension-of-timeline-for-implementation-of-sebi-circular-dated-february-04-2025-on-safer-participation-of-retail-investors-in-algorithmic-trading-_96979.html)
- [NSE circular — Investigation department](https://nsearchives.nseindia.com/content/circulars/INVG67858.pdf)
- [Zerodha Z-Connect — Explaining the latest SEBI algo trading regulations](https://zerodha.com/z-connect/business-updates/explaining-the-latest-sebi-algo-trading-regulations)
- [Kite Connect forum — algo provider permissions](https://kite.trade/forum/discussion/13595/about-taking-permission-from-any-authority-to-providing-services-of-algotrading-by-using-zerodha-api)
- [AlgoIP — TOPS threshold summary](https://algoip.in/compliance)

---

## 7. Update — 2026-09-24, after reading the brokers' own compliance pages

Round 2 of the broker research ([`API-REFERENCE-VERIFIED.md`](../03-brokers/API-REFERENCE-VERIFIED.md))
read each vendor's developer documentation directly. Two of the five publish a compliance page,
and **they contradict each other on the question §2 answers**.

### 7.1 What is now confirmed, and confirmed as live

All of this took effect **1 April 2026** — nearly six months before today's date — so it is
current operating condition, not preparation.

> "We have successfully deployed the latest regulatory changes… API trading now requires a
> **registered static IP** and **Algo registration** for strategies exceeding **10 orders per
> second (OPS)**." — [Upstox, 31 Mar 2026](https://community.upstox.com/t/important-update-regulatory-changes-for-api-and-algo-trading-are-now-live/14874)

| Change | Status | Effect on ATOM |
|---|---|---|
| **Registered static IP mandatory** | Live, enforced by Upstox (`UDAPI1154`), Dhan and Shoonya | ✅ Already designed for — D-009…D-011. **Validated, not invalidated** |
| **Market orders no longer permitted via API** | Live; Market Price Protection on by default | ✅ ATOM places limits only (D-057). The `MARKET` type should now be removed from the live adapter surface entirely rather than kept as a fallback |
| **Algo registration above 10 OPS** | Live | ✅ ATOM caps at 2 OPS (D-088/D-149) — **on Upstox's reading** |
| **MCX API trading disabled at Upstox** | Live, "temporarily" | No effect — ATOM's commodity ETFs are NSE CASH instruments |

The static-IP mandate is worth dwelling on: ATOM designed a per-investor static egress IP from
the brief's own requirements, before this was enforced. The regulation has since made that
design compulsory. **The infrastructure work is validated by the regulation, not threatened by
it.**

### 7.2 🔴 The disagreement — and it goes against §2

**Shoonya reads the same circular far more strictly than Upstox:**

> "SEBI's algo trading circular (**SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013**) requires
> **every order placed through an API — not just orders from registered algo strategies** — to
> carry a broker-empanelled Algo ID. This applies whether you're running a formally registered
> strategy or a personal script hitting the same order endpoints."
>
> "Full enforcement applies from April 1, 2026. Orders placed via the API without a valid,
> empanelled Algo ID after that date are **expected to be rejected at the exchange level**, not
> just flagged after the fact."
>
> — [Shoonya, SEBI Algo ID Framework](https://shoonya.com/api-documentation/algo-compliance)

Its applicability table is explicit:

| Integration type | Algo ID required? |
|---|---|
| Manual orders via the Shoonya app/terminal | No |
| **Personal script placing orders via the API** | **Yes** |
| Vendor platform placing orders for clients | Yes, per registered strategy |
| Read-only integrations (quotes, positions, order book) | No |

ATOM is precisely row 2.

### 7.3 Where that leaves §2

I wrote in §2 that ATOM is "almost certainly exempt from registration" because it sits four
orders of magnitude below TOPS. **That reasoning is correct about TOPS and may be beside the
point.** TOPS governs the *rate* threshold above which a strategy must be registered as a
high-frequency algo. Shoonya is describing a *different* obligation — a per-order Algo ID tag
on all API order flow, irrespective of rate.

Both can be true at once: a low-rate strategy needing no TOPS registration but still needing an
empanelled Algo ID to tag its orders. If so, §2's conclusion — that ATOM needs to do nothing —
is wrong, and the gap is not academic: Shoonya says non-compliant orders are **rejected at the
exchange**, which would mean ATOM places orders that never reach the market.

**I am not going to resolve this from documentation.** Shoonya's own page hedges on the field
name ("confirm the exact field name with your onboarding contact, as it is being finalized
across the industry"), and Upstox's silence on a per-order requirement is not evidence of its
absence. This needs an answer from each broker's compliance desk.

### 7.4 What ATOM does about it now

1. **Ask.** Action **C6** — put the question to all five brokers in writing, alongside the C2
   self-use query that is already outstanding. Tracked as **Q-268** and external blocker **X8**.
2. **Build for the strict reading.** The broker adapter contract carries an **optional
   per-account `algo_id` / `algo_name`**, defaulting to unset, mapped by each adapter to its
   broker's field — `X-Algo-Name` header on Upstox, an order-payload field on Shoonya, to be
   confirmed elsewhere. This upgrades C4 from "keep a field, unused" to "wire it through the
   whole path, unset by default". Building it now costs a field and a header; retrofitting it
   after a rejection costs a trading day and an unexplained failed run.
3. **Log it.** Shoonya's guidance — "log the Algo ID alongside every order in your own audit
   trail; SEBI's framework expects **strategy-level traceability**, not just account-level" — is
   good practice under either reading, and ATOM's per-universe run model already provides the
   strategy boundary to hang it on.
4. **Do not go live on any broker until its answer is in.** This is an addition to the go-live
   checklist, not to the build schedule: phases 0–5 are unaffected, since dry-run mode places no
   orders at all (D-045).

### 7.5 One more thing Shoonya's page says that ATOM should heed

> "**Keep static strategies static.** Any change to an already-registered strategy's logic may
> require re-registration."

If an Algo ID is required, ATOM's configurability becomes a compliance surface. A threshold the
operator can change per universe, per broker and per category (D-030) is exactly the kind of
change a strict reading might treat as a new strategy. This is another reason config versioning
(D-056) matters: it produces the record of what changed and when. Raised as **Q-277**.
