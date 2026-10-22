-- ③ 1분 × 토픽 × 파티션 = 한 줄. Bronze 지연 수집기가 쓴다. 재처리로 다시 만들지 않는다.
-- 시간 폴더는 collected_at(UTC) 기준.
CREATE EXTERNAL TABLE IF NOT EXISTS gold_b.bronze_lag_snapshots (
  collected_at     TIMESTAMP COMMENT '측정 시각 (UTC)',
  topic            STRING    COMMENT 'S3 Sink 소비자 그룹의 대상 토픽',
  kafka_partition  INT       COMMENT '파티션',
  end_offset       BIGINT    COMMENT '마지막 메시지 위치 (Kafka 관리 API)',
  committed_offset BIGINT    COMMENT 'S3 Sink가 처리한 위치 (Kafka 관리 API)',
  lag_msgs         BIGINT    COMMENT 'end_offset - committed_offset',
  lag_sec          DOUBLE    COMMENT '처리 안 된 가장 오래된 메시지의 Kafka 시각과 측정 시각의 차이 (초)',
  connector_state  STRING    COMMENT 'Kafka Connect REST의 커넥터 상태 (RUNNING 등)'
)
PARTITIONED BY (dt STRING, hour STRING)
STORED AS PARQUET
LOCATION 's3://clothes-query-datalake/gold_b/bronze_lag_snapshots/'
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
  'storage.location.template'    = 's3://clothes-query-datalake/gold_b/bronze_lag_snapshots/dt=${dt}/hour=${hour}/',
  'parquet.compression'          = 'SNAPPY'
);
