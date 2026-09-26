# Logging Specification

**Status:** 🟢 Specified
**Date:** 2026-09-26
**Basis:** D-030 (two tiers) · D-031 (detailed logs are files, to Telegram) · D-057g (hard failures
to three places) · D-069e (redaction)

> Two tiers, deliberately. **Structured rows** answer "what happened and why" by query;
> **detailed files** answer "what exactly did the broker say" by reading. Neither substitutes for
> the other, and the structured tier is not a log — it is data.

---

## 1. The two tiers

| | Tier 1 — structured | Tier 2 — detailed |
|---|---|---|
| Form | Rows in `atom.run_log` | `.log` / `.txt` file per run |
| Content | One row per meaningful event, typed fields | Full human-readable narrative |
| Queryable | ✅ SQL | ❌ grep |
| Destination | Supabase | Telegram · S3 · S3 Deep Archive · Google Drive · instance-local |
| Retention | **90-day purge** | Telegram + Drive + Deep Archive **permanent**; S3 standard and instance-local **30-day rolling** |
| Audience | The console's Logs screen; the operator asking *why* | Forensics; a vendor support ticket |

### 1.1 Why the decision record is *not* in the log

The reason a candidate was bought or skipped lives in **`run_candidate`** — a table with every gate's
input and verdict, `decision` and `decision_reason` (D-035). Not in `run_log`, and not in the file.

That distinction is the single most important thing in this document. A log is prose that rots: it
gets reworded, truncated, purged at 90 days, and cannot be aggregated. The decision record is data
with a schema and no expiry. **A year later, one `run_id` must explain a decision with no log
archaeology** — which is only possible if the explanation was never in a log to begin with.

`run_log` carries the *narrative around* the decision: phase boundaries, timings, retries, broker
round-trips, warnings.

---

## 2. Structured events

```sql
-- atom.run_log
run_id · seq · ts · level · phase · event · message · context jsonb
```

| Field | |
|---|---|
| `level` | `DEBUG` `INFO` `WARN` `ERROR` `FATAL` |
| `phase` | `PREFLIGHT` `REFERENCE` `RECONCILE` `SELL` `BUY` `HARVEST` `SETTLE` |
| `event` | A stable machine-readable slug — **never free text** |
| `message` | Human-readable, may change |
| `context` | Typed jsonb: ids, quantities, prices, broker codes |

**`event` is a closed vocabulary.** Because it is stable, `WHERE event = 'EGRESS_IP_MISMATCH'` keeps
working after someone improves the wording of `message`. Free-text event names would make every
query a `LIKE` against prose.

### 2.1 Events that must always be emitted

Not an exhaustive list — the set whose absence would make an incident unexplainable.

| Phase | Events |
|---|---|
| Pre-flight | `EGRESS_IP_VERIFIED` · `EGRESS_IP_MISMATCH` · `EGRESS_IP_SHARED` · `TOKEN_PROBE_OK` · `TOKEN_INVALID` · `SELL_AUTH_REQUIRED` · `CALENDAR_CLOSED` |
| Reference | `INSTRUMENTS_SYNCED` · `INSTRUMENT_TOKEN_CHANGED` · `ISIN_UNRESOLVED` · `PRICES_FETCHED` · `NAV_FETCHED` · `TICK_SIZE_MISMATCH` |
| Reconcile | `RESIDUAL_ZERO` · `RESIDUAL_POSITIVE` · `RESIDUAL_NEGATIVE` · `FREE_QTY_UNAVAILABLE` |
| Sell | `GTT_CANCEL_SENT` · `GTT_CANCEL_VERIFIED` · `GTT_CANCEL_UNVERIFIED` · `UNRECOGNISED_RESTING_SELL` · `TRANCHE_COMPUTED` · `GTT_PLACED` · `GTT_FALLBACK_DAY_LIMIT` |
| Buy | `CANDIDATE_EVALUATED` · `GATE_FAILED` · `PROXY_BLOCK_HIT` · `ORDER_INTENT_WRITTEN` · `ORDER_PLACED` · `ORDER_REJECTED` |
| Harvest | `HARVEST_PROPOSED` · `HARVEST_CHAIN_BLOCKED` · `HARVEST_EXECUTED` · `HARVEST_PARTIAL` |
| Settle | `FILL_INGESTED` · `LOT_CREATED` · `LOT_CLOSED` · `CHARGES_COMPUTED` · `CHARGES_REPORTED` · `ACCRUAL_WRITTEN` · `TOKEN_CLEARED` |

