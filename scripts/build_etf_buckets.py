#!/usr/bin/env python3
"""
Build the ATOM ETF bucket taxonomy from an NSE ETF market-data export.

Produces a three-tier classification used for tax-loss-harvesting proxy matching:

    TIER 1  exact underlying index   -> near-perfect proxy (same index, different ISIN)
    TIER 2  segment / sector group   -> fallback when tier 1 has no peer
    BUCKET  INDEX / SECTOR / FACTOR / COMMODITY / GLOBAL / EXCLUDED

Classification is evaluated SECTOR-FIRST, then FACTOR, then INDEX (D-101): keyword
ordering is the source of the mis-classifications documented in SECTOR-BUCKETS.md §4.

Usage:  python3 scripts/build_etf_buckets.py <nse_export.csv> <output.csv> [reference.csv]

Passing the reference CSV from fetch_etf_reference_data.py lets the classifier use
scheme names to split buckets NSE's SUB-CATEGORY is too coarse to separate — notably
GLOBAL, where NSE labels six ETFs 'GLOBAL INDICES' though they track five different
indices across two markets (D-115).
"""
import csv, re, sys, collections

# D-112: BUCKETING IS PURELY TRACKING-BASED. Liquidity NEVER decides bucket
# membership or peer counts -- it is a config that changes, and a dormant ETF may
# become active. Volume is carried through as INFORMATION only, and the liquidity
# decision is made at execution time with an operator override (D-113).
VOLUME_THRESHOLD = 100_000          # informational flag only, D-027

# --- sector groups (D-096), with Q-201 applied ---------------------------------
SECTOR_GROUPS = [
    ('BANKING',            ['bank']),
    ('FINANCIAL_SERVICES', ['financial services', 'capital market', 'insurance']),
    ('IT',                 ['nifty it', ' it']),
    ('PHARMA_HEALTHCARE',  ['pharma', 'healthcare', 'hospital']),
    ('AUTO',               ['auto', 'ev and new age']),
    ('METALS',             ['nifty metal']),
    ('ENERGY',             ['energy', 'oil & gas', 'power']),
    ('FMCG_CONSUMPTION',   ['fmcg', 'consumption']),
    ('INFRA',              ['infrastructure', 'cement', 'realty', 'railways']),
    ('CHEMICALS',          ['chemical']),
    ('DEFENCE',            ['defence']),
    ('PSU',                ['psu', 'cpse', 'pse', 'bharat 22']),
    ('INTERNET',           ['internet']),
    ('COMMODITIES_EQUITY', ['commodities']),          # Q-201: split out of MANUFACTURING
    ('MANUFACTURING',      ['manufacturing']),
    # Q-201: OTHER_THEMATIC dissolved into single-theme groups
    ('TOURISM',            ['tourism']),
    ('MNC',                ['mnc']),
    ('SERVICES',           ['services sector']),
]

FACTOR_TYPES = [
    ('MOMENTUM_QUALITY', ['momentum quality']),
    ('MOMENTUM',         ['momentum']),
    ('QUALITY',          ['quality', 'flexicap quality']),
    ('VALUE',            ['value', 'enhanced value']),
    ('LOW_VOLATILITY',   ['low volatility', 'low-volatility']),
    ('ALPHA',            ['alpha']),
    ('EQUAL_WEIGHT',     ['equal weight']),
    ('ESG',              ['esg']),
    ('DIVIDEND',         ['dividend']),
    ('SHARIAH',          ['shariah']),
    ('GROWTH',           ['growth sectors']),
]

# Q-202: factor buckets split by market-cap segment too
CAP_SEGMENTS = [
    ('SMALLCAP',    ['smallcap', 'small 250', 'smallcap100']),
    ('MIDSMALLCAP', ['midsmall', 'midsmallcap']),
    ('MIDCAP',      ['midcap']),
    ('LARGEMID',    ['largemid']),
    ('BROAD500',    ['500', 'total market', 'multicap']),
    ('LARGECAP200', ['200']),
    ('LARGECAP100', ['100']),
    ('LARGECAP50',  ['50', 'sensex', 'top 10', 'top 15', 'top 20']),
]

