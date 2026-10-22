-- 조사 실행 기록: 조사 한 번마다 한 줄. 대시보드의 에이전트 관리 화면(최근 조사, 성공/실패, 걸린 시간, 오류)이 읽는다.
-- 리포트를 못 만든 조사(오류, 한도 초과)도 남긴다. 시간 폴더는 날짜(dt)만, 기준은 started_at(UTC).
CREATE EXTERNAL TABLE IF NOT EXISTS agent.investigation_runs (
  run_id                 STRING    COMMENT '조사 실행 번호',
  anomaly_id             STRING    COMMENT '조사한 이상',
  started_at             TIMESTAMP COMMENT '조사 시작 시각 (UTC)',
  finished_at            TIMESTAMP COMMENT '조사 끝낸 시각 (UTC). 오류로 끝나도 기록한다',
  status                 STRING    COMMENT 'REPORTED(리포트 제출, 검사 통과), INCOMPLETE(검사를 못 통과한 리포트), UNKNOWN(한도 안에 결론 못 냄), ERROR(실행 오류)',
  report_id              STRING    COMMENT '만든 리포트. 없으면 NULL',
  cause_layer            STRING    COMMENT '리포트의 원인 층. 없으면 NULL',
  turns                  BIGINT    COMMENT '모델을 부른 횟수',
  tool_calls             BIGINT    COMMENT '조회 도구를 부른 횟수 (성공한 것)',
  rejected_submissions   BIGINT    COMMENT '리포트가 검사에 걸려 되돌아간 횟수',
  model_id               STRING    COMMENT '사용한 모델 ID',
  error                  STRING    COMMENT '오류 요약 (쿼리 내용·개인정보 없이 짧게). 없으면 NULL'
)
PARTITIONED BY (dt STRING)
STORED AS PARQUET
LOCATION 's3://clothes-query-datalake/agent/investigation_runs/'
TBLPROPERTIES (
  'projection.enabled'           = 'true',
  'projection.dt.type'           = 'date',
  'projection.dt.format'         = 'yyyy-MM-dd',
  'projection.dt.range'          = '2026-09-01,NOW',
  'projection.dt.interval'       = '1',
  'projection.dt.interval.unit'  = 'DAYS',
  'storage.location.template'    = 's3://clothes-query-datalake/agent/investigation_runs/dt=${dt}/',
  'parquet.compression'          = 'SNAPPY'
);
