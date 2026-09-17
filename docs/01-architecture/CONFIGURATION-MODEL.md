# Configuration Model

**Status:** 🟢 Specified
**Implements:** D-037 · supersedes the scope table proposed in Q-060
**Governing rule:** *No operational number is ever hard-coded, and none is ever defaulted.
Every one is a stored, editable, versioned config value that the operator must supply
explicitly before a run may start.*

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

## 2. No defaults, ever — completeness is a pre-flight gate

> "There should be **no defaults**. While running we need to check that all configs are in
> place. If an investor holding an account with a broker has configs missing for equity, or
> priority missing, they should not be able to run the process. Do not assume or fall back to
> any defaults — ask the user to push in all the configs before running."

**There is no resolution hierarchy and no inheritance.** Every required key must be
explicitly set at its exact scope, by the operator, before a run may start. A missing value
is never filled in from a broader scope, a system default, or a literal in code.

### 2.1 The pre-flight check

Before any run — live or dry — the engine enumerates the full required config set and
verifies every entry exists:

```
required = { (trading_account, category, key)
             for trading_account in active_accounts
             for category        in [EQUITY, COMMODITY, GLOBAL]
             for key             in CATEGORY_SCOPED_KEYS }
         ∪ { (trading_account, key)
             for trading_account in active_accounts
             for key             in ACCOUNT_SCOPED_KEYS }

missing = required − configured
if missing:  BLOCK THE RUN
```

On failure the run **does not start**. The console shows exactly what is absent, grouped so
the gap is obvious:

```
⛔ Cannot start run — 3 configs missing

  Person A · Dhan · COMMODITY
      • profit_target_pct        not set
      • depth_levels             not set

  Person A · Dhan
      • category_priority        not set

  Set these on the Execute Engine screen, then run again.
```

The same check runs as a **live validity indicator** on the Execute Engine screen, so the gap
is visible before the operator reaches for the Execute button rather than at the moment they
press it.

### 2.2 NULL is an explicit choice, not an absence

An operator may deliberately set a config to **NULL**. That is a recorded decision meaning
**"do not trade this"**, and it is categorically different from a value that was never
supplied:

| State | Meaning | Run behaviour |
|---|---|---|
| **Value present** | Configured | Trades per that value |
| **NULL** (explicitly set) | Operator has switched this off | **Skips** that category/account; logged as an explicit operator choice |
| **Absent** (never set) | Unknown | **Blocks the run** |

NULL and absent must therefore be distinguishable in storage — a nullable column with a
separate `is_configured` marker, or a config row that exists carrying a NULL value versus no
row at all. The second is preferred: **presence of the row means configured; its value may
be NULL.**

### 2.3 Consequences

- Onboarding a new investor or broker is **not complete** until every config row exists. The
  onboarding flow ends with this same check.
- Adding a new config key to the registry **invalidates every existing account** until the
  operator fills it in. That is intentional: a new knob must be a deliberate choice per
  account, not silently defaulted across the estate.
- The "Default" column in the registry below is therefore a **suggested starting value shown
  in the UI when the operator first creates the row** — a pre-filled form field they must
  actively accept. It is never applied by the engine.

## 3. Config registry

Every operational number in ATOM. Nothing outside this table may be a literal in code.

### 3.1 Strategy — key `(trading_account, category)`

| Key | Type | Suggested starting value (UI pre-fill only) | Meaning |
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

| Key | Type | Suggested starting value (UI pre-fill only) | Meaning |
|---|---|---|---|
| `category_priority` | ARRAY | `[EQUITY, COMMODITY, GLOBAL]` | Order categories are funded in when cash is short |
| `daily_spend_cap_inr` | NUMERIC(18,4) | sum of amounts × 2 | Hard stop; breach aborts the run |
| `max_orders_per_run` | INT | 10 | Guard against a logic bug |
| `dry_run` | BOOL | false | Compute and log everything, send nothing |

### 3.3 Harvesting — key `(trading_account)`

| Key | Type | Suggested starting value (UI pre-fill only) | Meaning |
|---|---|---|---|
| `stcg_rate_pct` | NUMERIC(9,4) | 20.0000 | Short-term capital gains rate |
| `correlation_window_days` | INT | 250 | Window for proxy correlation |
| `min_correlation` | NUMERIC(9,4) | 0.8500 | Floor below which a proxy is rejected |
| `harvest_requires_approval` | BOOL | true | Human approval gate |

### 3.4 Operational — key `(global)`

| Key | Type | Suggested starting value (UI pre-fill only) | Meaning |
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
| ~~Q-153~~ | ✅ Withdrawn — there is no resolution order; every key is explicitly set (D-038) |
| ~~Q-155~~ | ✅ Resolved by D-040 — single admin login, no other roles |
| Q-156 | Confirm NULL semantics per key: does NULL on `trade_amount_inr` mean "never buy this category" while sells continue, i.e. identical to `category_enabled = false`? |
| Q-157 | When a new config key is added to the registry, block every account until filled, or allow a grace mode? |
