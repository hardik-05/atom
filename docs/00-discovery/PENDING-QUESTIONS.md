# ATOM — Pending Questions

**Status:** Awaiting answers · **as of 2026-09-17**
**Resolved so far:** 53 decisions (D-001 … D-053) — see [`DECISIONS.md`](./DECISIONS.md)

Numbered **1 … 86** for easy reference. Answer as `1. <answer>`, `2. agree`, etc.
Every item carries a recommendation, so **"agree"** is a complete answer.
Original IDs are shown for cross-reference with [`OPEN-QUESTIONS.md`](./OPEN-QUESTIONS.md).

---

## A. Engagement and delivery

| # | Q | Question | Recommendation |
|---|---|---|---|
| 1 | Q-001 | Build order after docs are approved | Paper gateway + strategy engine first (validates with no IP/credentials), then brokers, then console, then harvesting, then reports |
| 2 | Q-002 | Is there a go-live date? | — |
| 3 | Q-004 | Capital per account on day one | — (sizes order counts, API budgets, DB volumes) |
| 4 | Q-005 | Monorepo or split repos? | Monorepo: `engine/`, `web/`, `infra/`, `docs/` |
| 5 | Q-006 | Rename `docs/` to `documentation/`? | Keep `docs/` |
| 6 | Q-007 | Diagram format | Mermaid as source of truth, rendered PNGs alongside |
| 7 | Q-008 | Who else reads these docs? | — |
| 8 | Q-009 | Is "ATOM" the product name? Logo/brand assets? | — |
| 9 | Q-136 | Review docs in batches or all at the end? | In batches by area |

## B. Infrastructure

| # | Q | Question | Recommendation |
|---|---|---|---|
| 10 | Q-013 | Expected EC2 uptime per trading day | Assume ≤60 min, operator-driven shutdown |
| 11 | Q-014 | Auto-shutdown safety net if you forget? | Auto-stop after 90 min idle, Telegram warning at 75 |
| 12 | Q-015 | Confirm region `ap-south-1` | Yes |
| 13 | Q-016 | Existing AWS account, or new? Fresh VPC? | — |
| 14 | Q-017 | Confirm instance is fully disposable (all state in Supabase/S3) | Yes |
| 15 | Q-018 | Deploy mechanism to EC2 | Docker image on ECR |
| 16 | Q-019 | Recovery if the engine dies mid-run | Write order intent to DB **before** sending; reconcile on restart |
| 17 | Q-139 | Secrets Manager vs encrypted-in-Supabase — settle on cost | Secrets Manager (~$0.40/secret/month); confirm acceptable |
| 18 | Q-140 | **Domain auto-switch Render ↔ EC2** — mechanism not yet designed | Needs its own design; options are DNS switching, a reverse proxy, or Render-side redirect |
| 19 | Q-141 | Confirm ap-south-1 pricing in console (blocked here) | — |
| 20 | Q-142 | Confirm ENI/IPv4 limits via `describe-instance-types` | — |
| 21 | Q-143 | Is the AWS account in its first 12 months (750 free IPv4 hrs)? | — |
| 22 | Q-144 | EBS root volume size, given 30-day local log retention | 20 GB gp3 |
| 23 | Q-135 | Monthly infra budget ceiling | Analysis says ~₹755/mo at 2 accounts |

## C. Brokers

| # | Q | Question | Recommendation |
|---|---|---|---|
| 24 | Q-021 | Confirm the broker adapter contract (14 methods listed in the bank) | Plus `get_funds_credits` for D-050 |
| 25 | Q-024 | **Do you have API access for Zerodha (₹500/mo), Groww and Shoonya yet?** | Blocker for testing all five |
| 26 | Q-025 | Shared rate limiter per broker per account? | Yes, token bucket from documented limits |
| 27 | Q-026 | Vendor SDKs or raw HTTP? | **Raw HTTP** — Shoonya's SDK cannot place GTT, and SDKs can't bind a source IP/proxy |
| 28 | Q-027 | Buys as MARKET or LIMIT? | LIMIT at LTP + small buffer (thin ETF books; Dhan converts MARKET to LIMIT anyway) |
| 29 | Q-028 | Confirm CNC/delivery only | Yes |
| 30 | Q-029 | NSE only, or BSE fallback? | NSE only in v1; schema carries exchange |

## D. Telegram, Lambda, run lifecycle

| # | Q | Question | Recommendation |
|---|---|---|---|
| 31 | Q-030 | Bot command surface | `/start` `/stop` `/status` `/logs` `/funds` |
| 32 | Q-032 | One chat or separate log channel? | Separate: commands+status vs log artefacts |
| 33 | Q-033 | Status reply timing (EC2 takes 30–60s to boot) | Immediate ack, then a "ready" message with the console link |
| 34 | Q-034 | Should the engine ever self-start on a schedule? | No for trading; EventBridge only for the weekly universe job |
| 35 | Q-035 | Where does the Saturday universe job run? | Separate scheduled start; needs no static IP |
| 36 | Q-036 | NSE holiday awareness | Yes, cached calendar; refuse and say why |
| 37 | Q-037 | Can Execute be pressed twice in a day? | Allowed but idempotent — won't re-buy the same category |
| 38 | Q-038 | Concurrency — two runs at once | DB run-lock per account |
| 39 | Q-039 | Where do hard failures alert? | Telegram |

