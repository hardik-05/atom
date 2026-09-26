# Lambda and Telegram Control Plane

**Status:** 🟢 Specified
**Date:** 2026-09-26

> The instance runs 15–20 minutes a day. Something has to start it, and that something cannot itself
> be an always-on server. A Telegram bot backed by one Lambda is the whole control plane.

---

## 1. Why Telegram rather than a web button

The console lives **on the instance** (D-078). So the one thing it can never do is start the
instance — a chicken-and-egg that any in-console control would hit.

Telegram solves it at zero cost: the operator already has it on their phone, it gives push
notifications for free, it accepts file attachments (which is how detailed run logs are delivered,
D-031), and it needs no hosting.

---

## 2. Commands

| Command | Does | Notes |
|---|---|---|
| `/start` | Starts the instance; replies with the console URL when SSH-less health check passes | Idempotent — already-running is a normal reply, not an error |
| `/stop` | Stops the instance | Refuses while a run is `EXECUTING` unless `/stop force` |
| `/status` | Instance state, uptime, today's run states per universe, idle-shutdown countdown | The most-used command |
| `/logs [date]` | Pushes the run log file for a date | Defaults to today |
| `/runs` | Today's `run` rows: universe, mode, status, counts | Read from Supabase, not the instance |
| `/help` | The above | |

**Deliberately absent: anything that trades.** No `/execute`, no `/buy`, no `/sell`, no `/approve`.
Every trading action requires the console, where the full context — deviations, gates, quantities,
charges — is visible. A one-tap trade from a phone with no context is exactly the affordance this
system should not have, and a compromised phone should not be able to place an order.

`/stop force` is the only destructive command, and it only stops compute.

---

## 3. Authorisation (D-014)

```python
ALLOWED_CHAT_IDS = {...}          # from SSM, not code

if update.effective_user.id not in ALLOWED_CHAT_IDS:
    log_rejected_attempt(update)   # id and command only — never the message body
    return                         # silence: no reply at all
```

**Allow-list by numeric Telegram user ID.** Not username — usernames can be changed and reused;
numeric IDs cannot.

**Unauthorised messages get no reply.** Not "unauthorised", not an error — silence. A bot that
answers tells a prober that the token is live and the bot exists; one that says nothing is
indistinguishable from a dead token.

### 3.1 Webhook hardening

| Control | |
|---|---|
| Telegram secret token | `X-Telegram-Bot-Api-Secret-Token` header, set at webhook registration, verified on every request |
| Bot token storage | SSM `SecureString`, never in Lambda environment variables |
| Function URL auth | `AWS_IAM` is not usable (Telegram cannot sign), so the secret token **is** the authentication — which is why it is mandatory, not optional |
| Rate limit | Reserved concurrency of 2; a flood cannot spin up cost |

> ⚠️ **The bot token is a bearer credential for the whole control plane.** Anyone holding it can
> receive updates addressed to the bot. It is rotated if there is any suspicion, and it never
> appears in a log line, a commit, or a Lambda environment variable.

---

## 4. The Lambda

```
atom-control            Python 3.12 · 128 MB · 30 s timeout · reserved concurrency 2
  └── Function URL (HTTPS)  ← Telegram webhook
```

Small on purpose. It does four things:

1. Verify the secret token and the caller's user ID
2. `ec2:StartInstances` / `StopInstances` / `DescribeInstances`, scoped by tag `atom:managed = true`
3. Read `run` rows from Supabase for `/status` and `/runs`
4. Reply to Telegram

It holds **no trading logic**, no broker credentials, and no ability to place an order. Its IAM role
cannot reach `/atom/sessions/*` in SSM.

### 4.1 Cold start and the reply pattern

Telegram retries a webhook that does not answer within ~60 s, which would double-start the instance.
So the Lambda **replies immediately** and does the slow part after:

```
1  verify → 2  reply "starting, ~90 s" → 3  StartInstances → 4  poll → 5  second message with the URL
```

Two messages, not one held open. `StartInstances` is idempotent, so even a duplicated webhook is
harmless — but not relying on that would be better, hence the fast acknowledgement.

---

## 5. Notifications the engine sends

The engine pushes to the same Telegram group. This is the alerting channel (D-057g).

| Event | Content | Why Telegram |
|---|---|---|
| Run started | universe, mode, account | Confirms the operator's action took effect |
| Run completed | orders placed, fills, skips | The daily summary |
| 🔴 Hard failure | phase, reason, `run_id` | Also to the run log **and** a local log on the instance (D-057g) — three places, because the instance may be about to shut down |
| Egress IP mismatch | observed vs expected | Infrastructure fault; needs a human immediately |
| Token invalid | account, broker | The operator must regenerate before anything can run |
| Negative attribution residual | instrument, shortfall | ATOM believes it holds what it does not |
| Partial harvest failure | sold leg filled, proxy leg did not (D-070b) | **Waits for the operator** — the position is exposed |
| Idle shutdown warning | minutes remaining | D-055a |
| Detailed run log | `.log` / `.txt` **file attachment** | D-031 |
| Weekly universe job | two CSVs — frozen universe and volumes | D-058g |

**Hard failures go to three places** because the failure may be the instance itself. Telegram
survives the instance stopping; a local log survives Telegram being unreachable; the run log survives
both for later forensics.

---

## 6. Cost

| | |
|---|---|
| Lambda invocations | a handful a day — comfortably inside the free tier |
| CloudWatch Logs (Lambda only) | pennies |
| Telegram | free |
| **Added to the bill** | **~$0** |

The control plane is effectively free, which is the argument for it existing at all rather than
keeping a tiny always-on instance to hold a web button.

---

## 7. Failure modes

| Failure | Effect | Handling |
|---|---|---|
| Telegram API down | Cannot start the instance | Fall back to the AWS console or CLI. Documented in the runbook |
| Lambda throttled | `/start` unanswered | Reserved concurrency 2 makes this unlikely; retry |
| Webhook secret mismatch | Requests rejected | Re-register the webhook |
| Instance fails to boot | `/start` reports, no console URL | Runbook: check EIP associations **first** (§3.2 of the static-IP doc) |
| Bot token leaked | 🔴 Anyone can drive the control plane | Revoke via BotFather, rotate in SSM, re-register webhook. **No trading exposure** — §2 |
| Operator's phone compromised | Control plane reachable | Same as above; again no trading exposure, because no command trades |

The last two rows are the reason §2 keeps trading commands out of Telegram. It bounds the blast
radius of the most likely credential loss in the system to "someone can turn a computer on and off".

---

## 8. Open items

| ID | Item |
|---|---|
| Q-140 | Domain auto-switch (D-018) — the Lambda is the natural place to update Route 53 on boot. See [`DEPLOYMENT.md`](DEPLOYMENT.md) §4 |
| — | Confirm whether `/status` should read Supabase directly or wake the instance. **Proposed: Supabase directly**, so `/status` works while the instance is stopped |
