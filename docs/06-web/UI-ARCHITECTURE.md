# Web Console — Architecture

**Status:** 🟢 Specified
**Date:** 2026-09-26
**Stack:** React · TypeScript · Tailwind, served by the Python engine (D-069c)

> One admin, one role, one browser tab. The console is where every trading decision is taken,
> because it is the only place the full context is visible — deviations, gates, quantities, charges
> and the three P&L figures side by side.

---

## 1. Constraints that shaped it

| Constraint | Consequence |
|---|---|
| Served **from the instance**, which runs ~20 min/day (D-078) | No SSR, no Next.js server runtime. A static bundle + JSON API |
| The instance may stop **mid-session** | Every screen must fail gracefully to "engine offline", not to a blank page |
| Single admin, no other roles (D-040) | No RBAC, no user management, no sharing. One session |
| Must be **fast and light** (D-069c) | Static bundle, client-side routing, no heavyweight component library |
| Identical-looking static failover (D-018) | The layout shell is shared between console and Render site; only the login button differs |
| Decisions must be **explainable** | Every number carries its basis and its source. No bare "P&L" anywhere |

The last one is the design brief, not a nicety. A console that shows a single profit figure without
saying which basis it uses would actively mislead once a harvest has happened.

---

## 2. Shape

```
frontend/
├── src/
│   ├── main.tsx                  entry; router
│   ├── api/                      generated types + fetch wrapper
│   ├── lib/
│   │   ├── money.ts              ₹ formatting, 2dp display / 4dp internal
│   │   ├── pct.ts                percentage formatting, signed, 2dp
│   │   └── theme.ts              light/dark, persisted
│   ├── components/               Table, StatTile, Badge, Drawer, ConfirmDialog,
│   │                             BasisLabel, SourceBadge, EmptyState, OfflineBanner
│   ├── screens/                  one directory per screen (§4 of SCREEN-SPECS)
│   └── shell/                    AppShell, Nav, Header, EngineStatus
└── dist/                         built; served by FastAPI as static files
```

```
atom/web/
├── app.py                        FastAPI; mounts dist/ and /api
├── deps.py                       session auth dependency
└── routes/                       one module per screen group; read-mostly
```

### 2.1 The API is thin and read-mostly

Most endpoints are `GET` and return rows the database already has. The console does **no
computation that the backend does not also do** — a number shown in the UI must be reproducible by
a SQL query, because that is the property that makes a decision auditable a year later.

The small set of `POST` endpoints are the *actions*: execute a run, release an order, override an
averaging block, type a cash movement, exclude an instrument. Each writes to `action_audit`.

---

## 3. State and data flow

```
screen mount
   └─► GET /api/... (TanStack Query)
          ├─ 200 → render
          ├─ 401 → redirect to login
          └─ network error → OfflineBanner: "engine offline" + last-known timestamp
```

**No global client state store.** Server data is cached by TanStack Query; UI state (which tab, which
drawer) is local. There is no client-side model of the portfolio to drift out of sync with the
database — the database is the model.

### 3.1 Polling, deliberately sparse

| Screen | Refresh |
|---|---|
| Run status while `EXECUTING` | 5 s |
| Everything else | on mount, plus a manual refresh button |

No websockets. Runs take minutes, prices come from **start and end-of-day snapshots with no
intraday polling** (D-041), and a live-ticking portfolio would invite exactly the intraday attention
this system is designed not to need.

---

## 4. Offline behaviour

The instance stops after each run, so "offline" is the **normal** state, not an error.

| | |
|---|---|
| Render static site | Same shell, same theme, marketing/summary content, **no login button** |
| Console, engine stopping mid-session | `OfflineBanner` appears; cached data stays visible, marked *as of HH:MM*; all actions disable |
| Never | A white screen, a spinner that never resolves, or an action that appears to work and does not |

**Cached data stays on screen with a timestamp** rather than being cleared. Wiping the view when the
engine stops would destroy context the operator was reading.

---

## 5. Component conventions that carry meaning

Three components exist specifically to prevent a class of mistake, and they are mandatory wherever
they apply.

### 5.1 `<BasisLabel>` — no bare P&L, ever

Every monetary return is rendered with the basis it was computed against:

```tsx
<Money value={x} basis="strategy" />   // vs synthetic basis
<Money value={y} basis="cash" />       // vs actual paid
<Money value={z} basis="taxable" />    // vs actual, tax FIFO
```

After a harvest these three diverge (D-190). A single unlabelled figure would be the most
misleading thing the UI could show — it is the phantom-profit failure surfacing as a display bug
instead of a logic bug.

### 5.2 `<SourceBadge>` — computed or reported

Charges, and anything else with two possible provenances, carry a badge: **`computed`** (ATOM's
model) or **`broker`** (reported). Where a broker supplies no figure, the broker column shows
`—` with a tooltip naming the limitation — **never `₹0.00`**, which reads as "no charges".

| Broker | Per-order | Components |
|---|---|---|
| Dhan · Zerodha | ✅ | ✅ |
| Upstox | ❌ period only | ✅ incl. DP |
| Groww | ✅ | ❌ aggregate |
| Shoonya | ❌ | ❌ |

### 5.3 `<ConfirmDialog>` — for anything audited

Every action that writes to `action_audit` goes through it, and the dialog **states what will
happen**, not "are you sure?". The averaging override, for example, says that a second sell tranche
will be created.

---

## 6. Accessibility and theming

| | |
|---|---|
| Themes | **Light and dark, both first-class** (D-069c). Toggle persisted; respects `prefers-color-scheme` on first visit |
| Contrast | WCAG AA minimum on all text, including the ±colour on numbers |
| Colour is never the only signal | Gains and losses carry a sign and an arrow, not just green/red |
| Keyboard | Full tab order; tables arrow-navigable; `Esc` closes drawers |
| Numbers | Tabular figures, right-aligned, fixed decimals so columns line up |

"Colour is never the only signal" matters more here than in a typical app: red/green profit
indication is the single most common accessibility failure in financial UIs, and roughly 1 in 12 men
has some form of red-green colour deficiency.

---

## 7. Performance targets

| | Target |
|---|---|
| Bundle (gzipped) | < 250 KB |
| First contentful paint on the instance | < 1 s |
| Any table render | < 100 ms for 500 rows |
| Dependencies | React, React Router, TanStack Query, Tailwind, Recharts. **No component library** |

The instance is a `t3a.small` that also runs the engine, so the frontend has to be genuinely light
rather than merely modern.

---

## 8. Related

[`DESIGN-SYSTEM.md`](DESIGN-SYSTEM.md) · [`SCREEN-SPECS.md`](SCREEN-SPECS.md) ·
[`AUTH-AND-ACCESS.md`](AUTH-AND-ACCESS.md) ·
[`../01-architecture/SYSTEM-OVERVIEW.md`](../01-architecture/SYSTEM-OVERVIEW.md)
