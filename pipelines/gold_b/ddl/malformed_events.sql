-- ④ 오류 하나 = 한 줄 (한 메시지에 오류가 여러 개면 여러 줄). 시간 폴더는 kafka_timestamp(UTC) 기준.
-- (topic, kafka_partition, kafka_offset, rule_version, field)가 같은 오류는 한 번만 쌓는다.
CREATE EXTERNAL TABLE IF NOT EXISTS gold_b.malformed_events (
  topic           STRING    COMMENT 'Kafka 토픽',
  kafka_partition INT       COMMENT '파티션',
  kafka_offset    BIGINT    COMMENT '파티션 안 위치 (재처리 시작 위치)',
  kafka_timestamp TIMESTAMP COMMENT 'Kafka 기록 시각 (UTC, 오염 시작 시점)',
  field           STRING    COMMENT '문제가 난 필드 하나. 메시지 전체 파싱 실패는 __message__',
  reason          STRING    COMMENT 'PARSE_ERROR, MISSING_FIELD, TYPE_MISMATCH, INVALID_VALUE',
  raw_sample      STRING    COMMENT '마스킹한 원문 일부 (필드 이름 유지, 값만 가림). 메시지의 첫 줄에만, 나머지는 NULL',
  rule_version    STRING    COMMENT '적용한 형식 검사 규칙표 버전',
  loaded_at       TIMESTAMP COMMENT '원장에 쌓은 시각 (UTC)'
)
PARTITIONED BY (dt STRING, hour STRING)
STORED AS PARQUET
LOCATION 's3://clothes-query-datalake/gold_b/malformed_events/'
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
  'storage.location.template'    = 's3://clothes-query-datalake/gold_b/malformed_events/dt=${dt}/hour=${hour}/',
  'parquet.compression'          = 'SNAPPY'
);
