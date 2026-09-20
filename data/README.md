# data/

All market and reference data, separated by provenance. **Nothing here is
hand-edited** — every generated file is reproducible from `raw/` via `scripts/`.

```
data/
├── raw/          third-party source files, exactly as downloaded
│   ├── nse/      MW-ETF-*.csv   ETF market-data export (the strategy's source of truth)
│   │             EQUITY_L.csv   NSE equity list, symbol → ISIN
│   ├── dhan/     api-scrip-master-detailed.csv   scrip master with ISIN
│   ├── upstox/   NSE.json.gz    instrument master with ISIN
│   └── amfi/     NAVAll.txt     scheme master, ISIN → scheme name + AMC
├── reference/    etf-reference-data-<date>.csv   generated: symbol, ISIN, scheme name, AMC, benchmark
└── buckets/      etf-buckets-<date>.csv          generated: all 350 ETFs incl. exclusions
                  etf-tradable-buckets-<date>.csv generated: 311 tradable, DEBT/HYBRID removed
```

## Regenerating

```bash
# 1. reference data — see scripts/README.md for the download URLs
python3 scripts/fetch_etf_reference_data.py \
    data/buckets/etf-tradable-buckets-2026-09-17.csv \
    data/reference/etf-reference-data-2026-09-20.csv \
    --dhan-file data/raw/dhan/api-scrip-master-detailed.csv \
    --upstox-file data/raw/upstox/NSE.json.gz \
    --amfi-file data/raw/amfi/NAVAll.txt \
    --nse-file data/raw/nse/EQUITY_L.csv

# 2. bucket taxonomy (reference CSV is optional but improves GLOBAL — D-115)
python3 scripts/build_etf_buckets.py \
    data/raw/nse/MW-ETF-17-Sep-2026.csv \
    data/buckets/etf-buckets-2026-09-17.csv \
    data/reference/etf-reference-data-2026-09-20.csv
```

## Conventions

- **Dated filenames.** Generated files carry the date of the source data, never
  overwritten in place, so any past taxonomy can be reproduced and compared.
- **`raw/` is append-only.** Source files are snapshots; a newer download lands
  beside the old one rather than replacing it.
- **Liquidity is informational.** Bucketing is purely tracking-based (D-112), so
  `VOLUME_INFO_ONLY` and `LIQUID_INFO_ONLY` are carried for reference and read by
  no classification logic.

> ⚠️ `raw/dhan/api-scrip-master-detailed.csv` is ~34 MB and changes daily. It is
> committed as a dated snapshot for reproducibility. If the repository grows
> uncomfortable, this is the file to move to S3 and reference by URL.
