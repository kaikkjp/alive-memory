-- Backfill orphaned visitors from totems and visitor_traits.
-- Earlier consolidation only upserted visitors when both visitor_id AND
-- visitor_name were present in moment metadata, so callers that supplied
-- only visitor_id (e.g. Telegram user IDs) ended up with totems and traits
-- pointing at visitor_ids that have no row in the visitors table.
--
-- We pull first_visit/last_visit from the source records' own timestamps
-- (totems.first_seen / totems.last_referenced and visitor_traits.created_at)
-- so search_visitors's "ORDER BY last_visit DESC" preserves real recency
-- instead of bunching every backfilled visitor at the migration time.
-- INSERT OR IGNORE keeps this idempotent on every startup.

INSERT OR IGNORE INTO visitors
    (id, name, trust_level, visit_count, first_visit, last_visit, emotional_imprint, summary)
SELECT visitor_id, visitor_id, 'stranger', 1, MIN(ts_min), MAX(ts_max), '', ''
FROM (
    SELECT visitor_id,
           MIN(first_seen) AS ts_min,
           MAX(last_referenced) AS ts_max
    FROM totems
    WHERE visitor_id IS NOT NULL AND visitor_id != ''
    GROUP BY visitor_id
    UNION ALL
    SELECT visitor_id,
           MIN(created_at) AS ts_min,
           MAX(created_at) AS ts_max
    FROM visitor_traits
    WHERE visitor_id IS NOT NULL AND visitor_id != ''
    GROUP BY visitor_id
)
GROUP BY visitor_id;
