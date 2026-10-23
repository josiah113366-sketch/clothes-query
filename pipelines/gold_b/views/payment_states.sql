-- gold_b.payment_states: docs/design/gold-b/README.md 「탐지가 읽는 것」의 SQL과 같다 (tests/test_views.py가 확인).
-- Athena에서 실행한다. 만드는 순서는 views/README.md.
CREATE OR REPLACE VIEW gold_b.payment_states AS
WITH checks AS (
  SELECT kafka_partition, kafka_offset, loaded_at, 1 AS valid, payment_id, source_ts_ms, cdc_op,
         order_id, attempt_no, pg, status, failure_code, completed_at, rule_version
  FROM gold_b.payment_events
  UNION ALL
  SELECT kafka_partition, kafka_offset, loaded_at, 0 AS valid, record_key, MAX(source_ts_ms), NULL,
         NULL, NULL, NULL, NULL, NULL, NULL, rule_version
  FROM gold_b.malformed_events
  WHERE topic = 'payments' AND record_key IS NOT NULL
  GROUP BY kafka_partition, kafka_offset, loaded_at, record_key, rule_version
),
latest_checks AS (
  SELECT *
  FROM (SELECT c.*, ROW_NUMBER() OVER (PARTITION BY kafka_partition, kafka_offset
                                       ORDER BY loaded_at DESC, valid) AS check_rank
        FROM checks c)
  WHERE check_rank = 1
),
ordered AS (
  SELECT l.*,
         MIN(kafka_partition) OVER (PARTITION BY payment_id) AS first_partition,
         MAX(kafka_partition) OVER (PARTITION BY payment_id) AS last_partition,
         COUNT(*) OVER (PARTITION BY payment_id) AS event_count,
         MAX(source_ts_ms) OVER (PARTITION BY payment_id ORDER BY kafka_offset
                                 ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS earlier_max_ts,
         ROW_NUMBER() OVER (PARTITION BY payment_id ORDER BY kafka_offset DESC) AS from_last
  FROM latest_checks l
)
SELECT payment_id, order_id, attempt_no, pg, status, failure_code, completed_at, loaded_at,
       cdc_op, source_ts_ms, rule_version, kafka_partition, kafka_offset, event_count,
       CASE
         WHEN first_partition <> last_partition THEN 'MULTI_PARTITION'
         WHEN source_ts_ms < earlier_max_ts THEN 'ORDER_ANOMALY'
         WHEN valid = 0 THEN 'INVALID_LATEST'
       END AS hold_reason
FROM ordered
WHERE from_last = 1;
