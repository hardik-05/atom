# Configuration Model

**Status:** 🟢 Specified
**Implements:** D-037 · supersedes the scope table proposed in Q-060
**Governing rule:** *No operational number is ever hard-coded. Every one is a stored,
editable, versioned config value.*

---

## 1. The scope key

> "This percentage — 2% or any percent — should be configurable. For **each account, each
> broker and each category** we should be able to change these numbers. Do not hard-code it
> as a number."

That gives three dimensions: **investor × broker × category**. The first two always travel
together, so the model names their pair:

```
TRADING ACCOUNT  =  (investor, broker)
CONFIG KEY       =  (trading_account, category)
```

**A "trading account" is one investor's account at one broker.** Person A with Upstox and
Dhan has **two** trading accounts, each independently configurable. This is also the unit
that holds a token, funds, holdings and an order book — so the config key matches the
natural grain of everything else in the system.

### Worked example

Person A (Upstox + Dhan) and Person B (Dhan) across three categories = **9 independently
configurable rows**:

| Trading account | Category | Profit target | Depth | Amount | Lookback | NAV tol. |
|---|---|---|---|---|---|---|
| A · Upstox | EQUITY | 3.50% | 3 | ₹10,000 | 50 | 2.00% |
| A · Upstox | COMMODITY | 5.00% | 5 | ₹5,000 | 35 | 2.00% |
| A · Upstox | GLOBAL | 2.00% | 1 | ₹20,000 | 90 | 2.00% |
| A · Dhan | EQUITY | 4.00% | 2 | ₹15,000 | 20 | 1.50% |
| … | … | … | … | … | … | … |
| B · Dhan | GLOBAL | 2.00% | 1 | ₹10,000 | 90 | 2.00% |

Person A may run a 3.5% equity target on Upstox and 4% on Dhan. Nothing is shared between
two accounts unless the operator sets the same value in both.

---

## 2. Resolution order

A value is resolved most-specific-first, so an operator can set one default and override only
where it differs:

```
1. (trading_account, category)   ← most specific, always wins
2. (trading_account, *)           ← account-wide default
3. (investor, category)           ← investor's house style across their brokers
4. (investor, *)
5. (*, category)                  ← system default per category
6. (*, *)                         ← system default
```

Every resolution records **which level supplied the value**, and the run log prints it, so
"why was this 4% and not 3.5%?" is answerable without guesswork.

---

## 3. Config registry

Every operational number in ATOM. Nothing outside this table may be a literal in code.

### 3.1 Strategy — key `(trading_account, category)`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `profit_target_pct` | NUMERIC(9,4) | 3.5000 | Sell limit = buy price × (1 + this) |
| `depth_levels` | INT | 3 | How far down the ranked list to look when candidates are already held |
| `trade_amount_inr` | NUMERIC(18,4) | 10000.0000 | Rupees per buy order |
| `lookback_days` | INT | 50 | Window for the mean/median |
| `average_method` | ENUM | `MEAN` | `MEAN` or `MEDIAN` (D-026 ranking basis) |
| `category_enabled` | BOOL | true | Suppresses **buying** only; sells always run |
| `nav_check_enabled` | BOOL | true | Master toggle for the NAV veto gate |
| `nav_premium_tolerance_pct` | NUMERIC(9,4) | 2.0000 | Max premium over NAV permitted on a buy |
| `volume_threshold_units` | NUMERIC(18,4) | 100000.0000 | Liquidity floor, in **units** (D-027) |
| `volume_window_days` | INT | 25 / 60 | Window(s) for average volume (D-016) |

### 3.2 Strategy — key `(trading_account)`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `category_priority` | ARRAY | `[EQUITY, COMMODITY, GLOBAL]` | Order categories are funded in when cash is short |
| `daily_spend_cap_inr` | NUMERIC(18,4) | sum of amounts × 2 | Hard stop; breach aborts the run |
| `max_orders_per_run` | INT | 10 | Guard against a logic bug |
| `dry_run` | BOOL | false | Compute and log everything, send nothing |

### 3.3 Harvesting — key `(trading_account)`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `stcg_rate_pct` | NUMERIC(9,4) | 20.0000 | Short-term capital gains rate |
| `correlation_window_days` | INT | 250 | Window for proxy correlation |
| `min_correlation` | NUMERIC(9,4) | 0.8500 | Floor below which a proxy is rejected |
| `harvest_requires_approval` | BOOL | true | Human approval gate |

### 3.4 Operational — key `(global)`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `market_open_gate_time` | TIME | 09:30 | Earliest a run may execute |
| `order_poll_interval_sec` | INT | 60 | Fill-polling cadence |
| `order_poll_timeout_sec` | INT | 300 | Give up waiting, leave order resting |
| `log_purge_days` | INT | 90 | Supabase structured-log retention (D-030) |
| `local_log_retention_days` | INT | 30 | EC2 + S3 standard (D-025) |
| `kill_switch` | BOOL | false | Blocks all order placement everywhere |

**Precision:** all percentages and money are `NUMERIC(_,4)` — 4 decimal places for storage
and comparison, 2 for display (D-026). Rounding happens in the presentation layer only and
never feeds a decision.

---

## 4. Versioning and audit

1. **Every change is versioned.** `config_history` records key, scope, old value, new value,
   who changed it, and when. Nothing is updated in place.
2. **Every run snapshots its config.** A run stores the fully-resolved set it used, so a
   decision six months old can be replayed exactly even after the live config has moved on.
3. **Config is frozen at run start.** Edits during a run are ignored by that run (Q-062).
4. **The snapshot is printed into the run log** (D-035), so the `.txt` file is self-contained.

## 5. Validation

Rejected at write time, not discovered at run time:

| Rule | |
|---|---|
| `profit_target_pct` | > 0, ≤ 100 |
| `depth_levels` | ≥ 1, ≤ 20 |
| `trade_amount_inr` | > 0, ≤ `daily_spend_cap_inr` |
| `lookback_days` | ≥ 2, ≤ available history for that category |
| `nav_premium_tolerance_pct` | ≥ 0 (negative would demand a discount — use 0) |
| `volume_threshold_units` | ≥ 0 |
| `min_correlation` | between −1 and 1 |
| `category_priority` | a permutation of the three categories, no duplicates, no omissions |

A config that fails validation cannot be saved, and a run refuses to start on an unresolvable
key rather than falling back to a literal.

## 6. Where it is edited

The **Execute Engine** screen, grouped by trading account then category, with the resolution
level shown against each value so an inherited default is visually distinct from an explicit
override. Changing a value takes effect from the next run.

---

## 7. Open items

| ID | Item |
|---|---|
| Q-153 | Confirm the resolution order in §2 — particularly whether an investor-level default should outrank a system-level category default |
| Q-154 | Should `category_priority` also be per-category-set, or is one ordering per trading account enough? |
| Q-155 | Who may edit config — ADMIN only, or VIEWER too (Q-072)? |
