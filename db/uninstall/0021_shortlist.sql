-- Undo 0021.
DELETE FROM atom.account_config WHERE config_key_id IN
    (SELECT config_key_id FROM atom.config_key WHERE key_name = 'shortlist_size');
DELETE FROM atom.config_key WHERE key_name = 'shortlist_size';
DROP TABLE IF EXISTS atom.universe_shortlist;
ALTER TABLE atom.run DROP COLUMN IF EXISTS sells_released_at;
