-- 이상 이력: 판정 잡이 5분마다 새 줄로 쌓는다 (지우거나 고치지 않는다). 같은 이상이 회차(run_id)마다 여러 줄일 수 있다.
-- "현재 보기"(이상별 가장 최근 줄)는 views/anomaly_current.sql. 시간 폴더는 날짜(dt)만, 기준은 detected_at(UTC). 양이 적어 시간 폴더는 두지 않는다.
-- 컬럼 설명: docs/design/agent/anomaly-answer-key.md 5절. 코드 쪽 기준은 agent/detect/athena_io.py의 TABLE_SPECS.
CREATE EXTERNAL TABLE IF NOT EXISTS gold_b.anomaly (
  run_id          STRING    COMMENT '판정 회차. 정기 순찰은 20261020T1510Z, 재판정은 <구간 시작>-RD-<요청 번호>',
  anomaly_id      STRING    COMMENT '규칙·규칙 버전·대상·시간대 시작의 해시. 같은 입력이면 같은 번호',
  rule_id         STRING    COMMENT 'R1_PG_FAILURES, R3_BRONZE_LAG, R4_MALFORMED, R5_DUPLICATE_SUCCESS, R6_ORDER_TOTAL_MISMATCH',
  rule_version    STRING    COMMENT '규칙 묶음 버전',
  anomaly_type    STRING    COMMENT 'PG_FAILURE_SPIKE, BRONZE_LAG_SPIKE, MALFORMED_SPIKE, DUPLICATE_SUCCESS_PAYMENT, ORDER_TOTAL_MISMATCH',
  source_table    STRING    COMMENT '읽은 원장 또는 뷰',
  window_start    TIMESTAMP COMMENT '판정한 시간대 시작 (UTC)',
  window_end      TIMESTAMP COMMENT '판정한 시간대 끝 (UTC)',
  scope_type      STRING    COMMENT '범위 종류: pg, topic, global',
  scope_key       STRING    COMMENT '범위: PG 이름, 토픽 이름, all, orders, orders-resolved',
  metric          STRING    COMMENT '본 지표 이름',
  observed_value  DOUBLE    COMMENT '관측값',
  baseline_value  DOUBLE    COMMENT '비교 기준',
  baseline_kind   STRING    COMMENT 'FIXED_THRESHOLD, PREV_WINDOW',
  sample_size     BIGINT    COMMENT '판정에 쓴 건수 (없으면 NULL)',
  episode_start   TIMESTAMP COMMENT '이어진 이상 기간 시작 (아직 비어 있음)',
  episode_end     TIMESTAMP COMMENT '이어진 이상 기간 끝 (아직 비어 있음)',
  evidence_ref    STRING    COMMENT '조사가 볼 곳과 근거 (JSON 문자열)',
  status          STRING    COMMENT 'OPEN, RESOLVED (R6 해소 줄). INVESTIGATING, REPORTED는 예약',
  detected_at     TIMESTAMP COMMENT '판정 잡이 기록한 시각 (UTC)'
)
PARTITIONED BY (dt STRING)
STORED AS PARQUET
LOCATION 's3://clothes-query-datalake/gold_b/anomaly/'
TBLPROPERTIES (
  'projection.enabled'           = 'true',
  'projection.dt.type'           = 'date',
  'projection.dt.format'         = 'yyyy-MM-dd',
  'projection.dt.range'          = '2026-09-01,NOW',
  'projection.dt.interval'       = '1',
  'projection.dt.interval.unit'  = 'DAYS',
  'storage.location.template'    = 's3://clothes-query-datalake/gold_b/anomaly/dt=${dt}/',
  'parquet.compression'          = 'SNAPPY'
);
