# Threat Model

**Status:** 🟢 Specified
**Date:** 2026-09-26
**Scope:** ATOM as deployed — one admin, one EC2 instance, five broker accounts, family capital

> The asset worth protecting is not data. It is **the ability to place orders on five brokerage
> accounts holding real family money**. Everything below is ordered by how directly it reaches that.

---

## 1. What we are protecting

| Asset | Loss if compromised |
|---|---|
| **Broker order capability** | Unauthorised trades; capital destroyed within one session |
| Broker credentials (key/secret, 12-month on Dhan) | Persistent order capability, outside ATOM |
| Daily broker tokens | Order capability for up to 24 h |
| **The static Elastic IPs** | 🔴 Up to 7 days of no trading on Dhan (D-173) |
| Audit trail (lots, closures, candidates, `action_audit`) | Cannot prove or reconstruct what happened |
| Tax and P&L data | Financial-position disclosure; no government ID (no PAN stored) |
| Telegram bot token | Ability to start/stop compute — **not** to trade (D-014, by design) |

**No PAN, no bank details, ever** (D-069e). Tax pooling uses a surrogate investor key, so a full
database compromise leaks positions and returns but no government identifier and no payment
instrument.

---

## 2. Trust boundaries

```
 ① operator's phone ──Telegram──► ② Lambda ──IAM──► ③ EC2 instance
                                                       │
 ④ operator's browser ──TLS+TOTP──────────────────────►│
                                                       │
                                        ┌──────────────┼──────────────┐
                                        ▼              ▼              ▼
                                  ⑤ SSM/KMS     ⑥ five brokers   ⑦ Supabase
                                                    (via proxy,
                                                   static egress)
```

| # | Boundary | Control |
|---|---|---|
| ① | Telegram → Lambda | Secret-token header + numeric user allow-list; **no trading commands** |
| ② | Lambda → EC2 | IAM, tag-scoped to `atom:managed`; cannot read `/atom/sessions/*` |
| ③ | Instance → AWS | Instance role; **explicit deny on `ec2:*`** and `s3:DeleteObject` |
| ④ | Browser → console | TLS, password + **mandatory TOTP**, `HttpOnly`/`Secure`/`SameSite=Strict`, CSRF |
| ⑤ | Instance → SSM | Path-scoped reads; values never logged |
| ⑥ | Instance → brokers | Forward proxy binding the registered static IP; fails closed |
| ⑦ | Instance → Supabase | Scoped role, RLS on every table; the browser holds **no** database key |

---

## 3. Threats, in order of severity

### T1 🔴 Broker credentials exfiltrated

| | |
|---|---|
| Vector | Instance compromise · secret in a log · secret in git · developer machine |
| Impact | Persistent order capability from **anywhere the attacker's IP is whitelisted** |
| Mitigations | SSM `SecureString` only, never on disk or in env vars · logger-level redaction (D-069e) · daily tokens destroyed after each run (D-170) · `broker_session` stores the SSM **path**, with a CHECK that it cannot look like a token |
| **Residual** | 🔴 **X1 — Upstox key/secret were committed to the archived repository and are still unrotated** |

**The static-IP requirement is an accidental but real control here.** A stolen token is only usable
from a whitelisted address, and on Dhan the attacker cannot change that address for 7 days either. The
regulation that constrains ATOM also constrains anyone who steals from it.

### T2 🔴 Console session hijacked

| | |
|---|---|
| Vector | XSS · stolen cookie · unlocked laptop |
| Impact | Full trading capability for the session |
| Mitigations | TOTP at login · 12 h absolute / 60 min idle · `SameSite=Strict` + CSRF · no `dangerouslySetInnerHTML` · **the instance is off ~23 h/day**, so the exposure window is ~20 minutes |
| Accepted | A live session can trade. That is its purpose |
| Cannot do | Read a token value · change the egress IP · delete logs (§2 ③) |

The daily stop is the strongest control and it is a side effect of the cost design rather than a
security measure — worth noting, because it means the security posture degrades if the instance ever
becomes always-on.

### T3 🔴 Elastic IP lost

| | |
|---|---|
| Vector | EIP released · instance terminated without re-association · someone "cleaning up" AWS |
| Impact | **Up to 7 days without order placement on Dhan.** No override exists |
| Mitigations | Tag `atom:do-not-release` · instance role **denies `ec2:*`** so the engine cannot detach its own address · backup IP slot registered with every broker that offers one · rebuild runbook opens with "confirm both allocation IDs exist" |
| Residual | A human with AWS console access can still release one |

This is the highest-impact *availability* threat and it is entirely self-inflicted. It is in the threat
model rather than the runbook because the mitigation is a permissions boundary, not a procedure.

### T4 Telegram bot token leaked

| | |
|---|---|
| Impact | Start/stop compute. **Cannot trade** |
| Why bounded | §2 of `../02-infrastructure/LAMBDA-AND-TELEGRAM.md` — no trading commands exist |
| Mitigations | Numeric allow-list · webhook secret token · silence to unauthorised senders |
| Recovery | Revoke via BotFather, rotate in SSM, re-register webhook |

