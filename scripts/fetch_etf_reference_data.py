#!/usr/bin/env python3
"""
Fetch reference data for every ETF in the ATOM universe, from public sources.

Resolves, per symbol:  full scheme name, AMC, ISIN, benchmark index, exchange.

DESIGN NOTE — why this script no longer depends on NSE
------------------------------------------------------
The first version keyed everything off NSE: ISIN came from the NSE API, and the
AMFI lookup was keyed on that ISIN. So when NSE returned 403 (it aggressively
blocks non-browser clients), every downstream source failed too and the output
was empty.

This version inverts that. The primary sources are broker CDN asset files that
need no authentication, no cookies and no browser emulation:

  1. DHAN scrip master (detailed)  -> ISIN + trading symbol + name
     https://images.dhan.co/api-data/api-scrip-master-detailed.csv
  2. UPSTOX instrument master      -> isin + trading_symbol + name
     https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz
  3. AMFI scheme master            -> official scheme name + AMC, keyed by ISIN
     https://portal.amfiindia.com/spages/NAVAll.txt
  4. NSE archives EQUITY_L.csv     -> symbol + ISIN (static archive file)
     https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv
  5. NSE API                       -> last resort only, needs cookie priming

Sources 1 and 2 alone are usually enough for symbol -> ISIN -> scheme name.
Every source is independent: if one fails the others still contribute, and each
field records which source supplied it.

BENCHMARK INDEX: no public API exposes this directly. It is derived from the
scheme name (e.g. "Nippon India ETF Nifty 50 BeES" -> "Nifty 50") and
cross-checked against the NSE SUB-CATEGORY already held in the bucket CSV,
which is NSE's own statement of what each ETF tracks. Mismatches are flagged
for operator review rather than silently resolved.

LAST-RESORT FALLBACK — local files
----------------------------------
If every scripted fetch is blocked (corporate proxy, NSE bot-detection, an
offline machine), download the files by hand in a browser — a browser is never
blocked the way a script is — and pass them in:

    --dhan-file    api-scrip-master-detailed.csv
    --upstox-file  complete.json.gz  (or the unzipped .json)
    --amfi-file    NAVAll.txt
    --nse-file     EQUITY_L.csv

Any mix of remote and local works; a local file simply skips that download.

Usage:
    python3 scripts/fetch_etf_reference_data.py IN.csv OUT.csv
    python3 scripts/fetch_etf_reference_data.py IN.csv OUT.csv \
        --dhan-file ~/Downloads/api-scrip-master-detailed.csv \
        --amfi-file ~/Downloads/NAVAll.txt
"""
import csv, gzip, io, json, re, sys, datetime
from urllib.request import Request, urlopen
from http.cookiejar import CookieJar

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
TIMEOUT = 120

DHAN_DETAILED = "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"
DHAN_COMPACT  = "https://images.dhan.co/api-data/api-scrip-master.csv"
UPSTOX_ALL    = "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz"
UPSTOX_NSE    = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
AMFI_NAVALL   = "https://portal.amfiindia.com/spages/NAVAll.txt"
NSE_EQUITY_L  = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"

FIELDS = ['SYMBOL', 'ISIN', 'SCHEME_NAME', 'AMC', 'BENCHMARK_DERIVED',
          'NSE_SUB_CATEGORY', 'BENCHMARK_MATCHES_NSE', 'EXCHANGE',
          'ISIN_SOURCE', 'NAME_SOURCE', 'FETCHED_AT']

report = []


LOCAL = {}          # populated from --*-file flags; short-circuits a download


def get(url, binary=False, local_key=None):
    """Read from a local file when one was supplied for this source, else fetch."""
    path = LOCAL.get(local_key)
    if path:
        with open(path, 'rb') as fh:
            data = fh.read()
        return data if binary else data.decode('utf-8', 'ignore')
    req = Request(url, headers={'User-Agent': UA, 'Accept': '*/*'})
    with urlopen(req, timeout=TIMEOUT) as r:
        data = r.read()
    return data if binary else data.decode('utf-8', 'ignore')


