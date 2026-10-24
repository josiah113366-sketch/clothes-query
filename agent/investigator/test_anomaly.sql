-- 조사 에이전트 시험용 이상 줄. Athena 콘솔에서 위 INSERT를 한 번 실행하면 조사 DAG(5분마다)가 이 줄을 집어 간다.
-- 구분: anomaly_id가 'a-test-'로 시작한다. 채점(agent/eval/score.py)은 이 접두어를 건너뛴다. 지우지 않는다(이력은 쌓기만 한다).
-- 기대: 5분 안에 agent.investigation_runs에 이 anomaly_id가 DONE으로 남고, 리포트가 1건 생긴다(원인 층 1개, 근거 있는 FACT).
--       시험 사건은 실제 원장에 없으므로 근거가 약해 UNKNOWN이 나올 수 있다. 그 경우도 "호출·검증·저장까지 동작"이면 성공이다.
-- 끝나면 맨 아래 RESOLVED 줄을 실행해 현재 보기에서 닫는다.

INSERT INTO gold_b.anomaly
SELECT
  'a-test-run'                                                         AS run_id,
  'a-test-0001'                                                        AS anomaly_id,
  'R1_PG_FAILURES'                                                     AS rule_id,
  '0.2.0'                                                              AS rule_version,
  'PG_FAILURE_SPIKE'                                                   AS anomaly_type,
  'payment_attempts'                                                   AS source_table,
  CAST(date_add('minute', -10, current_timestamp) AS timestamp)        AS window_start,
  CAST(date_add('minute', -5, current_timestamp) AS timestamp)         AS window_end,
  'pg'                                                                 AS scope_type,
  'PG_A'                                                               AS scope_key,
  'pg_cause_failures'                                                  AS metric,
  12.0                                                                 AS observed_value,
  5.0                                                                  AS baseline_value,
  'FIXED_THRESHOLD'                                                    AS baseline_kind,
  CAST(20 AS bigint)                                                   AS sample_size,
  CAST(NULL AS timestamp)                                              AS episode_start,
  CAST(NULL AS timestamp)                                              AS episode_end,
  '{"table": "payment_attempts", "pg": "PG_A", "pg_cause_failure_rate": 0.6, "test": true}' AS evidence_ref,
  'OPEN'                                                               AS status,
  CAST(current_timestamp AS timestamp)                                 AS detected_at,
  date_format(current_timestamp, '%Y-%m-%d')                           AS dt;

-- 확인: 현재 보기에 보이는지
-- SELECT anomaly_id, status, detected_at FROM gold_b.anomaly_current WHERE anomaly_id = 'a-test-0001';

-- 정리(시험이 끝난 뒤): 같은 id로 RESOLVED 줄을 추가한다. 삭제하지 않는다.
-- INSERT INTO gold_b.anomaly
-- SELECT run_id, anomaly_id, rule_id, rule_version, anomaly_type, source_table, window_start, window_end, scope_type, scope_key, metric,
--        observed_value, baseline_value, baseline_kind, sample_size, episode_start, episode_end, evidence_ref,
--        'RESOLVED', CAST(current_timestamp AS timestamp), date_format(current_timestamp, '%Y-%m-%d')
-- FROM gold_b.anomaly_current WHERE anomaly_id = 'a-test-0001';
