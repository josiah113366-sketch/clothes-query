-- gold_b.payment_conflicts: docs/design/gold-b/README.md 「탐지가 읽는 것」의 SQL과 같다 (tests/test_views.py가 확인).
-- Athena에서 실행한다. 만드는 순서는 views/README.md.
CREATE OR REPLACE VIEW gold_b.payment_conflicts AS
SELECT payment_id, hold_reason, event_count, pg, status, completed_at,
       cdc_op, source_ts_ms, rule_version, kafka_partition, kafka_offset, loaded_at
FROM gold_b.payment_states
WHERE hold_reason IS NOT NULL;