## E. Market data and universe

| # | Q | Question | Recommendation |
|---|---|---|---|
| 40 | Q-045 | How much price history to hold? | 750 trading days (~3 yrs) |
| 41 | Q-046 | **Corporate actions** — splits/distributions corrupt means and correlations | Store raw + adjusted close; **all strategy maths on adjusted** |
| 42 | Q-047 | Data refresh cadence | Nightly backfill + gap check at run start |
| 43 | Q-048 | Minimum history before an ETF is eligible | Longest lookback + 10 days, min 60 |
| 44 | Q-049 | Freeze each week's universe as an immutable snapshot? | Yes, runs reference a snapshot ID |
| 45 | Q-150 | NAV missing for some rows (18 of 350 lack i-NAV) — block, allow, or fall back? | Block the buy, log "NAV unavailable" |
| 46 | Q-151 | Use NAV (EOD) or i-NAV (intraday) for the live check? | i-NAV when present, NAV fallback |
| 47 | Q-152 | Confirm `Hybrid` category excluded | Yes |
| 48 | Q-170 | Which free price provider for `FREE` dry runs, and should unmapped symbols block? | Yahoo Finance; don't block, but report coverage prominently |

## F. Strategy mechanics

| # | Q | Question | Recommendation |
|---|---|---|---|
| 49 | Q-050 | **Mean or median** for the ranking? | Config per account×category, defaulting to mean; always compute and log both |
| 50 | Q-053 | Quantity from a ₹ budget | `floor(amount/price)`; skip if one unit exceeds budget |
| 51 | Q-056 | Duplicate sell orders when one already rests at the broker | Reconcile against order book; leave correct ones, cancel-replace wrong prices, never double |
| 52 | Q-057 | Profit target on raw price or all-in cost? | Raw price; show charge-inclusive breakeven in UI/logs |
| 53 | Q-058 | Tick-size rounding for the sell limit | Round **up**, so realised % is never below target |
| 54 | Q-059 | Cost basis for holdings ATOM didn't buy | Use broker's average cost, flag as `EXTERNAL` |
| 55 | Q-059b | Does the holdings check look at the whole broker account or only ATOM positions? | Whole account |

## G. Configuration

| # | Q | Question | Recommendation |
|---|---|---|---|
| 56 | Q-061 | Version every config change with who/when/old value? | Yes |
| 57 | Q-156 | NULL semantics per key — does NULL `trade_amount` equal `category_enabled=false`? | Treat as "don't buy this category; sells continue" |
| 58 | Q-157 | When a new config key is added, block all accounts until filled? | Yes, block |

## H. Web console

| # | Q | Question | Recommendation |
|---|---|---|---|
| 59 | Q-064 | Daily Status row count (brief said 7 in one place, 10 in another) | 10 rows, greyed beyond depth |
| 60 | Q-065 | Daily Status history depth | Date picker over all history |
| 61 | Q-068 | Engine addressing + TLS for the browser | Third Elastic IP for the console, separate from the two broker-registered trading IPs |
| 62 | Q-069 | UI framework | React + Vite + TypeScript + Tailwind, served by the Python engine |
| 63 | Q-069b | Mobile support | Desktop-first, responsive for status checks |
| 64 | Q-070 | Login mechanism for the single admin | Supabase Auth, Google sign-in restricted to your email + password fallback |
| 65 | Q-071 | 2FA on login? | Yes — Google's own 2FA; TOTP if password login is used |

## I. Security

| # | Q | Question | Recommendation |
|---|---|---|---|
| 66 | Q-073 | Where all secrets live | AWS Secrets Manager, fetched at boot via instance role |
| 67 | Q-074 | Supabase RLS from day one? | Yes — retrofitting is painful |
| 68 | Q-075 | Store PAN/bank details? | No; broker client code only |
| 69 | Q-076 | Confirm log redaction of tokens/secrets, with a test | Yes |
| 70 | Q-077 | Audit every operator action that causes a trade | Yes, immutable table |
| 71 | Q-078 | Global kill switch | Yes, flippable from console and Telegram |
| 72 | Q-079 | Per-run and per-day spend caps | Yes; breach aborts and alerts |

## J. Tax-loss harvesting