INDEX_SEGMENTS = [
    ('NEXT_50',          ['next 50', 'next 30']),
    ('SMALLCAP',         ['smallcap']),
    ('MIDSMALLCAP',      ['midsmall']),
    ('LARGEMIDCAP',      ['largemid']),
    ('MIDCAP',           ['midcap']),
    ('BROAD_MARKET_500', ['total market', 'multicap', 'nifty 500', 'bse 500']),
    ('NIFTY_200',        ['nifty 200', 'bse 200']),
    ('NIFTY_100',        ['nifty 100', 'bse 100']),
    ('LARGECAP_50',      ['nifty 50', 'sensex', 'top 10', 'top 15', 'top 20']),
    ('MSCI_INDIA',       ['msci india']),
    ('IPO_THEME',        ['select ipo']),
]


SCHEME_NAMES = {}      # symbol -> scheme name, loaded from the reference CSV


def load_scheme_names(path):
    """Optional: reference data from fetch_etf_reference_data.py, used to split
    buckets that NSE's SUB-CATEGORY is too coarse to separate (D-115)."""
    import os
    if not path or not os.path.exists(path):
        return {}
    out = {}
    for r in csv.DictReader(open(path, encoding='utf-8-sig')):
        if r.get('SYMBOL') and r.get('SCHEME_NAME'):
            out[r['SYMBOL'].strip().upper()] = r['SCHEME_NAME']
    return out


def _match(text, keys):
    return any(k in text for k in keys)


GLOBAL_INDEX_PATTERNS = [
    ('NASDAQ 100', ['nasdaq 100']), ('NASDAQ Q50', ['nasdaq q50']),
    ('S&P 500 TOP 50', ['s&p 500 top 50']), ('S&P 500', ['s&p 500']),
    ('NYSE FANG+', ['fang']), ('HANG SENG TECH', ['hang seng tech']),
    ('HANG SENG', ['hang seng']),
]


def normalise_index(sub, symbol=''):
    """Tier 1: the exact underlying index, normalised so naming variants collapse."""
    name = SCHEME_NAMES.get((symbol or '').strip().upper(), '')
    if name:
        n = name.lower()
        for label, keys in GLOBAL_INDEX_PATTERNS:
            if any(k in n for k in keys):
                return label
    s = re.sub(r'\s+', ' ', (sub or '').strip().lower())
    s = s.replace(' etf', '')
    s = re.sub(r'^(nifty|bse)\s+', '', s)
    return s.strip().upper()


def classify(category, sub, symbol=''):
    """Return (bucket, tier2_group, note)."""
    cat = (category or '').strip().upper()
    low = ' ' + re.sub(r'\s+', ' ', (sub or '').strip().lower()) + ' '

    if cat == 'DEBT':
        return 'EXCLUDED', 'DEBT', 'debt/liquid — never traded (D-015)'
    if cat == 'HYBRID':
        return 'EXCLUDED', 'HYBRID', 'hybrid equity/debt — excluded (D-077)'
    if cat == 'COMMODITY':
        return 'COMMODITY', (sub or '').strip().upper(), ''
    if cat == 'GLOBAL INDICES':
        # D-115: NSE labels all global ETFs 'GLOBAL INDICES', but scheme names show
        # they track five different indices across two markets. Grouping them would
        # permit swapping US tech exposure for Hong Kong exposure.
        name = SCHEME_NAMES.get((symbol or '').strip().upper(), '') or low
        n = name.lower()
        if 'hang seng' in n or 'hangseng' in n or 'hkg' in n:
            grp = 'HK_EQUITY'
        elif any(k in n for k in ('nasdaq', 's&p 500', 'sp 500', 'fang', 'nyse')):
            grp = 'US_EQUITY'
        else:
            grp = 'GLOBAL_OTHER'
        return 'GLOBAL', grp, 'structural NAV premium — see NAV-PREMIUM-CHECK.md'

    # EQUITY: sector first (D-101), then factor, then index
    for name, keys in SECTOR_GROUPS:
        if _match(low, keys):
            return 'SECTOR', name, ''

    for name, keys in FACTOR_TYPES:
        if _match(low, keys):
            # D-117 (Q-203): tier 2 is the factor type WITHOUT the cap segment, so a
            # midcap momentum ETF can still proxy a largecap momentum ETF when no
            # same-index peer exists. Cap precision is preserved at tier 1, which is
            # the exact index, and the 0.85 correlation floor guards the tier-2 swap.
            return 'FACTOR', name, 'tier2 ignores cap segment; tier1 keeps exact index'

    for name, keys in INDEX_SEGMENTS:
        if _match(low, keys):
            return 'INDEX', name, ''

    return 'UNCLASSIFIED', 'UNCLASSIFIED', 'NEEDS OPERATOR REVIEW'


