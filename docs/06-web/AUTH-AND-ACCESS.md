# Authentication and Access

**Status:** 🟢 Specified
**Date:** 2026-09-26
**Basis:** D-040 — single admin login, no other roles

---

## 1. The access model

| | |
|---|---|
| Console users | **One admin.** No other roles, no user management |
| Investors whose accounts are traded | **No access at all** (D-040) |
| Telegram | Allow-listed numeric user IDs (D-014); **no trading commands** |
| AWS | IAM Identity Center + MFA; no long-lived keys |
| Database | Supabase RLS from day one (D-069e) |

> The people whose money is traded do not log in. They receive reports. This is a family
> arrangement operated by one admin, not a multi-tenant product — and pretending otherwise would add
> an authorisation surface with no user.

---

## 2. Console login

```
1  operator opens https://metalcocapital.com
2  if the engine is down  → Render static site, NO login button
3  if the engine is up    → login form
4  credentials + TOTP     → session cookie
```

| | |
|---|---|
| Credentials | Single admin username + password (argon2id) |
| Second factor | **TOTP, mandatory** |
| Session | `HttpOnly` · `Secure` · `SameSite=Strict` cookie, server-side session record |
| Lifetime | 12 h absolute, 60 min idle |
| CSRF | Double-submit token on every mutating request |
| Rate limit | 5 attempts per 15 min, then a 15-min lock |
| Lockout alert | To Telegram, with the source IP |

**TOTP is not optional.** The console can move real money across five brokers; a password alone
protects it with one factor that is also the most commonly reused secret a person has.

**The absence of a login button on the static site matters** (D-018): the failover site is public and
must not present a login that cannot work. Its absence is also the only visible difference between
the two sites.

---

## 3. What the console can and cannot reach

| | |
|---|---|
| Can | Everything in `atom.*` through the API; place, cancel and release orders; override blocks |
| Cannot | Read a broker token value — the API returns SSM **paths**, never secrets (D-079) |
| Cannot | Modify the instance's networking — the instance role denies `ec2:*` |
| Cannot | Delete logs — `s3:DeleteObject` denied |

So a compromised console session can trade, which is unavoidable — that is its purpose. It cannot
exfiltrate credentials, change the egress IP, or destroy the audit trail. Those three exclusions are
what bound the damage.

---

## 4. Database access

### 4.1 RLS from day one (D-069e)

Every table in `atom` has RLS enabled. The API connects as a role scoped to the `atom` schema —
never as `postgres`, never with the service key from the browser.

The browser holds **no Supabase key at all**. All database access is through the engine's API, so
there is one authorisation point rather than two.

### 4.2 No PAN, no bank details — ever (D-069e)

| Stored | Not stored |
|---|---|
| A **surrogate investor key** | The PAN number itself |
| Broker client IDs | Bank account numbers, IFSC |
| SSM **paths** to tokens | Token values |
| Declared slab rate | Income figures beyond the slab |

Tax computation needs a *per-PAN identity* for pooling and the ₹1.25 L exemption — but it does not
need the number. A surrogate key gives the grouping without holding the identifier, so a database
compromise leaks no government ID.

### 4.3 Log redaction (D-069e)

Redaction is applied at the **logger**, not at the call site:

| Redacted | Rendered as |
|---|---|
| Tokens, API keys, secrets | `[REDACTED]` |
| TOTP codes, PINs | `[REDACTED]` |
| Anything matching a PAN pattern | `[REDACTED-PAN]` |
| Session cookies | `[REDACTED]` |

Call-site redaction fails the first time someone logs a whole request object. Logger-level redaction
holds regardless of what is passed in, which is the only version that survives contact with a
debugging session at 9 a.m.

---

## 5. Secret inventory

Full handling in [`../09-security/SECRETS-MANAGEMENT.md`](../09-security/SECRETS-MANAGEMENT.md).

| Secret | Where | Rotation |
|---|---|---|
| Broker API key / secret | SSM `SecureString` `/atom/brokers/*` | Dhan keys expire at 12 months |
| Broker daily token | SSM `/atom/sessions/*` | **Created and destroyed daily** (D-170) |
| Supabase service key | SSM `/atom/db/*` | On suspicion |
| Telegram bot token | SSM `/atom/telegram/*` | On suspicion |
| Console admin password hash | Database | On suspicion |
| TOTP seed | SSM | On device change |

**Daily tokens are destroyed at end of run** (D-170), and `broker_session` carries a CHECK
constraint that the stored `secret_ref` cannot look like a token. A stolen database yields nothing
once the SSM parameter is gone — which is the point of storing paths rather than values.

---

## 6. Known gaps

Stated rather than left implicit.

| Gap | Assessment |
|---|---|
| Single admin account — no break-glass second account | Accepted. A second account would double the attack surface for a single-operator system. Recovery is via AWS + SSM directly |
| Password reset is manual | Accepted; there is no email flow and no second user to notify |
| **X1 — exposed Upstox credentials in the archived repository** | 🔴 **Still outstanding.** Must be rotated regardless of ATOM's own hygiene |
| Broker T&C review (**X2**) | Outstanding; governs whether API access for these accounts is permitted at all |
| Console session cannot be revoked remotely | A stop via Telegram kills the instance and every session with it — crude but effective |

The last row is worth noting as an accidental strength: because the console lives on an instance that
is stopped most of the day, its exposure window is roughly 20 minutes daily rather than continuous.
