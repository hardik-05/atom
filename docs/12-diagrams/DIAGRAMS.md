# Diagrams

**Status:** 🟢 Complete
**Date:** 2026-09-26
**Format:** Mermaid — renders natively on GitHub, so these stay readable in the repository

Eight diagrams. Each one answers a question that prose answers badly.

---

## 1. System context

```mermaid
flowchart TB
    OP([Operator]) -->|Telegram| TG[Telegram Bot]
    OP -->|HTTPS + TOTP| CON[Web Console]
    TG --> LAM[Lambda: atom-control]
    LAM -->|start / stop| EC2
    subgraph EC2["EC2 · t3a.small · ~20 min/day"]
        CON --> ENG[Run Orchestrator]
        ENG --> ADP[Adapter Engine × 5]
        ADP --> PX[Forward proxies<br/>one per investor]
    end
    PX -->|EIP-A| BRK[(Five brokers)]
    PX -->|EIP-B| BRK
    ENG --> DB[(Supabase<br/>38 tables)]
    ENG --> SSM[(SSM<br/>tokens by path)]
    ENG --> S3[(S3 + Glacier)]
    ENG --> GD[(Google Drive)]
    ENG -->|alerts, log files| TG
    CON -.->|engine down| RND[Render static site]
```

The two things this shows that prose does not: **the operator has two separate paths in** (Telegram
for control, browser for trading), and **every broker call leaves through a proxy** — there is no
direct path from the engine to a broker.

---

## 2. Layers and the import rule

```mermaid
flowchart TB
    WEB[web / frontend] --> REP[reporting]
    REP --> STR[strategy]
    STR --> ADP[adapters]
    ADP --> DOM[domain]
    STR --> DOM
    REP --> DOM
    ORC[orchestration] --> STR
    ORC --> ADP
    ORC --> PER[persistence]
    REP --> PER
    PER --> DOM
    ADP -.->|"forbidden"| PER
    STR -.->|"forbidden"| ADP2[a broker name]
```

`domain` imports nothing. `adapters` cannot reach `persistence`. `strategy` never names a broker.
Enforced by import-linter in CI, because a documented convention decays and a failing build does not.

---

## 3. The seven phases of a run

```mermaid
flowchart TB
    START([execute]) --> P0

    subgraph READONLY["read-only · nothing sent to a broker"]
        P0[0 · PRE-FLIGHT<br/>egress IP · token · calendar · sell-auth]
        P1[1 · REFERENCE<br/>instruments · prices · NAV]
        P2[2 · RECONCILE<br/>ownership · sellability]
    end

    P0 -->|all 4 pass| P1 --> P2
    P0 -->|any fail| FAIL[run FAILED<br/>no orders]
    P2 -->|residual &lt; 0| FAIL

    P2 --> P3[3 · SELL PASS<br/>cancel → verify → tranches → GTTs]
    P3 -->|cancel unverified| FAIL
    P3 --> P4[4 · BUY PASS<br/>deviation → gates → orders]
    P4 --> P5[5 · HARVEST<br/>if queued]
    P5 --> P6[6 · SETTLE<br/>fills · lots · charges · accrual]
    P6 --> DONE([COMPLETED])
```

Phases 0–2 are read-only. The three paths to `FAILED` are the three conditions under which continuing
would be worse than stopping.

---

## 4. Pre-flight gates — why egress is separate

```mermaid
flowchart LR
    subgraph GATES["four independent gates"]
        G1[egress IP<br/>via the proxy]
        G2[token probe<br/>profile or holdings]
        G3[market calendar]
        G4[sell authorisation]
    end
    G1 --> OK{all pass?}
    G2 --> OK
    G3 --> OK
    G4 --> OK
    OK -->|yes| RUN[proceed]
    OK -->|no| ABORT[abort · alert]

    NOTE["Dhan whitelists WRITES only:<br/>a token probes green from the wrong IP<br/>and the first order still fails"]
    NOTE -.-> G1
```

This diagram exists for one reason: to make it obvious why the token probe cannot subsume the egress
check. On Dhan they test different things.

---

## 5. Adapter engine — two directions, five stages each

```mermaid
flowchart TB
    subgraph IN["INBOUND · broker → database"]
        I1[1 fetch<br/>raw HTTP via proxy] --> I2[2 map<br/>rename + cast only]
        I2 --> I3[3 normalise<br/>⚠ where brokers differ]
        I3 --> I4[4 enrich<br/>resolve instrument_id]
        I4 --> I5[5 persist]
    end
    subgraph OUT["OUTBOUND · database → broker"]
        O1[1 resolve<br/>instrument_id → token] --> O2[2 translate<br/>product · side · validity]
        O2 --> O3[3 serialise<br/>JSON / form / jData]
        O3 --> O4[4 transmit<br/>classify errors]
        O4 --> O5[5 record<br/>⚠ before returning]
    end
```

Stages 1–2 and 4–5 are mechanical and identical across brokers. **Stage 3 is the whole per-broker
document.** Stage O5 records the broker ID *before* returning, because on Zerodha an unrecorded GTT is
permanently unidentifiable.