def to_number(s):
    s = (s or '').strip().replace(',', '')
    if s in ('-', '', 'NA'):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def main(src, dst, reference=None):
    global SCHEME_NAMES
    SCHEME_NAMES = load_scheme_names(reference)
    if SCHEME_NAMES:
        print(f"loaded {len(SCHEME_NAMES)} scheme names from {reference}")
    rows = list(csv.DictReader(open(src, encoding='utf-8-sig')))
    enriched = []
    for r in rows:
        bucket, group, note = classify(r['CATEGORY'], r['SUB-CATEGORY'], r['SYMBOL'])
        vol = to_number(r['VOLUME']) or 0
        enriched.append({
            'SYMBOL': r['SYMBOL'],
            'NSE_CATEGORY': r['CATEGORY'],
            'NSE_SUB_CATEGORY': r['SUB-CATEGORY'],
            'ATOM_BUCKET': bucket,
            'TIER2_GROUP': group,
            'TIER1_INDEX': normalise_index(r['SUB-CATEGORY'], r['SYMBOL']),
            'VOLUME_INFO_ONLY': int(vol),
            'LIQUID_INFO_ONLY': 'YES' if vol > VOLUME_THRESHOLD else 'NO',
            'ASSIGNMENT_STATUS': 'AUTO',
            'LTP': r['LTP'], 'NAV': r['NAV'], 'I_NAV': r['I-NAV'],
            'NOTE': note,
        })

    # Peer counts are over ALL ETFs in the pool, regardless of liquidity (D-112).
    tradable = [e for e in enriched if e['ATOM_BUCKET'] != 'EXCLUDED']
    t1 = collections.Counter(e['TIER1_INDEX'] for e in tradable)
    t2 = collections.Counter(e['TIER2_GROUP'] for e in tradable)

    for e in enriched:
        if e['ATOM_BUCKET'] == 'EXCLUDED':
            e['PEERS_TIER1'] = e['PEERS_TIER2'] = 0
            e['PROXY_AVAILABLE'] = 'NO'
            continue
        p1 = t1[e['TIER1_INDEX']] - 1
        p2 = t2[e['TIER2_GROUP']] - 1
        e['PEERS_TIER1'] = p1
        e['PEERS_TIER2'] = p2
        e['PROXY_AVAILABLE'] = 'TIER1' if p1 >= 1 else ('TIER2' if p2 >= 1 else 'NO')

    cols = ['SYMBOL', 'NSE_CATEGORY', 'NSE_SUB_CATEGORY', 'ATOM_BUCKET', 'TIER2_GROUP',
            'TIER1_INDEX', 'PEERS_TIER1', 'PEERS_TIER2', 'PROXY_AVAILABLE',
            'ASSIGNMENT_STATUS', 'VOLUME_INFO_ONLY', 'LIQUID_INFO_ONLY',
            'LTP', 'NAV', 'I_NAV', 'NOTE']
    with open(dst, 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for e in sorted(enriched, key=lambda x: (x['ATOM_BUCKET'], x['TIER2_GROUP'],
                                                 -x['VOLUME_INFO_ONLY'])):
            w.writerow({c: e[c] for c in cols})

    print(f"wrote {dst}: {len(enriched)} ETFs")
    unc = [e for e in enriched if e['ATOM_BUCKET'] == 'UNCLASSIFIED']
    print(f"unclassified: {len(unc)}")
    for e in unc:
        print("   ", e['SYMBOL'], '|', e['NSE_SUB_CATEGORY'])
    v = collections.Counter(e['PROXY_AVAILABLE'] for e in enriched
                            if e['ATOM_BUCKET'] != 'EXCLUDED')
    print("proxy availability (liquidity-independent):", dict(v))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2],
         sys.argv[3] if len(sys.argv) > 3 else None)
