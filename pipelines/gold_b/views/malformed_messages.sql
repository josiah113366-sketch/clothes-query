-- gold_b.malformed_messages: docs/design/gold-b/README.md 「탐지가 읽는 것」의 SQL과 같다 (tests/test_views.py가 확인).
-- Athena에서 실행한다. 만드는 순서는 views/README.md.
CREATE OR REPLACE VIEW gold_b.malformed_messages AS
SELECT topic, kafka_partition, kafka_offset, rule_version,
       MIN(kafka_timestamp)        AS kafka_timestamp,
       COUNT(DISTINCT field)       AS error_count,
       ARRAY_AGG(CAST(ROW(field, reason) AS ROW(field VARCHAR, reason VARCHAR))) AS errors,
       MIN(loaded_at)              AS loaded_at,
       dt, hour
FROM gold_b.malformed_events
GROUP BY topic, kafka_partition, kafka_offset, rule_version, dt, hour;
