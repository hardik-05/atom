# Operations Runbook

**Status:** 🟢 Specified
**Date:** 2026-09-26
**Audience:** the operator, at 09:00, possibly in a hurry

> Procedures, not explanations. Each one says what to do, in order, with the decision point stated.
> Rationale lives in the design documents; this file is for when something needs doing now.

---

## 1. Daily routine

### 1.1 Normal morning

```
06:00+   ⚠️ never before 06:00 IST — Zerodha and Groww tokens expire at 06:00 (D-184)

1  Telegram  /start                        → wait for the console URL (~90 s)
2  Console → Overview                      → health strip must be all green
3  For each account: generate the broker token
4  Console → Execute Engine → select universe(s)
5  Pre-flight: four gates must pass
6  Review the proposal — read the skipped list, not only the buys
7  Release
8  Watch to COMPLETED
9  Telegram  /stop        (or let the 60-minute idle timer fire)
```

**Step 6 is the one that matters.** Releasing without reading the skipped list is how a
mis-configured threshold goes unnoticed for weeks.

### 1.2 Token generation, per broker

| Broker | Method |
|---|---|
| **Dhan** | 🟢 Automatic — TOTP, no browser. Nothing to do |
| **Groww** | Click **approve** on Groww's Cloud API Keys page, then generate in ATOM |
| **Upstox** | Console → Authorize → login + 2FA at Upstox → copy the code → paste into ATOM (D-183) |
| **Zerodha** | Console → Authorize → login + 2FA → redirect returns the token |
| **Shoonya** | Authorize → copy the code → paste. ⚠️ Token transport unconfirmed (Q-310) |

### 1.3 Pre-flight failed — what each means

| Gate | Meaning | Action |
|---|---|---|
| **Egress IP ✗** | 🔴 Wrong source address | **§3.1 — do not retry the run** |
| **Token ✗** | Expired, invalid, or revoked | Regenerate (§1.2) |
| **Calendar ✗** | Holiday or outside the window | Nothing — correct behaviour |
| **Sell-auth ✗** | Depository authorisation needed | §3.4 |

---

## 2. Weekly and periodic

| When | Task |
|---|---|
| **Saturday** | Universe rebuild job. Check the two CSVs in Telegram (D-058g). No static IP needed (D-057) |
| Monthly | Generate R6 statements; review charges contrast for drift |
| Quarterly | R10 tax computation · **restore a backup into `dev`** (§5.3) · `pip-audit` / `npm audit` |
| At 11 months | Rotate broker API keys — Dhan's expire at 12 |
| FY end (March) | Final R10; confirm exemption usage and loss-pool vintages |

**The quarterly restore test is not optional.** An untested backup is a belief. It is listed here
because things not on a list do not happen.

---

## 3. Incidents

### 3.1 🔴 Egress IP mismatch

```
1  DO NOT retry. A retry from the wrong address fails identically
2  AWS console → confirm both Elastic IPs are still allocated
       └─ one released?  → §3.2 immediately
3  Confirm each EIP is associated with the right secondary private IP
4  On the instance:  systemctl status atom-proxy
5  Confirm the nginx proxy_bind values match the private IPs
6  Fix, then:  python scripts/verify_egress_ip.py
7  Only when it passes: re-run
```

**Why no retry:** the address is wrong, not flaky. And on Dhan, orders may already have been sent from
a non-whitelisted address with no IP-specific error code (Q-305) — so confirm the order book before
assuming nothing happened.

### 3.2 🔴 An Elastic IP was released

The worst operational incident in the system.

```
1  Try to re-allocate the SAME address immediately — AWS sometimes permits it briefly
2  If recovered: re-associate, verify, resume. No broker action needed
3  If NOT recovered, per broker:
     Dhan     → is the BACKUP IP registered?  yes → switch to it
                                              no  → 🔴 NO TRADING for up to 7 days
     Shoonya  → switch to the backup slot, or update (no lock documented)
     Upstox   → update in the developer console
     Zerodha / Groww → procedure unknown (Q-274) — contact support
4  Set the affected account to DRY so runs do not attempt orders
5  Record the new address and the earliest permitted change date
```

There is **no override for Dhan's 7-day lock.** This is why the instance is stopped and never
terminated, and why `atom:do-not-release` tags exist.

### 3.3 Negative attribution residual

```
1  The run is already blocked — correct behaviour
2  Console → Holdings → find the negative row
3  Compare ATOM's open lots against the broker's holdings
4  Most likely: a manual sell outside ATOM, or a corporate action
5  Manual sell     → record it so lots close correctly
   Corporate action → apply the ratio on confirmation (D-091 / Q-260)
   Transfer out     → mark the quantity excluded
6  Re-run reconciliation; residual must be 0 (or positive)
7  Re-run
```

Never "force" past a negative residual. ATOM would place sells for stock that is not there.

### 3.4 Sell authorisation required

| Broker | Scope | Action |
|---|---|---|
| **Upstox** | One-time (EDIS) | In the Upstox app, start a GTT sell and complete the authorisation flow. **Do not complete the order** — going through the flow is enough |
| **Zerodha** | **Per session**, until 5:30 PM | Console → Authorise holdings → CDSL → **demat PIN** (known only to the operator and CDSL). Authorise the **whole holding**, not just today's quantity |
| **Dhan** | DDPI | If `ddpi` is inactive, activate it with Dhan |

Zerodha's is a **daily** step unless DDPI is active (**X10 / Q-280**). Checking DDPI status is the
cheapest way to remove it permanently.

### 3.5 Order rejected