`INSTRUMENT_TOKEN_CHANGED` and `TICK_SIZE_MISMATCH` are in the list because both are silent
correctness hazards: a changed broker token would route the next order to a different security
(D-187), and an inconsistent tick would mis-round every limit price (D-209).

---

## 3. Detailed file (tier 2)

One file per run: `atom-{trade_date}-{account}-{universe}-{run_id}.log`

```
2026-09-26T09:32:04+05:30  INFO   PREFLIGHT  Egress IP verified: 13.234.x.x (expected 13.234.x.x)
2026-09-26T09:32:05+05:30  INFO   PREFLIGHT  Token probe via GET /v2/profile → tokenValidity 27/09/2026 06:00
2026-09-26T09:32:11+05:30  INFO   SELL       Cancelling 3 ATOM GTTs
2026-09-26T09:32:12+05:30  DEBUG  SELL       → DELETE /v2/forever/orders/5132208051112 → 202 Accepted
2026-09-26T09:32:14+05:30  INFO   SELL       Re-poll: 0 ATOM GTTs resting — verified clean
2026-09-26T09:32:16+05:30  INFO   SELL       GOLDBEES tranche SYNTHETIC qty 20 basis ₹95.0000 target ₹98.3300
```

| Rule | |
|---|---|
| Timestamps | **IST, tz-aware, ISO-8601** — always. Never naive, never UTC-only |
| Every broker round-trip at `DEBUG` | Method, path, status, latency. **Never the body of an auth request** |
| Verbatim broker text preserved | `reject_reason`, `emsg`, `omsErrorDescription` (D-042) |
| Gzip above 10 MB (D-072e) | |
| Also written locally | The instance may be about to stop |

### 3.1 Redaction at the logger (D-069e)

| Pattern | Rendered |
|---|---|
| Bearer tokens, `access-token`, `jKey`, `susertoken` | `[REDACTED]` |
| `api_secret`, `app_secret`, `secret_code`, checksums | `[REDACTED]` |
| TOTP codes, PINs | `[REDACTED]` |
| PAN-shaped strings | `[REDACTED-PAN]` |
| Telegram bot token | `[REDACTED]` |

Applied in the **logging formatter**, not at call sites. Call-site redaction fails the first time
somebody logs a whole request object while debugging — which is exactly when logging is most verbose
and least careful.

> A spot-check for a token pattern in the shipped file is part of the test suite, not a habit.

---

## 4. Hard failures go to three places (D-057g)

```
FATAL / ERROR ──┬──► Telegram (immediate, to the group)
                ├──► run_log row (structured, queryable)
                └──► instance-local file (/var/log/atom/)
```

**Because the failure may be the instance itself.** Telegram survives the instance stopping; the
local file survives Telegram being unreachable; the `run_log` row survives both for later forensics.
Any single destination can be the one that fails.

---

## 5. Levels — what each is for

| Level | Use | Volume |
|---|---|---|
| `DEBUG` | Broker round-trips, gate arithmetic | File only, not `run_log` |
| `INFO` | Phase boundaries, decisions taken, orders placed | Both |
| `WARN` | Positive residual · `free_quantity` unavailable · unrecognised resting sell · Zerodha `discrepancy` · 12-month boundary proximity | Both |
| `ERROR` | One order failed; the run continues | Both + Telegram |
| `FATAL` | The run is aborted | Both + Telegram + local |

**`WARN` is not noise and must stay rare.** Every item in that row is a condition the operator should
look at. If warnings become routine, they stop being read — so a warning that fires every run is a
bug in either the code or the threshold, and is treated as one.

---

## 6. Correlation

Every log line, row and file carries `run_id`. Orders additionally carry `client_ref`, which is the
**same identifier ATOM sent to the broker** (D-175). So a broker support query, ATOM's log, and the
database row can all be joined on one string — which matters precisely when something has gone
wrong and a vendor is asking what was sent.

---

## 7. What is not logged

| Not logged | Why |
|---|---|
| Token values, secrets, PINs, checksums | §3.1 |
| Full PAN | Never stored at all (D-069e) |
| Prices for every instrument on every tick | There are no ticks — snapshots only (D-041) |
| Successful HTTP bodies at `INFO` | `DEBUG` and the file; otherwise the log becomes the response cache |
| The decision rationale | It belongs in `run_candidate` — §1.1 |

---

## 8. Related

[`ARCHIVAL.md`](ARCHIVAL.md) · D-030 · D-031 · D-035 · D-042 · D-057g · D-069e · D-072e ·
[`../01-architecture/RUN-LIFECYCLE.md`](../01-architecture/RUN-LIFECYCLE.md)