def try_source(label, fn):
    try:
        out = fn()
        report.append((label, 'OK', f'{len(out)} records'))
        print(f"  [OK]   {label}: {len(out)} records")
        return out
    except Exception as exc:
        report.append((label, 'FAILED', str(exc)[:120]))
        print(f"  [FAIL] {label}: {exc}", file=sys.stderr)
        return {}


def load_dhan():
    """Detailed master carries ISIN; fall back to compact if it 404s."""
    for url in (DHAN_DETAILED, DHAN_COMPACT):
        try:
            text = get(url, local_key='dhan')
        except Exception:
            continue
        out = {}
        for row in csv.DictReader(io.StringIO(text)):
            cols = {k.strip().upper(): (v or '').strip() for k, v in row.items() if k}
            sym = (cols.get('SEM_TRADING_SYMBOL') or cols.get('UNDERLYING_SYMBOL') or '').upper()
            seg = cols.get('SEM_EXM_EXCH_ID') or cols.get('EXCH_ID') or ''
            if not sym or (seg and seg.upper() != 'NSE'):
                continue
            isin = cols.get('ISIN') or cols.get('SEM_ISIN') or ''
            name = (cols.get('SM_SYMBOL_NAME') or cols.get('SEM_CUSTOM_SYMBOL')
                    or cols.get('SEM_INSTRUMENT_NAME') or '')
            if sym not in out or (isin and not out[sym].get('ISIN')):
                out[sym] = {'ISIN': isin, 'SCHEME_NAME': name, 'EXCHANGE': 'NSE'}
        if out:
            return out
    raise RuntimeError('both Dhan master URLs failed or returned no NSE rows')


def load_upstox():
    for url in (UPSTOX_NSE, UPSTOX_ALL):
        try:
            raw = get(url, binary=True, local_key='upstox')
        except Exception:
            continue
        try:
            text = gzip.decompress(raw).decode('utf-8', 'ignore')
        except OSError:
            text = raw.decode('utf-8', 'ignore')
        data = json.loads(text)
        out = {}
        for item in data:
            if (item.get('segment') or '') != 'NSE_EQ':
                continue
            sym = (item.get('trading_symbol') or '').upper()
            if sym:
                out[sym] = {'ISIN': item.get('isin', ''),
                            'SCHEME_NAME': item.get('name', ''),
                            'EXCHANGE': 'NSE'}
        if out:
            return out
    raise RuntimeError('both Upstox instrument URLs failed')


def load_amfi():
    text = get(AMFI_NAVALL, local_key='amfi')
    out, amc = {}, ''
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if ';' not in line:
            if not line.lower().startswith('scheme code'):
                amc = line
            continue
        parts = line.split(';')
        if len(parts) >= 4 and parts[0].strip().isdigit():
            for isin in (parts[1].strip(), parts[2].strip()):
                if isin and isin != '-':
                    out[isin] = {'SCHEME_NAME': parts[3].strip(), 'AMC': amc}
    return out


def load_nse_archive():
    text = get(NSE_EQUITY_L, local_key='nse')
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        cols = {k.strip().upper(): (v or '').strip() for k, v in row.items() if k}
        sym = cols.get('SYMBOL', '').upper()
        if sym:
            out[sym] = {'ISIN': cols.get('ISIN NUMBER', ''),
                        'SCHEME_NAME': cols.get('NAME OF COMPANY', ''),
                        'EXCHANGE': 'NSE'}
    return out


INDEX_PATTERNS = [
    r'nifty\s+(?:50|100|200|500)\s+\w[\w\s]*?\d+', r'nifty\s+next\s+50', r'nifty\s+midcap\s*\d*',
    r'nifty\s+smallcap\s*\d*', r'nifty\s+bank', r'nifty\s+it', r'nifty\s+pharma',
    r'nifty\s+auto', r'nifty\s+metal', r'nifty\s+fmcg', r'nifty\s+\d+', r'sensex\s*\w*',
    r'bse\s+\d+', r'gold', r'silver', r'nasdaq\s*\d*', r'hang\s*seng', r's&p\s*500',
]


def derive_benchmark(scheme_name):
    if not scheme_name:
        return ''
    s = scheme_name.lower()
    for pat in INDEX_PATTERNS:
        m = re.search(pat, s)
        if m:
            return m.group(0).strip().title()
    return ''


