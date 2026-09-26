# Log Archival and Retention

**Status:** 🟢 Specified
**Date:** 2026-09-26
**Basis:** D-030 (retention tiers) · D-031 (Telegram delivery) · D-072e (Google Drive via service
account, gzip above 10 MB)

---

## 1. Retention matrix

| Destination | Tier 1 (rows) | Tier 2 (files) | Retention | Purpose |
|---|---|---|---|---|
| **Supabase** `run_log` | ✅ | ❌ | **90-day purge** | The console's Logs screen |
| **Instance local** `/var/log/atom/` | ❌ | ✅ | **30-day rolling** | Debugging while the instance is up; survives Telegram being down |
| **S3 standard** `atom-logs/` | ❌ | ✅ | **30-day rolling** | Recent forensics without starting the instance |
| **S3 Glacier Deep Archive** | ❌ | ✅ | **Permanent** | The compliance-grade record |
| **Google Drive** | ❌ | ✅ | **Permanent** | Human-reachable archive, no AWS login needed |
| **Telegram group** | ❌ | ✅ | **Permanent** (Telegram's own) | Delivered where the operator already is |

**Four permanent copies of the detailed record, across three providers.** That is not redundancy for
its own sake: a trading system's logs are the only evidence of why it did what it did, and the
question may be asked years later by someone with no AWS access — or by a tax authority.

### 1.1 Why the structured tier is purged at 90 days but the files are not

`run_log` is a narrative convenience. The **durable** record is:

- `run_candidate` — every decision and its inputs, **never purged**
- `order_request` / `order_fill` / `position_lot` / `lot_closure` — **never purged**
- `charge`, `capital_accrual_*`, `tax_*` — **never purged**
- `action_audit` — every operator override, **never purged**

So a 90-day purge of `run_log` loses prose, not facts. The distinction is §1.1 of
[`LOGGING-SPEC.md`](LOGGING-SPEC.md) applied to retention: because the decision record was never in
a log, a log can be allowed to expire.

---

## 2. Shipping

```
run completes
   │
   ├─► write /var/log/atom/atom-{date}-{acct}-{univ}-{run}.log
   ├─► gzip if > 10 MB                                   (D-072e)
   ├─► PUT s3://atom-logs/YYYY/MM/DD/...                 (standard)
   ├─► PUT s3://atom-logs-archive/YYYY/MM/DD/...          (Deep Archive)
   ├─► upload to Google Drive shared folder               (service account)
   └─► push to Telegram as a file attachment              (D-031)
```

**Shipping happens before the instance stops**, and a shipping failure is logged but does **not**
fail the run — the trading outcome is already committed, and a run marked `FAILED` because an upload
timed out would be a lie about what happened. Unshipped files are retried on the next run's startup,
which is why the local 30-day cache exists.

### 2.1 Google Drive

A **service account** writing to a folder shared with it (D-072e) — not OAuth as the operator, which
would need an interactive refresh and would break unattended.

| | |
|---|---|
| Layout | `ATOM/logs/YYYY/MM/` |
| Credentials | SSM `/atom/drive/*` |
| Gzip | above 10 MB |
| Failure | logged, retried next run, never fatal |

### 2.2 S3 lifecycle

Two buckets rather than one with transitions, because the retention intents are genuinely different:

```
atom-logs            → expire after 30 days
atom-logs-archive    → Glacier Deep Archive on day 0, no expiry
```

| | |
|---|---|
| Encryption | SSE-KMS, customer-managed key |
| Versioning | On, on the archive bucket |
| Public access | Blocked at the bucket and account level |
| Object Lock | **Governance mode on the archive bucket** — see §3 |
| Engine IAM | `PutObject` only; `DeleteObject` **denied** (`AWS-TOPOLOGY.md` §4.1) |

Deep Archive retrieval takes up to 12 hours and costs a few cents. That is the correct trade for a
record that may be read once in five years, and the S3-standard copy covers anything recent.

---

## 3. Tamper resistance

| Control | Effect |
|---|---|
| Engine cannot delete | `s3:DeleteObject` denied to the instance role |
| Object Lock, governance mode | Deletion requires a separate privileged action, not the engine's credentials |
| Versioning on the archive | An overwrite does not destroy the prior object |
| Four copies, three providers | No single compromise or account closure destroys the record |

**A compromised engine can write misleading new logs. It cannot remove old ones.** That is the
property worth having — appending a lie is detectable by comparing copies; a silent deletion is not.

---

## 4. Database backups

Separate from logs, and included here because the durable record lives mostly in the database.

| | |
|---|---|
| Weekly `pg_dump` → S3 (D-072f) | Plus before every migration |
| Supabase point-in-time recovery | Per its plan |
| Retention | 12 weekly dumps, then monthly |
| Encryption | SSE-KMS |
| **Restore test** | **Quarterly, into the dev project** — see below |

> An untested backup is a belief, not a backup. The quarterly restore into `dev` is the only thing
> that converts it. It is in the runbook as a scheduled task, not left to intention.

---

## 5. Generated artefacts

Not logs, but archived the same way (D-058g, D-072e):

| Artefact | Destination |
|---|---|
| Weekly universe CSV + volume CSV | Telegram, S3, Drive |
| Period reports | S3, Drive, on demand |
| Tax computation exports | S3, Drive — **permanent** |
| Instrument master snapshots | S3, 90 days |

The instrument master snapshot matters more than it looks: it is what makes a past decision
reproducible after a symbol has been renamed or a broker token reused.

---

## 6. Access

| Who | How |
|---|---|
| Operator, recent | Console → Logs screen (`run_log`, 90 days) |
| Operator, files | Telegram scrollback, or Google Drive |
| Operator, older | S3 standard (30 days) or Drive |
| Forensics, years later | Google Drive, or restore from Deep Archive |
| Anyone else | No access |

Drive is listed before S3 for the operator's own use deliberately — it needs no AWS login, works from
a phone, and is searchable. The AWS copies exist for durability and tamper resistance, not
convenience.

---

## 7. Costs

| | Monthly |
|---|---|
| S3 standard, ~30 files × ~2 MB rolling | < $0.01 |
| Deep Archive, growing ~25 MB/month | < $0.01 for years |
| KMS key | $1.00 |
| Google Drive | Free tier |
| **Total** | **≈ $1.00**, almost all of it the KMS key |

The KMS key costs more than the storage it protects. That is fine — a customer-managed key is what
makes the deny-delete and Object Lock story coherent, and $1/month is not the constraint here.

---

## 8. Open items

| ID | Item |
|---|---|
| — | Confirm Telegram's file retention for a private group; treat it as convenience rather than guaranteed archive |
| — | Set a Drive quota alert; the free tier is shared with everything else in that Google account |
| — | Schedule the first quarterly restore test as part of go-live (§4) |
