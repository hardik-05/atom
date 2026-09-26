# Static IP and Egress Proxy

**Status:** 🟢 Specified
**Date:** 2026-09-26
**Regulatory basis:** SEBI *Safer participation of retail investors in Algorithmic trading* ·
NSE/INVG/67858 — **mandatory since 1 April 2026** (D-173)

> Every investor's broker traffic must leave from **that investor's own registered static IPv4
> address**. ATOM achieves this with one forward proxy per address on a single instance, so the
> adapters stay IP-agnostic and the binding is enforced in one place.

---

## 1. Why this exists, and why it is not optional

Three of the five brokers document the requirement explicitly, and they enforce it differently:

| Broker | Enforcement | Failure signature |
|---|---|---|
| **Upstox** | All calls | `UDAPI1154` — *"Access to this API is blocked due to static IP restrictions"* |
| **Shoonya** | 🟢 **Login itself** | Auth failure before any order — fails early and loudly |
| **Dhan** | 🔴 **Order placement only** | Reads succeed; the first order fails with **no IP-specific code** (Q-305) |
| Zerodha | ❓ undocumented (Q-274) | Assume all calls |
| Groww | ❓ undocumented (Q-274) | Assume all calls |

**Dhan's row is the dangerous one.** Holdings, order book and trade book work from *any* address, so
the D-170 token probe passes, reconciliation passes, and the failure appears only when the first
order is sent — by which point the sell pass has already cancelled the previous day's GTTs.

That is why egress verification is a **standalone pre-flight gate**, not a side effect of the token
probe (`../01-architecture/RUN-LIFECYCLE.md` §3.1).

---

## 2. Design

```
   ATOM engine (one process)
        │
        │  adapter receives proxy_url from config — never an IP
        │
        ├── investor A  →  http://127.0.0.1:3128 ──┐
        └── investor B  →  http://127.0.0.1:3129 ──┤
                                                   │
        ┌──────────────────────────────────────────┴──────────┐
        │  nginx (stream module), one server block per proxy  │
        │    :3128   proxy_bind 10.0.1.10   → EIP-A           │
        │    :3129   proxy_bind 10.0.1.11   → EIP-B           │
        └─────────────────────────────────────────────────────┘
                     │                      │
                  EIP-A                  EIP-B
             registered with          registered with
             A's five brokers         B's five brokers
```

**The adapter never knows an IP address.** It receives `trading_account.proxy_url` and uses it as an
HTTP proxy. The mapping from proxy port to source address lives entirely in nginx configuration, so
adding an investor is: allocate an EIP → add a secondary private IP → add one nginx block → set
`proxy_url` and `egress_ip` on the account. No Python changes.

This is D-005 as built, and it is the reason the adapters could be specified without reference to
networking at all.

### 2.1 Why a forward proxy rather than source-address binding in Python

Binding the source address per request is possible in Python but has to be done in every HTTP call
site, which means **one missed call silently egresses from the wrong address**. On Dhan that
produces a rejection with no IP-specific error code; the fault would be invisible.

A proxy makes the binding structural: a request either goes through the proxy or it fails to
connect. There is no "works but from the wrong IP" state. Given that the failure mode is a silent
one on the broker that matters most, that property is worth an extra hop.

The SDK evaluation reinforced it independently: Groww's and Shoonya's own Python SDKs use bare
module-level `requests` calls with no session object, so **per-instance proxying through them is
impossible** (D-139). The proxy approach works regardless of what a vendor library does — and ATOM
uses raw HTTP anyway (D-056b).

### 2.2 nginx configuration sketch

```nginx
stream {
    server {
        listen 127.0.0.1:3128;
        proxy_bind 10.0.1.10;          # → EIP-A
        proxy_pass $upstream;          # CONNECT target
    }
    server {
        listen 127.0.0.1:3129;
        proxy_bind 10.0.1.11;          # → EIP-B
        proxy_pass $upstream;
    }
}
```

Both listeners bind **`127.0.0.1` only**. An open forward proxy reachable from the internet is
abused within hours, and there is no reason for these ports to be reachable at all.

