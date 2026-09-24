# Prior Art — Analysis of the Existing MetaAlgo System

**Date:** 2026-09-24
**Sources reviewed:** `metaalgo_backup` (etf_mean_reversion_bot, …_v1) · `metaalgo-cloudflare` ·
`metaalgo-vercel-app`
**Status of that system:** ⚠️ **Archived and shut down — last running about six months ago.**
Not live, not a reference implementation, and parts of its infrastructure have likely been
cleaned up. It was shut down precisely because it fell short on reporting, trading and much else.

**How to use it:** for **understanding only**. ATOM is built from scratch. Nothing here is to be
copied or mimicked — the value is in the problems it already hit and solved, not in its code.

> Local paths `D:\MetaAlgo\metaalgo_capital` and `…_resources` were not reachable — this session
> runs in a cloud container with no access to a local drive. The four GitHub repositories were
> read instead. If `metaalgo_capital` holds material not in `metaalgo_backup`, push it and it can
> be reviewed.

---

## 1. 🔴 Security finding — act on this first

**`Token_gen/token_gen.py` contains hardcoded, committed credentials**: Upstox `client_id`,
`api_key` and `api_secret` in plaintext, in git history, in a repository that survives every
clone. The generated access token is then written to a plain `.txt` file on disk.

The repository is private, which limits but does not remove the exposure: anyone with repo
access, any future collaborator, and any machine that has ever cloned it holds live API
credentials for a trading account.

**Recommended, in order:**
1. **Rotate the Upstox API key and secret now**, before anything else.
2. Treat the git history as compromised for those values — rotation is the fix, not deletion,
   since history rewriting cannot recall clones already taken.
3. In ATOM, credentials live in **SSM Parameter Store** (D-079) and are fetched via the instance
   role. No credential is ever written to a file or committed.

*This is exactly the failure mode D-079 was chosen to prevent, and it is worth stating plainly
rather than leaving implied.*

---

## 2. 🟢 Q-140 answered — the domain switch is already solved, in production

`metaalgo-cloudflare` is a deployed Cloudflare Worker (`metaalgo-failover-router`) doing exactly
what D-018 describes:

```javascript
// Try EC2 origin first, 3-second timeout
const controller = new AbortController();
setTimeout(() => controller.abort(), 3000);
const response = await fetch(ec2Request, { signal: controller.signal });
if (response.status >= 500) throw new Error("EC2 Server Error");
return response;

// On timeout / error / 5xx → fall back to the static site
return fetch(new Request(`${VERCEL_URL}${url.pathname}${url.search}`, {...}));
```

Details worth keeping:
- Origin is a **grey-cloud subdomain** (`origin-direct.metaalgocapital.com`) — deliberately, to
  avoid Cloudflare Error 1003, which blocks Workers fetching orange-cloud IPs.
- An `X-Custom-Auth-Key` header is set on the origin request and **matched by an Nginx map on
  EC2**, so the origin cannot be reached except through the Worker.
- `Host` is rewritten to the apex domain.
- Domain: **metaalgocapital.com**.

**This is better than all three options proposed in D-055h** (DNS switching, reverse proxy,
Render redirect):

| | Proposed options | This Worker |
|---|---|---|
| Switch latency | DNS TTL — minutes to hours | **Per-request, instant** |
| Trigger | Manual or polled | **Automatic on timeout/5xx** |
| Origin protection | Not addressed | **Auth-key + Nginx map** |
| State to manage | DNS records | **None** |

**D-055h — build and measure three options — is withdrawn.** The answer exists and is running.

*Consequence: the static site is on **Vercel**, not Render as D-018 assumed. And **Nginx is
already on the EC2 box**, which matters for §5.*

---

## 3. 🟢 NSE access — solved with browser automation

`nse_scrapper/nse_scrapper.py` downloads the NSE ETF CSV using **Selenium + Chrome +
webdriver-manager**, driving the real download control.

This is the working answer to the problem that blocked `fetch_etf_reference_data.py`: NSE
fingerprints scripted clients and returns 403, but it cannot distinguish a real browser. The
existing system simply uses one.

**Directly reusable** for the weekly universe job (D-058g), and it means the NSE export need not
be a manual download. Chromium and Playwright are already available in the target environment.

*Preference stands for the broker CDN instrument masters where they suffice (D-114) — they are
lighter than driving a browser — but for the NSE ETF table specifically, this is the way.*

