-- ① 결제 시도 한 건 = 한 줄. payments 토픽에서 형식 검사를 통과하고 __op가 c 또는 r인 메시지.
-- 시간 폴더는 completed_at(UTC) 기준. 중복 제거·충돌 분리·원인 분류는 뷰에서 한다.
-- amount·method·requested_at은 컬럼으로 두지 않고 결제 내용 지문(payment_content_hash)에만 들어간다.
CREATE EXTERNAL TABLE IF NOT EXISTS gold_b.payment_events (
  payment_id      STRING    COMMENT '결제 시도 고유 번호. 중복 제거 기준',
  order_id        STRING    COMMENT '주문 번호. 재시도해도 같음',
  attempt_no      INT       COMMENT '그 주문에서 몇 번째 시도 (1부터)',
  pg              STRING    COMMENT '결제대행사 (PG_A, PG_B)',
  status          STRING    COMMENT 'SUCCESS 또는 FAILED',
  failure_code    STRING    COMMENT '실패 이유. 성공이면 NULL',
  completed_at    TIMESTAMP COMMENT '결제 결과 확정 시각 (UTC)',
  payment_content_hash STRING COMMENT '결제 업무 필드 9개를 정규화한 지문. 같은 payment_id인데 다르면 내용 충돌',
  fingerprint_version  STRING COMMENT '지문 규칙 버전 (pipelines/payment_fingerprint.py). 같은 버전끼리만 비교',
  kafka_partition INT       COMMENT 'payments 토픽 파티션',
  kafka_offset    BIGINT    COMMENT '파티션 안 위치',
  loaded_at       TIMESTAMP COMMENT '원장에 쌓은 시각 (UTC)'
)
PARTITIONED BY (dt STRING, hour STRING)
STORED AS PARQUET
LOCATION 's3://clothes-query-datalake/gold_b/payment_events/'
TBLPROPERTIES (
  'projection.enabled'           = 'true',
  'projection.dt.type'           = 'date',
  'projection.dt.format'         = 'yyyy-MM-dd',
  'projection.dt.range'          = '2026-09-01,NOW',
  'projection.dt.interval'       = '1',
  'projection.dt.interval.unit'  = 'DAYS',
  'projection.hour.type'         = 'integer',
  'projection.hour.range'        = '0,23',
  'projection.hour.digits'       = '2',
  'storage.location.template'    = 's3://clothes-query-datalake/gold_b/payment_events/dt=${dt}/hour=${hour}/',
  'parquet.compression'          = 'SNAPPY'
);
