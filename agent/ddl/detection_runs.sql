-- 순찰 기록: 판정 잡이 한 바퀴 돌 때마다 한 줄. "이상이 없어서 기록이 없는 것"과 "순찰이 안 돈 것"을 구별한다.
-- 시간 폴더는 날짜(dt)만, 기준은 started_at(UTC).
CREATE EXTERNAL TABLE IF NOT EXISTS gold_b.detection_runs (
  run_id         STRING    COMMENT '판정 회차 (anomaly.run_id와 같다)',
  kind           STRING    COMMENT 'REGULAR(정기 순찰), REDETECT(재처리 뒤 재판정)',
  request_id     STRING    COMMENT '재판정이면 재처리 요청 번호, 정기 순찰이면 NULL',
  judged_from    TIMESTAMP COMMENT '판정한 구간 시작 (UTC)',
  judged_to      TIMESTAMP COMMENT '판정한 구간 끝 (UTC)',
  started_at     TIMESTAMP COMMENT '이 한 바퀴를 시작한 시각 (UTC)',
  anomaly_count  BIGINT    COMMENT '이 회차에서 판정한 이상 개수'
)
PARTITIONED BY (dt STRING)
STORED AS PARQUET
LOCATION 's3://clothes-query-datalake/gold_b/detection_runs/'
TBLPROPERTIES (
  'projection.enabled'           = 'true',
  'projection.dt.type'           = 'date',
  'projection.dt.format'         = 'yyyy-MM-dd',
  'projection.dt.range'          = '2026-09-01,NOW',
  'projection.dt.interval'       = '1',
  'projection.dt.interval.unit'  = 'DAYS',
  'storage.location.template'    = 's3://clothes-query-datalake/gold_b/detection_runs/dt=${dt}/',
  'parquet.compression'          = 'SNAPPY'
);
