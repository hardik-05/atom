# Releases and first deploy

**Status:** 🟢 in use · **Code:** [`scripts/deploy.py`](../../scripts/deploy.py) ·
[`deploy/install.sh`](../../deploy/install.sh) · [`deploy/atom.service`](../../deploy/atom.service) ·
[`deploy/Caddyfile.tmpl`](../../deploy/Caddyfile.tmpl)

---

## 1. What runs on the instance

```
internet ──443/80──► Caddy (TLS, Let's Encrypt) ──► 127.0.0.1:8000 uvicorn (atom.web.main)
                                                        │
                                   ┌────────────────────┼─────────────────────┐
                                   ▼                    ▼                     ▼
                         squid 127.0.0.1:3128    Supabase pooler :5432   SSM /atom/*
                         → egress 13.127.7.83    (direct TCP)            (instance role)
                         → Upstox, AMFI, checkip
```

| Unit | Runs as | Why |
|---|---|---|
| `caddy` | `caddy` | Terminates TLS; the engine never listens on a public address |
| `atom` | `atom` | Unprivileged, `ProtectSystem=strict`; writes only `/var/log/atom` and `/run/atom` |
| `squid` | `squid` | Per-investor egress binding (STATIC-IP-AND-PROXY.md) |
| `atom-idle.timer` | root | Stops the instance after an hour with no console activity |

**One uvicorn worker.** Background jobs (history sync, instrument sync) run in-process; two
workers would each keep a job list the other cannot see.

---

## 2. A release

```
python scripts/deploy.py
```

1. Refuses a dirty tree — a release names a commit.
2. Builds `web/dist`.
3. Packages tracked files + `web/dist` (not `data/raw`, not `infra/`).
4. Uploads to `s3://atom-artifacts-905221883695-prod/releases/<stamp>-<sha>.tar.gz`.
5. Starts the instance if the idle timer stopped it.
6. Runs `deploy/install.sh` through SSM: new release directory, fresh virtualenv, symlink swap,
   restart, health check. **An unhealthy release is rolled back** to the previous symlink before
   the script exits non-zero. The three newest releases are kept.

The instance needs no git credentials and no Node toolchain: what runs is exactly the tarball.

---

## 3. First deploy — one-time steps

In order. Steps marked 👤 are the operator's, because they involve a credential or an account
ATOM must not hold.

| # | Step | Who |
|---|---|---|
| 1 | Cloudflare DNS: `A  app  13.127.7.83`, **DNS only (grey cloud)** | 👤 |
| 2 | `terraform apply` — artifacts bucket, port 80, KMS encrypt for session tokens | engine |
| 3 | Supabase: apply migration `0017_config_gaps` | engine |
| 4 | `python -m atom.cli db-login --host <pooler host> --pooler` → run the printed SQL | 👤 + engine |
| 5 | `python -m atom.cli console-setup` → add the key to an authenticator app | 👤 |
| 6 | `python scripts/deploy.py` | engine |
| 7 | Sign in at `https://app.metaalgocapital.com`, create Nidhi + her Upstox account | 👤 |
| 8 | Upstox developer console: new app, redirect URI below, static IP `13.127.7.83` | 👤 |
| 9 | `python -m atom.cli broker-secret --account-id <id> --broker UPSTOX` | 👤 |
| 10 | Universe & data → Import reference → Sync Upstox master | 👤 |
| 11 | Broker tokens → Generate → sign in at Upstox → paste code → test calls run | 👤 |

**Redirect URI**, exactly: `https://app.metaalgocapital.com/brokers/upstox/callback`

### Why DNS-only (grey cloud)

With Cloudflare's proxy on, the browser talks to Cloudflare and Cloudflare to the instance.
Caddy's certificate is then never presented to the browser, and ACME validation passes through a
third party. DNS-only keeps TLS end to end between the browser and the instance, which is what
the threat model assumes.

### Why the database login goes through a verifier

`db-login` generates a random password, stores the full DSN in `/atom/db/dsn`, and prints SQL
containing only a **SCRAM-SHA-256 verifier**. The verifier can be run through any channel —
including one that keeps a transcript — without exposing the password it sets.

### Why port 80 is world-open

Let's Encrypt validates from undisclosed addresses. A narrowed port 80 does not fail at issuance;
it fails 60 days later at *renewal*, quietly, and the first symptom is an expired certificate. The
rule is pinned to `0.0.0.0/0` separately from `allow_console_from` so tightening the console never
arms that trap. Port 80 serves only a redirect and the challenge.

---

## 4. Known gaps, stated

| Gap | Consequence | Unblocked by |
|---|---|---|
| Lot `unit_cost` = fill price | Charges not yet in the cost basis (D-076a) | Q-313 (STT on ETFs) + a rates table |
| Market holidays not checked | A LIVE plan on an exchange holiday is refused by the broker, not by pre-flight | Upstox holidays API in pre-flight |
| Upstox EDIS not automated | A LIVE sell pass is skipped when the account has neither POA nor DDPI | `initiate_sell_authorisation` for Upstox |
| Only the Upstox adapter is wired | Other brokers' accounts can be created but not connected | The Dhan adapter, next in MODULE-MAP order |
