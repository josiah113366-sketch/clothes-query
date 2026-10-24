-- 배포 시 실행. DB/테이블 생성·변경은 처리 잡이 수행하지 않는다.
CREATE DATABASE IF NOT EXISTS silver;
CREATE EXTERNAL TABLE IF NOT EXISTS silver.silver_runs (
  run_id STRING,
  completed_at TIMESTAMP,
  status STRING,
  quality_status STRING,
  checked_at TIMESTAMP,
  checked_at_utc STRING,
  check_version STRING,
  format_rule_version STRING,
  row_count BIGINT,
  coverage_status STRING,
  source_manifest STRING,
  source_manifest_sha256 STRING,
  result_location STRING,
  code_ref STRING
)
STORED AS PARQUET
LOCATION 's3://clothes-query-datalake/silver/runtime/trade/catalog/completed/'
TBLPROPERTIES ('classification'='parquet', 'projection.enabled'='false');
