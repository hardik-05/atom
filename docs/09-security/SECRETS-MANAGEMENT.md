# Secrets Management

**Status:** 🟢 Specified
**Date:** 2026-09-26
**Basis:** D-079 (store the SSM path, never the token) · D-170 (daily tokens, destroyed after each
run) · D-069e (redaction)

> One rule above all others: **the database stores a path to a secret, never a secret.** A stolen
> database yields nothing once the SSM parameter is gone.

---

## 1. Inventory

| Secret | Store | Path | Lifetime | Rotation |
|---|---|---|---|---|
| Broker API key + secret | SSM `SecureString` | `/atom/brokers/{broker}/{account}/key`, `/secret` | **12 months** (Dhan states this explicitly) | Calendar reminder at 11 months |
| Broker daily token | SSM `SecureString` | `/atom/sessions/{account}/{trade_date}` | **≤ 24 h** | Created each morning, **deleted after each run** |
| Broker TOTP seed | SSM `SecureString` | `/atom/brokers/{broker}/{account}/totp` | Long-lived | On device change |
| Broker PIN | SSM `SecureString` | `/atom/brokers/{broker}/{account}/pin` | Long-lived | On suspicion |
| Supabase service key | SSM `SecureString` | `/atom/db/service_key` | Long-lived | On suspicion |
| Telegram bot token | SSM `SecureString` | `/atom/telegram/bot_token` | Long-lived | On suspicion |
| Telegram webhook secret | SSM `SecureString` | `/atom/telegram/webhook_secret` | Long-lived | With the bot token |
| Google Drive service-account JSON | SSM `SecureString` | `/atom/drive/sa_json` | Long-lived | On suspicion |
| Console admin password | Database, **argon2id hash** | — | — | On suspicion |
| Console TOTP seed | SSM `SecureString` | `/atom/console/totp` | — | On device change |
| TLS private key | Instance, `0600`, root | — | 90 days | Automated |

All encrypted with a **customer-managed KMS key**, not the AWS-managed default. The CMK is what makes
`kms:Decrypt` an auditable, revocable grant rather than an ambient capability.

**Why SSM rather than Secrets Manager:** Secrets Manager is $0.40 per secret per month — at ~12
secrets, ~$5/month against a total AWS bill of ~$9. It buys automatic rotation, which ATOM does not
use for any of these (broker rotation is a manual vendor-side action). SSM `SecureString` gives
KMS encryption, IAM path scoping and CloudTrail for free.

---

## 2. 🔴 The daily token pattern (D-079, D-170)

This is the design's most important security property and it is worth stating as a sequence.

```
morning   operator generates a token   → SSM /atom/sessions/{account}/{date}
          broker_session row           → status VALID, secret_ref = the PATH
during    engine reads the path → fetches from SSM → uses in memory only
end       DELETE the SSM parameter
          broker_session               → status CLEARED, secret_ref NULL
```

### 2.1 `broker_session` holds a path, and the schema enforces it

```sql
secret_ref text,   -- SSM path — NEVER the token itself
CONSTRAINT broker_session_no_secret_ck
    CHECK (secret_ref IS NULL OR secret_ref NOT LIKE '%Bearer%')
```

The CHECK is a crude pattern match and deliberately so: it will not catch every possible token shape,
but it **will** catch the most likely mistake — someone storing a `Bearer …` header value during
debugging and forgetting to remove it. A cheap constraint that catches the realistic error beats an
elegant one that catches none.

### 2.2 Why daily destruction matters more than encryption

An encrypted token is still a token: anyone who can read SSM can decrypt it, because the engine must
be able to. **Destruction removes the asset.** After the run there is nothing to steal, so the window
of exposure is the run itself — minutes — rather than the token's nominal 24 hours.

And validity is **probed, never computed** (D-170), so a token invalidated early is detected rather
than trusted. No expiry arithmetic exists anywhere in the codebase.

### 2.3 Tokens are never written to disk

Fetched into memory, used, discarded. Not cached to a file, not in an environment variable, not in a
temp file. An environment variable is visible to anything that can read `/proc/{pid}/environ` and is
inherited by child processes — including, historically, crash reporters.

---

## 3. Access control

### 3.1 Instance role — path-scoped

