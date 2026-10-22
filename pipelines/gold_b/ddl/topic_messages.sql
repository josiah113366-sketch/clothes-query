-- ② 메시지 하나 = 한 줄 (대상 토픽 전부, 형식 검사 결과와 상관없이). 내용은 담지 않는다.
-- 시간 폴더는 kafka_timestamp(UTC) 기준. 신뢰성 점검(오프셋 빈틈, 중복)도 이 표로 한다.
CREATE EXTERNAL TABLE IF NOT EXISTS gold_b.topic_messages (
  topic           STRING    COMMENT 'Kafka 토픽',
  kafka_partition INT       COMMENT '파티션',
  kafka_offset    BIGINT    COMMENT '파티션 안 위치',
  kafka_timestamp TIMESTAMP COMMENT 'Kafka 기록 시각 (UTC)',
  loaded_at       TIMESTAMP COMMENT '원장에 쌓은 시각 (UTC)'
)
PARTITIONED BY (dt STRING, hour STRING)
STORED AS PARQUET
LOCATION 's3://clothes-query-datalake/gold_b/topic_messages/'
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
  'storage.location.template'    = 's3://clothes-query-datalake/gold_b/topic_messages/dt=${dt}/hour=${hour}/',
  'parquet.compression'          = 'SNAPPY'
);
