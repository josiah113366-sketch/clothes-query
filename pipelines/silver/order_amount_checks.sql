-- silver_runs.sql의 DB 준비 후 배포. run_id 파티션은 공개자가 개별 등록한다.
CREATE EXTERNAL TABLE IF NOT EXISTS silver.order_amount_checks (
  order_id STRING,
  check_name STRING,
  check_version STRING,
  status STRING,
  order_total_amount BIGINT,
  item_total_amount BIGINT,
  amount_difference BIGINT,
  checked_at TIMESTAMP,
  checked_at_utc STRING,
  source_manifest STRING,
  format_rule_version STRING
)
PARTITIONED BY (run_id STRING)
STORED AS PARQUET
LOCATION 's3://clothes-query-datalake/silver/runtime/trade/catalog-data/runs/'
TBLPROPERTIES ('classification'='parquet', 'projection.enabled'='false');