> ⚠️ **nginx is the starting approach, not a commitment** (D-005). If HTTPS `CONNECT` handling
> through `stream` proves awkward, the documented fallbacks are **tinyproxy** (simpler, purpose-built
> for forward proxying) or **one lightweight container per investor with its own network namespace**.
> The abstraction — `proxy_url` per account — survives any of them, which is the point of putting
> the seam there.

---

## 3. Verification — `verify_egress_ip.py`

Already written (`scripts/verify_egress_ip.py`). It **fails closed** and detects shared addresses.

```
for each account:
    observed = GET https://api.ipify.org  via account.proxy_url
    if observed != account.egress_ip:                 → EGRESS_IP_MISMATCH   (abort)
    if observed appears for more than one account:    → EGRESS_IP_SHARED     (abort)
```

**Run on every run, not only at onboarding.** A silent IP change is a week-long outage on Dhan, not
a restartable error, so it has to be caught before the first order rather than inferred from a
rejection afterwards.

| Check | Catches |
|---|---|
| Mismatch | EIP detached, reassociated, or nginx binding wrong |
| Shared | Two accounts routed through the same proxy — a config error that Dhan explicitly forbids ("each individual needs to have a unique static IP") and that would look like it worked |
| No proxy configured on a `LIVE` account | Impossible by construction — `trading_account_live_needs_proxy_ck` |

More than one IP-check service is queried, because a single provider being unreachable must not read
as a mismatch. Ambiguity resolves to abort, never to proceed.

---

## 4. Registration, per broker

| Broker | Where | Notes |
|---|---|---|
| **Dhan** | **API** — `POST /v2/ip/setIP` | Primary + secondary. 🔴 **Locked 7 days.** `GET /v2/ip/getIP` returns the earliest change date |
| **Shoonya** | Trading account → API Key Generation | Primary + backup, IPv4 or IPv6. Leave the ">10 OPS" box **unchecked** |
| **Upstox** | Developer console | Procedure not in the docs (Q-274) |
| Zerodha | ❓ (Q-274) | |
| Groww | ❓ (Q-274) | |

**Register the secondary/backup slot too**, wherever the broker offers one. It costs nothing and it
is the only fast path if the primary address is ever lost — on Dhan, the difference between a
failover and a seven-day outage.

Record per account, per broker: the registered address, the registration date, and the earliest
permitted change date.

---

## 5. Ordering — this sequence is not interchangeable

```
1  Allocate the Elastic IP                     ← reversible
2  Associate it with a secondary private IP
3  Add the nginx block; set proxy_url
4  Run verify_egress_ip.py and confirm
5  Register the address with the brokers        ← 🔴 becomes irreversible for 7 days on Dhan
6  Set trading_account.egress_ip
7  First DRY run
8  Promote to LIVE
```

**Steps 1–4 before step 5.** Registering an address ATOM has not yet proved it egresses from means
discovering the error after the lock has engaged.

---

## 6. Failure handling

| Failure | Blast radius | Response |
|---|---|---|
| Mismatch on one account | that account's run | Abort, alert. **Never retry** — retrying a wrong IP just fails again |
| Mismatch on all accounts | everything | EIPs likely detached; stop, fix networking, re-verify before any run |
| Shared address detected | both accounts | Abort both. A config error, not a transient one |
| EIP lost after release | 🔴 up to 7 days on Dhan | Register the backup slot; if none, the account cannot trade until the lock lifts |
| Proxy process down | the account | Abort. Nothing egresses from the wrong address — the proxy failing closed is the desired behaviour |

**The proxy failing is safer than the proxy being wrong**, which is the whole argument for §2.1.

---

## 7. Related

D-005 (local forward proxy) · D-009…D-011 (per-investor static egress) · D-139 (vendor SDKs cannot
be proxied) · D-173 (regulation; 7-day lock; egress verified separately) ·
[`AWS-TOPOLOGY.md`](AWS-TOPOLOGY.md) §3 · `scripts/verify_egress_ip.py` ·
`../01-architecture/RUN-LIFECYCLE.md` §3.1