---

## 4. ⚠️ The existing strategy ranks on RUPEE difference — ATOM changes this

`Market_buy/market_buy_updated.py`:

```python
metal_etf_df["price_difference"]  = metal_etf_df["symbols"].apply(
    lambda x: metal_etf_current_price_dict[x] - metal_etf_dma_dict[x])
equity_etf_df.sort_values("price_difference", inplace=True)
top_5_equity_etf_df = equity_etf_df.iloc[:5]
```

The live system ranks by **absolute rupee difference** (`current − mean`), ascending.

**ATOM ranks by percentage (D-026).** This was raised as Q-051 and decided deliberately, for the
reason that a ₹5,000 ETF and a ₹100 ETF at the same percentage discount produce wildly different
rupee gaps, so rupee ranking systematically favours expensive ETFs.

> ⚠️ **ATOM will therefore not reproduce the existing bot's picks.** That is intended, but it
> should be expected rather than discovered: the first parallel run will show different
> candidates, and that is the change working, not a bug. Worth validating on history before
> going live — and a good first use of the deferred backtest harness (V2-1).

Other confirmed parameters: `amount = 10000` per trade, top-5 shortlist per category, three
categories with manual ticker lists per category (`equity_etf_sheet.csv`, `metal_etf_sheet.csv`,
`global_etf_sheet.csv`).

---

## 5. What is directly reusable

| Component | Reuse |
|---|---|
| **Cloudflare failover Worker** | ✅ As-is. Answers D-018 completely |
| **Nginx on EC2 with auth-key map** | ✅ Already proven — and Nginx is a candidate for the per-account forward proxy (D-005), since it is on the box and configured |
| **Selenium NSE downloader** | ✅ For the weekly universe job |
| **Upstox OAuth flow** | ✅ Endpoints and payload shape confirmed against a working implementation |
| **Telegram messaging** | ✅ `send_telegram_message(bot_token, chat_id, message)` already working |
| **Upstox endpoints** | ✅ `historical-candle/{key}/day/{to}/{from}`, `historical-candle/intraday/{key}/1minute`, `portfolio/long-term-holdings`, order book, trades, **trade charges** |
| **Cancel-resting-sells logic** | ✅ Already filters `order_type == LIMIT and transaction_type == SELL` — the same shape as D-063's cancel-first step |
| **Vercel static site** | ✅ Brand and palette — dark navy `#0a0f1c`, cyan `#06b6d4`, Inter, Tailwind |

## 6. What ATOM deliberately does differently

| | Existing | ATOM |
|---|---|---|
| Ranking | Rupee difference | **Percentage** (D-026) |
| Categorisation | Manual CSV ticker lists | **NSE category + LLM + operator review** (D-032) |
| Credentials | Hardcoded in source | **SSM Parameter Store** (D-079) |
| Orchestration | Script executor with hardcoded absolute paths | **Modular engine, config-driven** |
| Persistence | CSV files on disk | **Supabase, lot-level** (D-045) |
| Brokers | Upstox only | **Five, behind an adapter contract** |
| Per-account egress | Not addressed | **Static IP per investor** (D-005) |
| Sell orders | Limit sells, cancel/replace | **GTT where supported, DAY fallback** (D-142) |
| Cost of capital, tax, harvesting | Not present | **Full subsystems** |

*The archived system was an early prototype that was retired for falling short on reporting, trading and more. ATOM is a fresh build, not its successor in code — the value taken forward is the problems it surfaced, not its implementation.*

---

## 7. Decisions changed by this review

| ID | Change |
|---|---|
| **D-055h** | **Withdrawn** — no need to build and measure three domain-switch options; the Cloudflare Worker is the answer |
| **D-018** | Static site is on **Vercel**, not Render |
| **D-144** | Nginx is already deployed on EC2 — evaluate it for the per-account forward proxy before introducing squid |
| **D-145** | Use the Selenium approach for NSE downloads in the weekly job |

## 8. Open items

| ID | Item |
|---|---|
| Q-242 | 🔴 Rotate the exposed Upstox API key and secret |
| Q-243 | Is `metaalgo_capital` (local only) materially different from `metaalgo_backup`? If so, push it for review |
| Q-244 | Should the existing Cloudflare Worker be reused as-is, or re-deployed under ATOM's own account? |
| Q-245 | Keep the existing `metaalgocapital.com` domain and brand for ATOM? |