def main(src, dst):
    src_rows = list(csv.DictReader(open(src, encoding='utf-8-sig')))
    symbols = sorted({r['SYMBOL'].strip().upper() for r in src_rows})
    nse_sub = {r['SYMBOL'].strip().upper(): r.get('NSE_SUB_CATEGORY', '') for r in src_rows}
    print(f"{len(symbols)} symbols to resolve\n\nsources:")

    dhan   = try_source('dhan scrip master',   load_dhan)
    upstox = try_source('upstox instruments',  load_upstox)
    nsearc = try_source('nse archive EQUITY_L', load_nse_archive)
    amfi   = try_source('amfi scheme master',  load_amfi)

    if not (dhan or upstox or nsearc):
        print("\nAll symbol->ISIN sources failed. Nothing can be resolved.", file=sys.stderr)

    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
    rows = []
    for sym in symbols:
        rec = {f: '' for f in FIELDS}
        rec['SYMBOL'], rec['FETCHED_AT'] = sym, now
        rec['NSE_SUB_CATEGORY'] = nse_sub.get(sym, '')

        for label, table in (('dhan', dhan), ('upstox', upstox), ('nse-archive', nsearc)):
            hit = table.get(sym)
            if not hit:
                continue
            if hit.get('ISIN') and not rec['ISIN']:
                rec['ISIN'], rec['ISIN_SOURCE'] = hit['ISIN'], label
            if hit.get('SCHEME_NAME') and not rec['SCHEME_NAME']:
                rec['SCHEME_NAME'], rec['NAME_SOURCE'] = hit['SCHEME_NAME'], label
            rec['EXCHANGE'] = rec['EXCHANGE'] or hit.get('EXCHANGE', '')

        if rec['ISIN'] and rec['ISIN'] in amfi:
            a = amfi[rec['ISIN']]
            rec['AMC'] = a.get('AMC', '')
            if a.get('SCHEME_NAME'):
                rec['SCHEME_NAME'], rec['NAME_SOURCE'] = a['SCHEME_NAME'], 'amfi'

        rec['BENCHMARK_DERIVED'] = derive_benchmark(rec['SCHEME_NAME'])
        if rec['BENCHMARK_DERIVED'] and rec['NSE_SUB_CATEGORY']:
            a = re.sub(r'[^a-z0-9]', '', rec['BENCHMARK_DERIVED'].lower())
            b = re.sub(r'[^a-z0-9]', '', rec['NSE_SUB_CATEGORY'].lower())
            rec['BENCHMARK_MATCHES_NSE'] = 'YES' if (a in b or b in a) else 'REVIEW'
        rows.append(rec)

    with open(dst, 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    n = len(rows)
    print(f"\nwrote {dst}")
    print(f"  ISIN resolved        : {sum(1 for r in rows if r['ISIN'])}/{n}")
    print(f"  scheme name resolved : {sum(1 for r in rows if r['SCHEME_NAME'])}/{n}")
    print(f"  AMC resolved         : {sum(1 for r in rows if r['AMC'])}/{n}")
    print(f"  benchmark derived    : {sum(1 for r in rows if r['BENCHMARK_DERIVED'])}/{n}")
    print(f"  benchmark NEEDS REVIEW vs NSE : "
          f"{sum(1 for r in rows if r['BENCHMARK_MATCHES_NSE'] == 'REVIEW')}")
    print("\nsource status:")
    for label, status, detail in report:
        print(f"  {status:<7} {label:<22} {detail}")


def parse_args(argv):
    positional, i = [], 0
    while i < len(argv):
        a = argv[i]
        if a.startswith('--') and a.endswith('-file'):
            key = a[2:-5]
            if i + 1 >= len(argv):
                sys.exit(f'{a} needs a path')
            LOCAL[key] = argv[i + 1]
            i += 2
        else:
            positional.append(a)
            i += 1
    if len(positional) != 2:
        sys.exit(__doc__)
    return positional


if __name__ == '__main__':
    src, dst = parse_args(sys.argv[1:])
    if LOCAL:
        print('using local files: ' + ', '.join(f'{k}={v}' for k, v in LOCAL.items()))
    main(src, dst)
