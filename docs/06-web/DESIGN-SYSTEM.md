# Design System

**Status:** 🟢 Specified
**Date:** 2026-09-26
**Brand basis:** the existing MetaAlgo site — dark navy `#0a0f1c`, cyan `#06b6d4`, Inter, Tailwind

> A navy professional financial theme, in **light and dark**, where every number is legible at a
> glance and nothing decorative competes with the data.

---

## 1. Tokens

Defined once as CSS custom properties on `:root`, redefined for dark mode. Tailwind reads them, so
no component hardcodes a colour.

### 1.1 Surfaces and text

| Token | Light | Dark |
|---|---|---|
| `--bg` | `#f7f9fc` | `#0a0f1c` |
| `--surface` | `#ffffff` | `#111827` |
| `--surface-raised` | `#ffffff` | `#1a2233` |
| `--border` | `#e2e8f0` | `#1f2937` |
| `--text` | `#0a0f1c` | `#e8eef7` |
| `--text-muted` | `#5a6b85` | `#94a3b8` |
| `--text-faint` | `#8a99b0` | `#64748b` |

`#0a0f1c` is the dark background *and* the light-mode text colour. That is deliberate — it keeps the
two themes recognisably the same product rather than two palettes that happen to share a logo.

### 1.2 Brand and semantic

| Token | Light | Dark | Used for |
|---|---|---|---|
| `--accent` | `#0891b2` | `#06b6d4` | Primary actions, links, focus rings |
| `--accent-soft` | `#e0f7fb` | `#0e3a47` | Selected rows, subtle fills |
| `--gain` | `#047857` | `#34d399` | Positive numbers |
| `--loss` | `#b91c1c` | `#f87171` | Negative numbers |
| `--warn` | `#b45309` | `#fbbf24` | Gates failed, warnings, stale data |
| `--block` | `#9333ea` | `#c084fc` | Blocked / frozen / proxy-applied |
| `--neutral` | `#475569` | `#94a3b8` | Zero, not-applicable, unknown |

Cyan darkens to `#0891b2` in light mode because `#06b6d4` on white fails AA for body text. The brand
is preserved by hue, not by hex.

**`--block` is purple, not red.** A blocked instrument is not an error — it is a deliberate state
awaiting a decision (frozen, under review, proxy-applied). Colouring it red would make correct
behaviour look like a fault.

### 1.3 Type

| | |
|---|---|
| UI | **Inter**, `-apple-system` fallback |
| Numbers | Inter with `font-variant-numeric: tabular-nums` |
| Code, IDs, ISINs | **JetBrains Mono**, fallback `ui-monospace` |

Scale: `11 / 12 / 14 / 16 / 20 / 24 / 32`. Body is 14. Tables are 13 with 12 headers — financial
tables earn their density, and 14 in a 20-column table wastes the screen the operator is reading.

### 1.4 Spacing, radius, shadow

4px base scale. Radius `6px` for controls, `10px` for cards, `0` inside table cells.

**Shadows only on overlays** — drawers, dialogs, dropdowns. Cards use a border. Elevation on
everything makes a dense data screen feel noisy, and in dark mode shadows are nearly invisible
anyway, so a border is the honest separator in both themes.

---

## 2. Number rendering

The rules that make a financial table readable, and the reason each exists.

| Rule | Why |
|---|---|
| Right-aligned, tabular figures, fixed decimals | Columns align; magnitude is comparable by eye |
| **Currency: 2dp displayed, 4dp stored** (D-026) | Never round in the database; never show noise |
| **Percentages: 2dp displayed, 4dp internal** (D-149) | Same |
| Explicit sign on deltas | `+3.50%` / `−10.00%` — a bare `3.50` is ambiguous |
| Unicode minus `−` (U+2212), not hyphen | Aligns with digits at tabular width |
| Zero renders `—` where "no value" is meant | `₹0.00` and "no data" are different facts |
| Thousands separators, Indian grouping | `₹12,34,567.89` — this is an Indian system |
| Colour **plus** sign **plus** arrow | Colour alone excludes colour-deficient readers (§6 of UI-ARCHITECTURE) |

### 2.1 A number never appears without its basis or source

