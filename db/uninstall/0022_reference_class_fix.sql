-- Undo 0022: put the rows it lifted back to EQUITY / REVIEW.
UPDATE atom.instrument
SET asset_class = 'EQUITY'
WHERE status = 'ACTIVE' AND status_reason = 'classified by the reference import'
  AND asset_class IN ('COMMODITY', 'GLOBAL');
UPDATE atom.instrument
SET status = 'REVIEW',
    status_reason = 'registered from a broker holding; classify before ATOM may trade it',
    status_changed_at = now()
WHERE status = 'ACTIVE' AND status_reason = 'classified by the reference import';
