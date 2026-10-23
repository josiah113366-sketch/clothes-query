-- gold_b.payment_conflicts: docs/design/gold-b/README.md 「탐지가 읽는 것」의 SQL과 같다 (tests/test_views.py가 확인).
-- Athena에서 실행한다. 만드는 순서는 views/README.md.
CREATE OR REPLACE VIEW gold_b.payment_conflicts AS
WITH grouped AS (
  SELECT payment_id, fingerprint_version,
         COUNT(*)                         AS row_count,
         filter(ARRAY[
           IF(COUNT(DISTINCT order_id) > 1,                  'order_id'),
           IF(COUNT(DISTINCT attempt_no) > 1,                'attempt_no'),
           IF(COUNT(DISTINCT pg) > 1,                        'pg'),
           IF(COUNT(DISTINCT status) > 1,                    'status'),
           IF(COUNT(DISTINCT coalesce(failure_code, '')) > 1, 'failure_code'),
           IF(COUNT(DISTINCT completed_at) > 1,              'completed_at')
         ], x -> x IS NOT NULL)          AS stored_fields,
         ARRAY_AGG(DISTINCT pg)           AS pgs,
         MIN(completed_at)                AS first_completed_at,
         MIN(loaded_at)                   AS first_loaded_at,
         MAX(loaded_at)                   AS last_loaded_at,
         ARRAY_AGG(CAST(ROW(kafka_partition, kafka_offset)
                   AS ROW(kafka_partition INTEGER, kafka_offset BIGINT))) AS sources
  FROM gold_b.payment_events
  GROUP BY payment_id, fingerprint_version          -- 지문 버전이 같은 줄끼리만 비교
  HAVING COUNT(DISTINCT payment_content_hash) > 1
)
SELECT payment_id, fingerprint_version, row_count,
       IF(cardinality(stored_fields) = 0, ARRAY['payment_content_hash'], stored_fields) AS conflict_fields,
       pgs, first_completed_at, first_loaded_at, last_loaded_at, sources
FROM grouped;