```
1  Console → Orders → read the VERBATIM reject_reason (D-042)
2  Insufficient funds → expected (D-052). Add funds or accept the skip
3  Not sellable / authorisation → §3.4
4  Price outside circuit → check the band; the limit price was outside it
5  Invalid symbol → 🔴 instrument resolution bug. Do NOT retry; investigate the master sync
6  Unknown → do not retry. Preserve the payload and investigate
```

**Never blind-retry a rejection.** A rejection is information; retrying discards it.

### 3.6 GTT cancel could not be verified

```
1  The run halted — correct behaviour (D-055)
2  Read the broker's GTT book directly
3  Still resting?  → cancel manually, confirm, then re-run
4  Dhan: DELETE returns 202 Accepted, not cancelled — always re-poll (Q-185)
5  Zerodha: an active GTT carries NO ATOM identifier (D-176).
      Compare the broker's list against ATOM's stored trigger_ids.
      An orphan needs MANUAL cancellation — there is no API path
```

### 3.7 Partial harvest — sold leg filled, proxy leg did not

```
1  ATOM waits for the operator by design (D-070b)
2  The position is EXPOSED — cash is uninvested and the loss is booked
3  Decide:  (a) buy the proxy manually, then record it
           (b) buy a different proxy
           (c) leave in cash and accept the exposure
4  Whichever: record it so the carried basis attaches to the right lot
5  If nothing is bought, the carried basis has nowhere to go — record that too
```

Step 5 is the trap. A booked loss with no proxy means the synthetic basis is not carried anywhere,
and the position simply realised a loss — which is a legitimate outcome but must be recorded as such.

### 3.8 Instance will not boot

```
1  Telegram /status
2  AWS console → instance state and system log
3  Booted but no console?  → step 3 of the boot sequence failed:
      verify_egress_ip did not pass, so atom-web was deliberately not started
4  SSM Session Manager (port 22 is closed by design):
      systemctl status atom-proxy atom-web
      journalctl -u atom-web -n 100
      python scripts/verify_egress_ip.py
```

An instance that boots without serving a console is usually working correctly — it is refusing to
serve a trading UI it cannot prove the egress for.

### 3.9 Console unreachable but the instance is up

```
1  Likely the Route 53 record — the instance may have stopped without /stop (Q-312)
2  Reach the console directly on EIP-A (TLS will warn on a bare IP)
3  Correct the A record
4  Confirm atom-web is running
```

---

## 4. Onboarding a new account

```
1  Allocate an Elastic IP              ← reversible
2  Associate to a new secondary private IP
3  Add the nginx proxy block; assign a port
4  Create investor + trading_account rows, execution_mode = DRY
5  Set proxy_url and egress_ip
6  python scripts/verify_egress_ip.py  ← MUST pass
7  Register the IP with the broker      ← 🔴 irreversible for 7 days on Dhan
8  Register the BACKUP IP slot too
9  Broker API key/secret → SSM
10 Complete sell authorisation (Upstox EDIS / Zerodha DDPI)
11 Auto-exclude all existing holdings (D-137); start accrual at the onboarding date
12 Instrument sync; confirm ISIN resolution
13 At least one full DRY run
14 Verify computed charges against a real contract note (Q-313)
15 Promote to LIVE
```

**Steps 1–6 before step 7.** Registering an address ATOM has not proved it egresses from means
discovering the error after the lock engages.

**Step 14 is not optional.** STT rates for ETFs are provisional (`../08-reporting/CHARGES-MODEL.md`
§5.1), and a 100× error would corrupt every `unit_cost`.

---

## 5. Maintenance

### 5.1 Deploying a release

See [`../02-infrastructure/DEPLOYMENT.md`](../02-infrastructure/DEPLOYMENT.md) §7. Short form:
`pg_dump` → migrations on `dev` → dry run on `dev` → `pg_dump` on prod → migrations → `git pull` →
restart → dry run per account → restore `LIVE`.

### 5.2 Rebuilding the instance

[`../02-infrastructure/DEPLOYMENT.md`](../02-infrastructure/DEPLOYMENT.md) §6. **Step 0 is confirming
both Elastic IP allocation IDs still exist.**

### 5.3 Quarterly restore test

```
1  Pick the most recent weekly pg_dump from S3
2  Restore into the dev Supabase project
3  Confirm row counts on: position_lot · lot_closure · tax_gain · charge · action_audit
4  Run one report against the restored data; compare against production
5  Record the result. A failure is an incident, not a note
```

---

## 6. Escalation

| Situation | Who |
|---|---|
| Broker API behaving unexpectedly | That broker's API support (Shoonya: `apisupport@shoonya.com`, 0172-4740000) |
| IP whitelisting problem | Broker support — mention the 7-day lock on Dhan |
| Tax treatment uncertainty | A chartered accountant. ATOM computes; it does not advise |
| Regulatory question | Broker compliance desk |
| AWS | AWS support |

---

## 7. Quick reference

| | |
|---|---|
| Telegram | `/start` `/stop` `/status` `/logs` `/runs` `/help` |
| Console | `https://metalcocapital.com` |
| Never before | **06:00 IST** (token expiry) |
| Market | 09:15 – 15:30 IST |
| Idle shutdown | 60 minutes |
| Logs, recent | Console → Logs (90 days) |
| Logs, files | Telegram, Google Drive |
| SSH | 🚫 closed — use SSM Session Manager |
| Verify egress | `python scripts/verify_egress_ip.py` |

### 7.1 The three things never to do

1. **Never release an Elastic IP.** Up to 7 days of no trading on Dhan.
2. **Never force past a negative residual.** ATOM would sell stock that is not there.
3. **Never blind-retry a rejected order.** Read the reason first.
