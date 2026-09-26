# Deployment and Environments

**Status:** 🟢 Specified
**Date:** 2026-09-26

---

## 1. Environments

| | `dev` | `prod` |
|---|---|---|
| Supabase | separate project (D-072f) | separate project |
| AWS | same account, tag `atom:env = dev` | tag `atom:env = prod` |
| Elastic IPs | **none** — dev never places a live order | 2, registered with brokers |
| Execution mode | **`DRY` only**, enforced | `DRY` per account until promoted |
| Broker credentials | sandbox where offered (Upstox has one) | real |
| Telegram | separate bot + separate group | production bot |

**`dev` cannot trade by construction, not by convention.** With no Elastic IP it has no
`proxy_url`, and `trading_account_live_needs_proxy_ck` forbids a `LIVE` account without one. The
guarantee is a database constraint rather than a deployment discipline, which is the only kind that
holds under pressure.

---

## 2. What gets deployed where

```
GitHub  ──┬──►  EC2 instance     engine · web API · nginx proxies     (git pull + systemd)
          ├──►  Lambda           atom-control                         (zip upload)
          ├──►  Render           static failover site                 (auto-deploy on push)
          └──►  Supabase         migrations                           (CLI, forward-only)
```

Four targets, three mechanisms. Deliberately boring: no CI/CD pipeline, no container registry, no
blue-green. One operator, one instance, ~20 minutes of runtime a day — a deployment pipeline would
be more machinery than the thing it deploys.

---

## 3. The instance

### 3.1 Layout

```
/opt/atom/                  git checkout
/opt/atom/.venv/            Python virtualenv
/etc/atom/config.toml       non-secret config: proxy ports, log paths, env name
/etc/nginx/conf.d/          one file per investor proxy
/var/log/atom/              local logs, 30-day rolling (D-030)
```

**No secrets on disk.** Broker tokens live in SSM (`/atom/sessions/*`), and the Supabase key comes
from SSM at startup. `/etc/atom/config.toml` would be safe to publish.

### 3.2 systemd units

| Unit | Role |
|---|---|
| `atom-proxy.service` | nginx with the forward-proxy config — **must be healthy before the engine starts** |
| `atom-web.service` | FastAPI + the built frontend, on 443 |
| `atom-engine.service` | oneshot, invoked per run; not a daemon |
| `atom-idle.timer` | Idle shutdown check (D-055a) |

`atom-web` declares `After=atom-proxy.service` and `Requires=` it. If the proxy is not up, nothing
that could reach a broker starts — the fail-closed property from
[`STATIC-IP-AND-PROXY.md`](STATIC-IP-AND-PROXY.md) §6, enforced at boot rather than at call time.

### 3.3 Boot sequence

```
1  systemd starts nginx proxies
2  fetch Supabase credentials from SSM
3  verify_egress_ip.py  ← for every LIVE account
       └─ mismatch → do NOT start atom-web; alert Telegram; leave the instance up for diagnosis
4  start atom-web
5  Lambda health-checks 443, replies with the console URL
```

**Step 3 gates step 4.** An instance that cannot prove its egress addresses does not serve a console
that could be used to trade from them.

---

## 4. Domain and the failover switch (D-018, Q-140)

One domain, `metalcocapital.com`. When the engine is down it must serve the Render static site; when
the engine is up, the same domain must serve the console. **The two sites look identical — the only
visible difference is the login button.**

Three mechanisms were considered (D-069b / D-078 discussion):

| | Mechanism | Cost | Verdict |
|---|---|---|---|
| **(a)** | Lambda updates a Route 53 A record on boot/shutdown | ~$0.50/mo hosted zone | **Chosen** — domain stays stable, no extra IP |
| (b) | Serve the console on a broker-whitelisted Elastic IP | free (already paid) | **Also adopted** — D-078; this is the *address* the A record points to |
| (c) | Accept a changing IP, read it from `/status` | free | Rejected: no TLS certificate can be issued for a bare IP |

So the final design is **(a) + (b) together**: the console is served on **EIP-A**, which is stable,
and Route 53 switches the A record between EIP-A and Render depending on instance state.

Because EIP-A never changes (`AWS-TOPOLOGY.md` §3.2), the A record only needs to flip between two
known values — which is materially simpler and more reliable than chasing an ephemeral public IP.
That reliability concern was the substance of Q-140, and it is now largely resolved by the decision
to keep the console on a permanent address.