```
Strategy return   +3.50%   vs synthetic ₹100.00
Cash return       −6.85%   vs actual    ₹90.00
Taxable gain      −₹10.00  tax FIFO
```

After a harvest these disagree, and which one is "the" return depends on the question being asked
(D-190). The UI does not choose for the reader.

Charges likewise carry `computed` / `broker` badges, with `—` where a broker supplies nothing.

---

## 3. Core components

| Component | Notes |
|---|---|
| `Table` | Sticky header, zebra off, hover highlight, right-aligned numerics, column sort, CSV export |
| `StatTile` | Label, value, optional delta, optional basis. Never more than 6 in a row |
| `Badge` | `success` `warn` `block` `neutral` `info` — text always, colour additionally |
| `BasisLabel` | The `vs synthetic ₹100.00` suffix |
| `SourceBadge` | `computed` / `broker` |
| `Drawer` | Right-side detail panel; the default for drill-down, so the list keeps its scroll position |
| `ConfirmDialog` | States the consequence; used for anything audited |
| `GateChip` | A gate and its verdict — `NAV premium 18.9% > 2% ✗` |
| `EmptyState` | Explains *why* it is empty, never just "no data" |
| `OfflineBanner` | Engine offline + last-known timestamp |
| `ModePill` | **`DRY`** (accent outline) / **`LIVE`** (solid) — see §4 |

### 3.1 `GateChip` carries the number, not just the verdict

`NAV premium ✗` tells the operator nothing actionable. `NAV premium 18.9% > 2% ✗` tells them the
threshold and the actual value, which is the difference between a UI that reports and one that
explains. Every `run_candidate` gate renders this way.

---

## 4. Execution mode is unmissable

A dry run and a live run look identical by design — they share every line of code (D-045). So the
UI must make the difference impossible to miss:

| Mode | Treatment |
|---|---|
| `DRY` | `ModePill` outlined in accent; a persistent top strip reading **DRY RUN — no orders sent** |
| `LIVE` | Solid pill; no strip |

The strip is not dismissible. The failure this prevents is the operator reading dry-run numbers as
real ones, or worse, hesitating over a live action because they think it is a simulation.

---

## 5. Charts

Recharts, used sparingly. Chart types: line (time series), bar (period comparison), horizontal bar
(peer comparison across universes).

| Rule | |
|---|---|
| Line for time, bar for comparison, no pies | A pie of eight ETFs is unreadable |
| Value axes on bar charts include zero | Truncating exaggerates differences |
| Series colours from the palette, not defaults | |
| Every chart has a table equivalent | The table is the source of truth; the chart is the summary |
| Axis labels carry units | `₹` or `%`, always |

---

## 6. Layout

```
┌────────────────────────────────────────────────────────────┐
│ ▣ ATOM     [account ▾] [universe ▾]   ●LIVE  ◐ theme  ⏻   │  56px
├──────────┬─────────────────────────────────────────────────┤
│ Overview │                                                 │
│ Execute  │                  content                        │
│ Universe │              max-width 1600px                   │
│ Holdings │                                                 │
│ Orders   │                                                 │
│ Harvest  │                                                 │
│ Cash     │                                                 │
│ Reports  │                                                 │
│ Charges  │                                                 │
│ Tax      │                                                 │
│ Config   │                                                 │
│ Logs     │                                                 │
│ Dry Run  │                                                 │
└──────────┴─────────────────────────────────────────────────┘
```

**Account and universe selectors live in the header, not per screen.** They are global context: a
screen shows data for the selected account and universe, and changing either re-scopes everything.
Repeating the selector per screen would let the two drift apart, which is how someone reads
universe 1's P&L believing it is universe 2's.

Sidebar collapses to icons below 1280px. Below 768px the console is usable but not optimised — it is
an admin tool for a desk, and Telegram covers the phone case.

---

## 7. What this system avoids

| Avoided | Why |
|---|---|
| Gradients, glassmorphism, animated backgrounds | They compete with the data |
| Animation beyond 150 ms state transitions | A trading console should feel instant |
| Icon-only buttons | Always a label or an accessible name |
| Red for anything non-erroneous | Blocked ≠ broken (§1.2) |
| Dark mode as an afterthought | Both themes are specified and tested together |
| A bare "P&L" column anywhere | §2.1 |
