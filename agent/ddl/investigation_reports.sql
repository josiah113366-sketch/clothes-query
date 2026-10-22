-- 조사 에이전트의 원인 리포트: 이상 하나를 조사해 낼 때마다 한 줄. 지우거나 고치지 않는다 (다시 조사하면 새 줄).
-- 재처리로 이어지면 reprocess_events의 REQUESTED 줄 detail에 anomaly_id와 report_id를 남겨 연결한다 (Gold B 담당 권장).
-- 시간 폴더는 날짜(dt)만, 기준은 created_at(UTC). 리뷰 원문·개인정보는 담지 않는다.
CREATE EXTERNAL TABLE IF NOT EXISTS agent.investigation_reports (
  report_id             STRING    COMMENT '리포트 번호',
  anomaly_id            STRING    COMMENT '조사한 이상 (gold_b.anomaly.anomaly_id)',
  investigation_run_id  STRING    COMMENT '이 리포트를 만든 조사 실행 (investigation_runs.run_id)',
  created_at            TIMESTAMP COMMENT '리포트를 만든 시각 (UTC)',
  cause_layer           STRING    COMMENT 'PAYMENT, INGEST, DATA_QUALITY, UNKNOWN',
  conclusion            STRING    COMMENT '결론 한두 문장',
  claims                STRING    COMMENT '주장 목록 (JSON 배열 문자열): [{text, kind: FACT 또는 ASSUMPTION, evidence: [{tool}]}]',
  trace                 STRING    COMMENT '조사 과정 (JSON 배열 문자열): 부른 도구, 인자, 성공·오류·거절',
  problems              STRING    COMMENT '검사를 통과하지 못한 점 (JSON 배열 문자열). 없으면 NULL',
  model_id              STRING    COMMENT '사용한 모델 ID'
)
PARTITIONED BY (dt STRING)
STORED AS PARQUET
LOCATION 's3://clothes-query-datalake/agent/investigation_reports/'
TBLPROPERTIES (
  'projection.enabled'           = 'true',
  'projection.dt.type'           = 'date',
  'projection.dt.format'         = 'yyyy-MM-dd',
  'projection.dt.range'          = '2026-09-01,NOW',
  'projection.dt.interval'       = '1',
  'projection.dt.interval.unit'  = 'DAYS',
  'storage.location.template'    = 's3://clothes-query-datalake/agent/investigation_reports/dt=${dt}/',
  'parquet.compression'          = 'SNAPPY'
);
