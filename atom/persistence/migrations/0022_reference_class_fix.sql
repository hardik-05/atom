-- 0022_reference_class_fix.sql
-- D-214. An ETF first met as a broker holding (a manual buy) was registered before the
-- reference import knew it: asset class EQUITY, status REVIEW. The import's upsert then kept
-- both, so three gold/silver ETFs sat in EQUITY, two Hang Seng ETFs were missing from GLOBAL,
-- and every such ETF failed the tradability gate. The import now corrects both (code); this
-- corrects the rows already written.

-- The class follows the reference bucket. In the reference data COMMODITY and GLOBAL buckets
-- are exactly the COMMODITY and GLOBAL INDICES categories; every other bucket is EQUITY.
UPDATE atom.instrument i
SET asset_class = c.bucket
FROM atom.instrument_classification c
WHERE c.instrument_id = i.instrument_id
  AND c.bucket IN ('COMMODITY', 'GLOBAL')
  AND i.asset_class <> c.bucket;

-- Classified, so no longer awaiting review. BLOCKED or any other status is not touched.
UPDATE atom.instrument i
SET status = 'ACTIVE',
    status_reason = 'classified by the reference import',
    status_changed_at = now()
WHERE i.status = 'REVIEW'
  AND EXISTS (SELECT 1 FROM atom.instrument_classification c
              WHERE c.instrument_id = i.instrument_id);