---

## 6. Order placement — write before send

```mermaid
sequenceDiagram
    participant S as strategy
    participant O as orchestration
    participant D as database
    participant A as adapter
    participant B as broker

    S->>O: OrderIntent
    O->>D: INSERT order_request (INTENT, idempotency_key)
    Note over O,D: committed BEFORE the HTTP call
    O->>A: place(intent)
    A->>B: POST /orders
    B-->>A: order_id | error
    A-->>O: OrderState
    O->>D: UPDATE status, broker_order_id

    Note over O,B: crash between the two?<br/>next run finds INTENT and reconciles.<br/>It never re-places blindly.
```

The note is the point of the diagram. Everything else is obvious; that recovery property is not.

---

## 7. Harvest and the two cost bases

```mermaid
flowchart TB
    A["Security A<br/>10 @ ₹100 = ₹1,000"] -->|"falls to ₹90"| SELL["SELL at ₹90<br/>₹900 proceeds<br/>loss ₹100 BOOKED"]
    SELL -->|"carried_basis_amount = ₹1,000"| BUY["BUY proxy B<br/>at ₹45 → 20 units"]
    BUY --> LOT["lot B<br/>unit_cost = ₹45<br/>synthetic = ₹1,000÷20 = ₹50"]

    LOT --> TAX["TAX uses ₹45<br/>the ₹100 loss is already booked"]
    LOT --> STR["STRATEGY uses ₹50<br/>target ₹51.75 = ₹1,035 total<br/>= ₹1,000 + 3.5% ✓"]

    LOT -.->|"operator averages<br/>at ₹40, override"| AVG["lot B2<br/>unit_cost = synthetic = ₹40"]
    AVG --> T1["Tranche SYNTHETIC<br/>20 @ target ₹51.75"]
    AVG --> T2["Tranche ACTUAL<br/>n @ target ₹41.40"]
```

Two things are visible here that the prose takes a page to establish: the carry-over is an **amount**
(₹1,000), not a price — which is why the per-unit figure is ₹50 and not ₹100 — and averaging produces
**two tranches**, never a blend.

---

## 8. Data model — the core

```mermaid
erDiagram
    investor ||--o{ trading_account : has
    broker ||--o{ trading_account : hosts
    trading_account ||--o{ run : executes
    universe ||--o{ run : scoped_to
    universe ||--o{ universe_member : contains
    instrument ||--o{ universe_member : in
    instrument ||--o{ broker_instrument : mapped_as
    run ||--o{ run_candidate : evaluated
    run ||--o{ order_request : placed
    order_request ||--o{ order_fill : filled_by
    order_fill ||--|| position_lot : creates
    position_lot ||--o{ lot_closure : closed_by
    position_lot ||--o{ harvest_chain : proxied_by
    order_request ||--o{ charge : incurs
    trading_account ||--o{ cash_ledger : records
    investor ||--o{ tax_gain : realises
```

Three structural facts: **one lot per fill** (not per order), **lots belong to a universe** while
**capital belongs to the account**, and **`broker_instrument` is the table that makes five brokers
tractable** — resolution happens once, and the strategy engine only ever sees `instrument_id`.

---

## 9. Charges — what each broker can actually tell us

```mermaid
quadrantChart
    title Charge reporting capability
    x-axis "No per-order attribution" --> "Per-order"
    y-axis "No components" --> "Full components"
    quadrant-1 "Full contrast"
    quadrant-2 "Components only"
    quadrant-3 "Nothing"
    quadrant-4 "Totals only"
    Dhan: [0.85, 0.9]
    Zerodha: [0.9, 0.85]
    Upstox: [0.15, 0.8]
    Groww: [0.85, 0.15]
    Shoonya: [0.1, 0.1]
```

**Upstox and Groww sit in opposite quadrants** — components without attribution, attribution without
components. Only Dhan and Zerodha support a per-fill, per-component contrast; Shoonya supports none,
so its charges are computed-only and the UI says so.

---

## 10. Source

These are the authoritative versions. If a diagram and a document disagree, the document wins — and
the diagram is a bug.

| Diagram | Document |
|---|---|
| 1, 2 | [`../01-architecture/SYSTEM-OVERVIEW.md`](../01-architecture/SYSTEM-OVERVIEW.md) |
| 3, 4, 6 | [`../01-architecture/RUN-LIFECYCLE.md`](../01-architecture/RUN-LIFECYCLE.md) |
| 2, 5 | [`../03-brokers/ADAPTER-ENGINE.md`](../03-brokers/ADAPTER-ENGINE.md) |
| 7 | [`../04-strategy/HARVEST-COST-BASIS.md`](../04-strategy/HARVEST-COST-BASIS.md) |
| 8 | [`../05-data/DATABASE-SCHEMA.md`](../05-data/DATABASE-SCHEMA.md) |
| 9 | [`../08-reporting/CHARGES-MODEL.md`](../08-reporting/CHARGES-MODEL.md) |