| # | Q | Question | Recommendation |
|---|---|---|---|
| 73 | Q-080 | STCG rate — config? surcharge/cess? | Config defaulting to 20%, headline only, with a disclaimer |
| 74 | Q-082 | **Correlation definition** | Pearson on **daily log returns**, 250-day window. Correlating price levels gives meaninglessly high numbers |
| 75 | Q-083 | Minimum correlation to permit a swap | 0.85 floor, override requires explicit action |
| 76 | Q-084 | Must the proxy pass the volume filter? | Yes |
| 77 | Q-086 | Sell fills but proxy buy fails | Alert immediately, mark chain INCOMPLETE, one-click retry, no auto-rollback |
| 78 | Q-087 | Confirm proxy must be a different ISIN | Yes — hard constraint (same-ISIN same-day risks intraday squaring off) |
| 79 | Q-088 | Offset ATOM's gains only, or all realised gains in the account? | All gains in the FY from the broker's trade book, ATOM's identified separately |
| 80 | Q-089 | Limit on harvest frequency? | No hard limit; each opportunity individually approved |

## K. Order lifecycle

| # | Q | Question | Recommendation |
|---|---|---|---|
| 81 | Q-091 | How long to poll for a fill before moving on | 5 min, then leave resting for reconciliation |
| 82 | Q-092 | Partial fills — sell quantity and price | Sell the filled qty at target on actual fill price; remainder stays resting |
| 83 | Q-094 | Idempotency if the engine dies after sending but before recording | Write intent with a client tag **before** sending; match on restart |
| 84 | Q-095 | How you learn a sell filled while the engine was down | Next run's reconciliation + Telegram message |

## L. Reporting, logging, database, ops, dry run, cost of capital

| # | Q | Question | Recommendation |
|---|---|---|---|
| 85 | Q-096 | Calendar months or Indian FY? | Both — monthly rows with FY-to-date totals |
| 86 | Q-101 | DP charges appear in the ledger days later — attribute back to the sell? | Yes where possible, else show as unattributed |
| 87 | Q-102 | Monthly report columns | Full list in the bank — confirm |
| 88 | Q-103 | Export format | CSV v1 |
| 89 | Q-104 | Pull broker ledgers automatically or upload statements? | Auto where an API exists, manual CSV fallback |
| 90 | Q-105 | Benchmark against NIFTY 50? | Not in v1 |
| 91 | Q-111 | Log file naming | `YYYY-MM-DD/<run_id>/<investor>_<broker>_<run_id>.txt` |
| 92 | Q-113 | Google Drive access method | Service account writing to a folder you share (service accounts have no own quota) |
| 93 | Q-115 | Cap Telegram uploads (50 MB bot limit) | gzip above 5 MB, else send the link |
| 94 | Q-120 | Does a Supabase project exist? Free tier pauses after a week idle | — |
| 95 | Q-121 | One schema or several? | One `atom` schema with table prefixes |
| 96 | Q-122 | Migration management | SQL files in repo via Supabase CLI, reviewed like code |
| 97 | Q-123 | Money type | `NUMERIC(18,4)`, never float |
| 98 | Q-124 | Time zone handling | `timestamptz` in UTC, displayed IST, plus an IST `trade_date` column |
| 99 | Q-126 | Tax lot matching method | FIFO |
| 100 | Q-128 | Weekly `pg_dump` to S3 beyond Supabase's own backups? | Yes |
| 101 | Q-129 | Separate Supabase dev project? | Yes |
| 102 | Q-146 | **Exempt trade/order/position tables from the 90-day purge?** | Yes — reports need years; purge only diagnostic log rows |
| 103 | Q-130 | Testing strategy before real money | Unit tests on strategy maths, contract tests per broker, dry run, then ₹1,000-size live trades |
| 104 | Q-131 | Build a backtest harness? | Yes, but after v1 — the history is already being stored |
| 105 | Q-133 | Have you checked each broker's T&C permits automated order placement? | — |
| 106 | Q-134 | Uptime monitoring on the Render site | Free uptime monitor |
| 107 | Q-158 | Confirm the paper fill model (OHLC, limit price only, no partial fills, no market impact) | Agree as written |
| 108 | Q-159 | Compare dry-run and live P&L side by side in reports? | Yes |
| 109 | Q-160 | Paper portfolio retention after going live | Keep indefinitely as a track record |
| 110 | Q-161 | Can a dry run start without EC2 (FREE source needs no IP)? | Yes — useful for cheap scheduled paper runs |
| 111 | Q-163 | Simple or compound interest | Simple |
| 112 | Q-164 | Day-count convention | Actual/365 |
| 113 | Q-166 | Can the borrowing rate change over time? | Yes — dated rate series; never restate history |
| 114 | Q-167 | Accrual base: original cost or current value | Cost |
| 115 | Q-168 | Does the sell day count toward days held? | Count buy day, exclude sell day |
| 116 | Q-169 | Are charges part of the accrual base? | Yes — all-in cost |
| 117 | Q-173 | How is each account's opening balance anchored? | Operator enters opening balance + date at onboarding |