| Parameter | Value |
|---|---|
| TTL | **60 s** — low enough to switch quickly, high enough not to hammer resolvers |
| Switch on start | Lambda, after the 443 health check passes — **never before** |
| Switch on stop | Lambda, before `StopInstances` |
| TLS | Certificate covering the domain, on the instance; Render has its own |

> ⚠️ **Never point the record at the instance before the health check passes.** Otherwise the
> operator sees a broken page during boot and cannot tell it from an outage.

**Residual risk:** if the instance is stopped without the Lambda (a crash, or a stop from the AWS
console), the A record still points at a dead address until the next `/stop` or a manual fix. The
mitigation is a scheduled Lambda check — cheap, and worth adding. Recorded as **Q-312**.

---

## 5. Database migrations

Numbered SQL files in `persistence/migrations/`, applied with the Supabase CLI.

| Rule | |
|---|---|
| **Forward-only** | No down migrations. A mistake is corrected by a new migration |
| **Additive first** | Add a column, backfill, switch reads, drop later — never in one step |
| `dev` before `prod`, always | |
| Weekly `pg_dump` to S3 (D-072f) | Before any migration, on top of the schedule |
| Invariants as `CHECK` constraints | Not application validation — the schema is the last line |

The schema carries ~15 CHECK constraints that encode real invariants (capital buckets summing to
principal, a live account requiring a proxy, `chain_depth = 1`, exemption not exceeded). Those are
part of the migration story, not decoration: a bug that would corrupt the ledger is rejected by
Postgres.

---

## 6. Rebuilding the instance

Needed only for an OS upgrade or an instance-type change. **Read this before starting.**

```
0  🔴 CONFIRM both Elastic IP allocation IDs still exist and are NOT released
1  Stop the engine; confirm no run is EXECUTING
2  Snapshot the EBS root volume
3  Launch the replacement with the same instance profile and security group
4  Assign the same secondary private IPs (10.0.1.10, .11)
5  Associate EIP-A and EIP-B to those addresses
6  git pull · build the venv · install nginx config · install systemd units
7  Run verify_egress_ip.py for every account — MUST pass before proceeding
8  Update the Route 53 A record if the console address changed
9  One DRY run per account before restoring LIVE
```

**Step 0 is the whole risk.** As long as the EIPs were never released, the addresses come back and
no broker registration changes. If one was released, that account cannot place orders on Dhan for up
to **7 days** and there is no override (D-173).

---

## 7. Release process

```
1  merge to main
2  dev:  migrations → DRY run → check run_candidate rows and logs
3  prod: pg_dump → migrations → git pull → restart services
4  prod: one DRY run per account
5  restore LIVE mode per account
```

**Every production release passes through a dry run before live mode is restored.** The dry-run
path shares every line of strategy, gate, lot, tax and reporting code with live (D-045), so a dry
run is a real integration test and not a smoke test.

### 7.1 Rollback

`git checkout <previous-tag>` and restart. Migrations are forward-only, so a rollback that needs a
schema change is a **new migration**, not a revert — which is why §5 insists on additive steps.

---

## 8. Cost summary

| | Monthly |
|---|---|
| 2 × Elastic IPv4 (24×7) | $7.30 |
| EBS gp3 8 GB | $0.64 |
| t3a.small, ~12 h | ~$0.23 |
| Route 53 hosted zone | $0.50 |
| S3 + Glacier Deep Archive | < $0.50 |
| Lambda, SSM, CloudWatch | ~$0 |
| **AWS total** | **≈ $9.20** |
| Supabase, Render | free tiers |

**79% of the bill is two IP addresses that bill whether anything runs or not.** Which is the finding
that shaped the whole topology: since IPs bill 24×7 regardless, splitting investors across instances
can never save money, and the cheapest correct design is one small instance with several addresses.

---

## 9. Open items

| ID | Item |
|---|---|
| **Q-312** | Add a scheduled Lambda to correct the Route 53 record if the instance stops without `/stop` (§4) |
| Q-140 | Largely resolved by (a)+(b); remaining work is implementing and testing the switch |
| — | Confirm `ap-south-1` pricing against the `us-east-1` figures in the cost document |
