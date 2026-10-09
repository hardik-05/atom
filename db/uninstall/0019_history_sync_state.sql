-- Undo 0019: the history sync's record of what it has already asked the broker for.
-- Holds no prices, so dropping it costs one full re-fetch and nothing else.
DROP TABLE IF EXISTS atom.history_sync_state;
