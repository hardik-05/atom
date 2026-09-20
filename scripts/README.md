# Scripts

## `build_etf_buckets.py`

Builds the ATOM ETF bucket taxonomy from an NSE ETF market-data export.

```bash
python3 scripts/build_etf_buckets.py \
    docs/99-vendor-docs/nse/MW-ETF-17-Sep-2026.csv \
    docs/99-vendor-docs/nse/etf-buckets-2026-09-17.csv
```

**Input:** the CSV exported from the download control on
<https://www.nseindia.com/market-data/exchange-traded-funds-etf>.

Bucketing is purely tracking-based — liquidity never affects it (D-112).

---

## `fetch_etf_reference_data.py`

Resolves scheme name, AMC, ISIN and benchmark index for every ETF, from four
independent public sources.

```bash
python3 scripts/fetch_etf_reference_data.py \
    docs/99-vendor-docs/nse/etf-tradable-buckets-2026-09-17.csv \
    docs/99-vendor-docs/nse/etf-reference-data.csv
```

### Where the files come from

All four are public and need **no login, no API key and no account**. Paste any
URL into a browser address bar and it downloads.

| # | What | URL | Size | Flag |
|---|---|---|---|---|
| **1** | **Dhan scrip master (detailed)** — has ISIN | `https://images.dhan.co/api-data/api-scrip-master-detailed.csv` | ~40–80 MB | `--dhan-file` |
| 1b | Dhan scrip master (compact) — smaller, no ISIN | `https://images.dhan.co/api-data/api-scrip-master.csv` | ~10 MB | `--dhan-file` |
| **2** | **Upstox instruments, NSE only** — has ISIN | `https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz` | ~2 MB | `--upstox-file` |
| 2b | Upstox instruments, all exchanges | `https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz` | ~10 MB | `--upstox-file` |
| **3** | **AMFI scheme master** — official scheme name + AMC | `https://portal.amfiindia.com/spages/NAVAll.txt` | ~8 MB | `--amfi-file` |
| 4 | NSE equity list — symbol → ISIN | `https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv` | ~1 MB | `--nse-file` |

**The minimum useful set is #2 and #3.** Upstox NSE-only is the smallest file
that carries ISIN, and AMFI turns that ISIN into an official scheme name and
AMC. #1 is an equally good substitute for #2. #4 is a backstop.

### If the script cannot download them

Download by hand in a browser — a browser is never blocked the way a script is —
and pass the paths in. Any mix of local and remote works:

```bash
python3 scripts/fetch_etf_reference_data.py IN.csv OUT.csv \
    --upstox-file ~/Downloads/NSE.json.gz \
    --amfi-file   ~/Downloads/NAVAll.txt
```

Gzip files can be passed still compressed; the script handles both.

### Known access quirks

- **`nseindia.com` fingerprints non-browser clients** and returns `403` to
  `urllib`. Sources 1–3 are on CDN/asset hosts and have no such protection. If
  you ever need NSE specifically, `requests` with a `Session` — or `curl_cffi`,
  which impersonates a browser TLS fingerprint — gets through where `urllib`
  does not.
- The script reports every source's status separately, so a partial failure is
  visible rather than silent.

### Output

`SYMBOL, ISIN, SCHEME_NAME, AMC, BENCHMARK_DERIVED, NSE_SUB_CATEGORY,
BENCHMARK_MATCHES_NSE, EXCHANGE, ISIN_SOURCE, NAME_SOURCE, FETCHED_AT`

`BENCHMARK_MATCHES_NSE` is `YES` where the benchmark parsed from the scheme name
agrees with NSE's own sub-category, and **`REVIEW`** where they disagree — that
column is the input to the second round of bucket analysis.
