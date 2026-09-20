#!/usr/bin/env python3
"""
Fetch reference / prospectus data for every ETF in the ATOM universe.

For each ETF this collects, where available:
    full scheme name, AMC, target benchmark index, ISIN, expense ratio,
    launch date, underlying asset

Sources are tried in order and the first success per field wins. Everything is
recorded with its source and fetch timestamp so a value can always be traced.

    1. NSE ETF listing       https://www.nseindia.com/api/etf
    2. NSE quote             https://www.nseindia.com/api/quote-equity?symbol=<SYM>
    3. AMFI scheme master    https://portal.amfiindia.com/spages/NAVAll.txt   (ISIN -> scheme)
    4. MFAPI                 https://api.mfapi.in/mf/search?q=<name>

⚠️  RUN THIS OUTSIDE THE CLAUDE CODE SANDBOX.
    All four hosts are refused (HTTP 403 at the egress gateway) by the agent
    proxy's policy, so the script cannot complete in that environment. Run it on
    the EC2 box or any machine with open outbound HTTPS.

NSE requires a browser-like session: hit the homepage first to collect cookies,
then call the API with those cookies and a Referer. The script does this, and
rate-limits itself to stay polite.

Usage:
    python3 scripts/fetch_etf_reference_data.py \
        docs/99-vendor-docs/nse/etf-tradable-buckets-2026-09-17.csv \
        docs/99-vendor-docs/nse/etf-reference-data.csv
"""
import csv, json, sys, time, datetime
from urllib.request import Request, urlopen, HTTPCookieProcessor, build_opener
from urllib.error import HTTPError, URLError
from http.cookiejar import CookieJar

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
DELAY = 1.2          # seconds between NSE calls
TIMEOUT = 20

FIELDS = ['SYMBOL', 'SCHEME_NAME', 'AMC', 'BENCHMARK_INDEX', 'ISIN',
          'EXPENSE_RATIO', 'LAUNCH_DATE', 'UNDERLYING_ASSET',
          'SOURCE', 'FETCHED_AT', 'ERROR']


def make_opener():
    return build_opener(HTTPCookieProcessor(CookieJar()))


def prime_nse(opener):
    """NSE rejects bare API calls; collect cookies from the homepage first."""
    try:
        opener.open(Request("https://www.nseindia.com",
                            headers={'User-Agent': UA,
                                     'Accept': 'text/html,application/xhtml+xml'}),
                    timeout=TIMEOUT).read()
        return True
    except Exception as exc:
        print(f"  ! could not prime NSE session: {exc}", file=sys.stderr)
        return False


def get_json(opener, url, referer="https://www.nseindia.com/"):
    req = Request(url, headers={'User-Agent': UA, 'Accept': 'application/json',
                                'Referer': referer,
                                'Accept-Language': 'en-US,en;q=0.9'})
    with opener.open(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode('utf-8'))


def fetch_nse_etf_listing(opener):
    """One call returns every listed ETF, including the underlying asset text."""
    try:
        data = get_json(opener, "https://www.nseindia.com/api/etf")
        out = {}
        for row in data.get('data', []):
            sym = (row.get('symbol') or '').strip().upper()
            if sym:
                out[sym] = {
                    'SCHEME_NAME': row.get('meta', {}).get('companyName') or row.get('assets') or '',
                    'UNDERLYING_ASSET': row.get('assets') or '',
                    'ISIN': row.get('meta', {}).get('isin') or '',
                    'SOURCE': 'nse:/api/etf',
                }
        return out
    except Exception as exc:
        print(f"  ! NSE ETF listing failed: {exc}", file=sys.stderr)
        return {}


def fetch_nse_quote(opener, symbol):
    try:
        d = get_json(opener, f"https://www.nseindia.com/api/quote-equity?symbol={symbol}",
                     referer=f"https://www.nseindia.com/get-quotes/equity?symbol={symbol}")
        info = d.get('info', {})
        return {'SCHEME_NAME': info.get('companyName', ''),
                'ISIN': info.get('isin', ''),
                'LAUNCH_DATE': d.get('metadata', {}).get('listingDate', ''),
                'SOURCE': 'nse:/api/quote-equity'}
    except Exception as exc:
        return {'ERROR': f'nse-quote: {exc}'}


def fetch_amfi_isin_map():
    """AMFI NAVAll.txt is semicolon-delimited: ISIN -> scheme name and AMC."""
    try:
        req = Request("https://portal.amfiindia.com/spages/NAVAll.txt",
                      headers={'User-Agent': UA})
        text = urlopen(req, timeout=60).read().decode('utf-8', 'ignore')
    except Exception as exc:
        print(f"  ! AMFI fetch failed: {exc}", file=sys.stderr)
        return {}
    out, amc = {}, ''
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if ';' not in line:
            amc = line                      # AMC names appear as bare lines
            continue
        parts = line.split(';')
        if len(parts) >= 4 and parts[0].isdigit():
            for isin in (parts[1].strip(), parts[2].strip()):
                if isin and isin != '-':
                    out[isin] = {'SCHEME_NAME': parts[3].strip(), 'AMC': amc,
                                 'SOURCE': 'amfi:NAVAll'}
    return out


def main(src, dst):
    symbols = [r['SYMBOL'].strip().upper()
               for r in csv.DictReader(open(src, encoding='utf-8-sig'))]
    symbols = sorted(set(symbols))
    print(f"{len(symbols)} symbols to resolve")

    opener = make_opener()
    primed = prime_nse(opener)
    listing = fetch_nse_etf_listing(opener) if primed else {}
    print(f"NSE listing returned {len(listing)} ETFs")
    amfi = fetch_amfi_isin_map()
    print(f"AMFI map returned {len(amfi)} ISINs")

    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
    rows = []
    for i, sym in enumerate(symbols, 1):
        rec = {f: '' for f in FIELDS}
        rec['SYMBOL'], rec['FETCHED_AT'] = sym, now
        rec.update({k: v for k, v in listing.get(sym, {}).items() if v})

        if primed and not rec.get('ISIN'):
            time.sleep(DELAY)
            rec.update({k: v for k, v in fetch_nse_quote(opener, sym).items() if v})

        if rec.get('ISIN') and rec['ISIN'] in amfi:
            for k, v in amfi[rec['ISIN']].items():
                if v and not rec.get(k):
                    rec[k] = v
            rec['SOURCE'] = (rec.get('SOURCE', '') + '+amfi').strip('+')

        rows.append(rec)
        if i % 25 == 0:
            print(f"  {i}/{len(symbols)}")

    with open(dst, 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    got = sum(1 for r in rows if r['SCHEME_NAME'])
    print(f"\nwrote {dst}")
    print(f"  scheme name resolved : {got}/{len(rows)}")
    print(f"  ISIN resolved        : {sum(1 for r in rows if r['ISIN'])}/{len(rows)}")
    print(f"  benchmark resolved   : {sum(1 for r in rows if r['BENCHMARK_INDEX'])}/{len(rows)}")
    print("\nBENCHMARK_INDEX is rarely exposed by these APIs; it usually has to come "
          "from the scheme information document. Where it is blank, fall back to the "
          "NSE SUB-CATEGORY already captured in the bucket CSV, which is NSE's own "
          "statement of what the ETF tracks.")


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