| Allow | Path |
|---|---|
| `ssm:GetParameter(s)` | `/atom/brokers/*`, `/atom/db/*`, `/atom/drive/*`, `/atom/sessions/*` |
| `ssm:PutParameter`, `DeleteParameter` | **`/atom/sessions/*` only** |
| `kms:Decrypt` | the CMK |

**Write access is narrowed to the daily-session path.** The engine creates and destroys tokens; it
cannot overwrite a long-lived broker key. So an engine compromise cannot lock the operator out by
replacing credentials, and cannot escalate by planting its own.

### 3.2 Lambda role

Reads **only** `/atom/telegram/*`. It has no path to broker credentials or database keys — which is
what makes T4 in the threat model bounded.

### 3.3 Humans

IAM Identity Center + MFA. Read access to `/atom/*` for the operator; **no long-lived access keys
anywhere**. CloudTrail records every `GetParameter` and `Decrypt`.

---

## 4. Redaction (D-069e)

Applied in the **logging formatter**, not at call sites:

| Pattern | Rendered |
|---|---|
| `Authorization: Bearer …`, `access-token:`, `jKey=`, `susertoken` | `[REDACTED]` |
| `api_secret`, `app_secret`, `secret_code`, `client_secret`, `checksum` | `[REDACTED]` |
| TOTP codes, PINs | `[REDACTED]` |
| PAN-shaped strings | `[REDACTED-PAN]` |
| Telegram bot token | `[REDACTED]` |
| Supabase keys | `[REDACTED]` |

**Formatter-level, because call-site redaction fails the first time someone logs a whole request
object** — which happens precisely when debugging, when logging is most verbose and least careful.

A test asserts that a synthetic token planted in a log call does not appear in the shipped output.
That test is the control; the table above is documentation of it.

---

## 5. Rotation

| Secret | Trigger | Procedure |
|---|---|---|
| Broker key/secret | 11 months, or suspicion | Generate at the broker → update SSM → verify with a DRY run → confirm live |
| Daily token | Every run | Automatic |
| TOTP seed | Device change | Re-enrol at the broker, update SSM |
| Telegram bot token | Suspicion | BotFather revoke → SSM → re-register webhook |
| Supabase key | Suspicion | Supabase dashboard → SSM → restart |
| Console password | Suspicion | Set a new argon2id hash |
| TLS | 90 days | Automated |

**Rotation always verifies with a dry run before live.** A rotated credential that does not work is
discovered at 09:30 with the market open otherwise.

---

## 6. Never

The list that matters more than the procedures.

| Never | |
|---|---|
| A secret in git | Including config files, notebooks, and `.env.example` |
| A secret in a Lambda environment variable | Visible in the console and to anyone with `GetFunctionConfiguration` |
| A secret in a log line | §4 |
| A secret in the database | Only paths (§2.1) |
| A secret in a Telegram message | Not even for debugging |
| A secret in a screenshot | Including in a bug report |
| A long-lived AWS access key | IAM roles only |
| TLS verification disabled | Not even against a sandbox |

---

## 7. 🔴 X1 — the outstanding exposure

The archived MetaAlgo repository contained **hardcoded Upstox API credentials in `token_gen.py`**,
committed to git history.

| | |
|---|---|
| Status | 🔴 **Still unrotated** |
| Risk | Public credentials with persistent order capability |
| Required | **Rotate at Upstox.** Git history rewriting is secondary — assume they are already harvested |
| Partial comfort | Static-IP whitelisting means a stolen credential is unusable from an unregistered address — but only where whitelisting is enforced, and only while the attacker's address is not whitelisted |

**This is the one place where ATOM's design cannot compensate for an existing mistake.** Every control
in this document is about secrets ATOM holds; a credential that is already public is outside all of
them. It stays flagged at the top of the readiness blockers until rotated.

---

## 8. Related

[`THREAT-MODEL.md`](THREAT-MODEL.md) · [`../06-web/AUTH-AND-ACCESS.md`](../06-web/AUTH-AND-ACCESS.md) ·
[`../02-infrastructure/AWS-TOPOLOGY.md`](../02-infrastructure/AWS-TOPOLOGY.md) §4 ·
[`../07-logging/LOGGING-SPEC.md`](../07-logging/LOGGING-SPEC.md) §3.1
