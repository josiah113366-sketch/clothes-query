-- 신뢰성 확인 쿼리 3개 (Athena 기준, 은서 님 장부 4개를 읽음)
-- 목적: 조사 에이전트가 원인을 찾기 전에 "이 장부를 믿어도 되나?"를 먼저 확인한다.
-- 모두 읽기 전용(SELECT)이다. 시각은 UTC. 조회 범위(:from_ts, :to_ts)는 호출하는 쪽이 정한다.

-- Q1 누락 확인: 파티션 안에서 offset 번호에 빈 곳이 있으면 메시지가 빠진 것이다.
--    (offset은 파티션마다 0,1,2,... 연속이어야 한다. 처음~끝 칸 수에서 실제 줄 수를 빼면 빠진 개수.)
SELECT topic,
       kafka_partition,
       MIN(kafka_offset)                                   AS first_offset,
       MAX(kafka_offset)                                   AS last_offset,
       COUNT(DISTINCT kafka_offset)                        AS rows_seen,
       (MAX(kafka_offset) - MIN(kafka_offset) + 1)
         - COUNT(DISTINCT kafka_offset)                    AS missing_count
FROM gold_b.topic_messages
WHERE kafka_timestamp >= :from_ts AND kafka_timestamp < :to_ts
GROUP BY topic, kafka_partition
HAVING (MAX(kafka_offset) - MIN(kafka_offset) + 1) - COUNT(DISTINCT kafka_offset) > 0;
-- 결과가 0줄이면 누락 없음.

-- Q2 중복 확인: 같은 메시지 위치가 두 번 쌓였는지(적재 쪽 문제 판단 기준)와, 같은 결제 번호가 두 번 쌓였는지(참고)를 센다.
--    메시지가 들어 있는 표는 topic_messages뿐이라 적재 문제는 이 표로 판단한다.
--    같은 payment_id는 Debezium 재시작·전송 재시도로 생기는 정상 현상이며 뷰가 걸러 준다. "재시작이 잦았는가"를 보는 참고값이다.
SELECT 'topic_messages' AS ledger,
       COUNT(*) - COUNT(DISTINCT CONCAT(topic, '-', CAST(kafka_partition AS VARCHAR), '-', CAST(kafka_offset AS VARCHAR))) AS duplicate_rows
FROM gold_b.topic_messages
WHERE kafka_timestamp >= :from_ts AND kafka_timestamp < :to_ts
UNION ALL
SELECT 'payment_events',
       COUNT(*) - COUNT(DISTINCT payment_id)
FROM gold_b.payment_events
WHERE completed_at >= :from_ts AND completed_at < :to_ts;
-- topic_messages 줄이 0이면 적재 중복 없음. 0보다 크면 적재 쪽 문제. payment_events 줄은 참고값이다(뷰가 걸러 주므로 지표는 안전).

-- Q3 멈춤(신선도) 확인: 장부를 쓰는 잡과 지연 수집기가 살아 있는지 본다.
--    은서 님 문서 기준: 2분 넘게 멈추면 고장이며, 데이터 이상과 섞지 않고 따로 표시한다.
SELECT 'ledger_writer' AS who,
       MAX(loaded_at) AS last_seen,
       date_diff('second', MAX(loaded_at), current_timestamp) AS stopped_sec,
       CASE WHEN date_diff('second', MAX(loaded_at), current_timestamp) > 120 THEN 'STOPPED' ELSE 'OK' END AS status
FROM gold_b.topic_messages
UNION ALL
SELECT 'lag_collector',
       MAX(collected_at),
       date_diff('second', MAX(collected_at), current_timestamp),
       CASE WHEN date_diff('second', MAX(collected_at), current_timestamp) > 120 THEN 'STOPPED' ELSE 'OK' END
FROM gold_b.bronze_lag_snapshots;
-- STOPPED면 "데이터 이상"이 아니라 "관제 자체 고장"으로 표시한다.
