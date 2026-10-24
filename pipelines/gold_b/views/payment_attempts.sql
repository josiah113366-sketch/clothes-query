-- gold_b.payment_attempts: docs/design/gold-b/README.md 「탐지가 읽는 것」의 SQL과 같다 (tests/test_views.py가 확인).
-- Athena에서 실행한다. 만드는 순서는 views/README.md.
CREATE OR REPLACE VIEW gold_b.payment_attempts AS
SELECT payment_id, order_id, attempt_no, pg, status, failure_code,
       CASE
         WHEN failure_code IN ('PG_TIMEOUT','PG_ERROR') THEN 'PG'
         WHEN failure_code IN ('INSUFFICIENT_BALANCE','CARD_LIMIT_EXCEEDED','CARD_DECLINED') THEN 'CUSTOMER'
         WHEN status = 'FAILED' THEN 'UNKNOWN'
       END AS failure_cause,
       completed_at, loaded_at
FROM gold_b.payment_states
WHERE hold_reason IS NULL;