Keeping trading out of Telegram is the single decision that converts a likely credential loss (a phone)
into a nuisance rather than an incident.

### T5 Supabase credentials leaked

| | |
|---|---|
| Impact | Read/write the audit trail and tax data. **No order capability** |
| Mitigations | RLS everywhere · scoped role, never `postgres` · browser holds no key · no PAN or bank details |
| Detectable | Yes — S3 log copies are append-only, so tampering shows as divergence between copies |

### T6 Malicious or wrong broker response

| | |
|---|---|
| Vector | Compromised endpoint · vendor bug · MITM |
| Impact | Wrong holdings → wrong orders |
| Mitigations | TLS with certificate verification, **never disabled** · attribution reconciliation halts on a negative residual · ISIN cross-check between master and holdings · unknown status treated as **in-flight**, never terminal (D-180) · unmapped error halts rather than retries |

The reconciliation gate is the real control: a wrong holdings response that would cause ATOM to sell
what it does not hold produces a negative residual and blocks the run before the sell pass.

### T7 Supply-chain compromise

| | |
|---|---|
| Vector | A malicious Python or npm dependency |
| Impact | Anything the instance can do |
| Mitigations | Pinned versions with hashes · **raw HTTP, no vendor broker SDKs** (D-056b) · minimal frontend dependencies (no component library) · `pip-audit` / `npm audit` in the release process |

The no-SDK decision was taken for capability reasons (D-139) and happens to remove five vendor
dependency trees from the path that touches money.

### T8 Operator error

| | |
|---|---|
| Vector | Releasing the wrong orders · wrong config · wrong universe |
| Mitigations | Block → review → release (D-070b) · every gate and value shown before release · `ConfirmDialog` states the consequence · **no defaults** (D-037) · config frozen per run (D-061) · `DRY` strip undismissable · `action_audit` on every override |
| Not mitigated | A deliberate, informed bad decision. Out of scope |

### T9 Regulatory non-compliance

| | |
|---|---|
| Mitigations | ≤2 OPS hard cap (D-088) · limit orders only (D-174) · static IP registered (D-173) · delivery only, **no margin** (D-207) · full audit trail |
| Residual | **X2 — broker T&C review outstanding.** Governs whether API access for these accounts is permitted at all |

### T10 Data loss

| | |
|---|---|
| Mitigations | Weekly `pg_dump` + PITR · four permanent log copies across three providers · Object Lock governance mode · engine denied `s3:DeleteObject` |
| Residual | An **untested** backup. Mitigated by the quarterly restore into `dev` — which is scheduled, not intended |

---

## 4. Explicitly out of scope

| Out of scope | Why |
|---|---|
| Nation-state adversary | Disproportionate for family capital |
| Physical seizure of AWS hardware | AWS's problem |
| Insider threat | One operator, who is the principal |
| DDoS on the console | One user; the instance is usually off |
| Broker-side compromise | Outside ATOM's control; reconciliation limits the blast radius |
| Multi-tenant isolation | There is one tenant (D-133) |

---

## 5. Detection

| Signal | Channel |
|---|---|
| Egress IP mismatch / shared | Telegram, immediate, run aborted |
| Token invalid | Telegram |
| Negative residual | Telegram, run blocked |
| Console login failures ≥5 | Telegram, with source IP |
| Unauthorised Telegram sender | Logged (id + command only), **no reply** |
| Unrecognised resting sell | Reconciliation exception report |
| Log copies diverging | Manual comparison; the tamper signal |
| CloudTrail on `ec2:*` and KMS | AWS |

**Silence to unauthorised Telegram senders is deliberate**: a bot that answers confirms the token is
live, one that says nothing is indistinguishable from a dead token.

---

## 6. Where the design is weakest

Stated plainly, because a threat model that only lists mitigations is marketing.

| Weakness | Assessment |
|---|---|
| 🔴 **X1 unrotated Upstox credentials** | The one live, known exposure. Nothing in ATOM's design compensates for a credential already public |
| **X2 broker T&C unreviewed** | Could invalidate the whole approach, not just a control |
| **Single admin, no break-glass** | Accepted: a second account doubles the attack surface for a one-person system. Recovery is via AWS + SSM |
| **A live console session can trade** | Irreducible. Bounded by TOTP, a 20-minute daily window, and the three things it cannot do |
| **Charge rates provisional** (Q-313) | Not a security issue but a correctness one, and it affects every reported figure |
| **Instance role trusted broadly within its scope** | An engine compromise reaches SSM tokens. Mitigated by daily destruction, not prevented |

---

## 7. Related

[`SECRETS-MANAGEMENT.md`](SECRETS-MANAGEMENT.md) · [`SEBI-ALGO-COMPLIANCE.md`](SEBI-ALGO-COMPLIANCE.md) ·
[`../06-web/AUTH-AND-ACCESS.md`](../06-web/AUTH-AND-ACCESS.md) ·
[`../02-infrastructure/AWS-TOPOLOGY.md`](../02-infrastructure/AWS-TOPOLOGY.md) §4 ·
[`../02-infrastructure/STATIC-IP-AND-PROXY.md`](../02-infrastructure/STATIC-IP-AND-PROXY.md)
