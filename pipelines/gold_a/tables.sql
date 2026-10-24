-- 배포 시 문장별로 실행한다. 처리 잡은 테이블을 만들거나 기존 LOCATION을 바꾸지 않는다.
CREATE DATABASE IF NOT EXISTS gold_a;

CREATE EXTERNAL TABLE IF NOT EXISTS gold_a.gold_runs (
  run_id STRING, completed_at TIMESTAMP, status STRING, quality_status STRING,
  source_manifest STRING, source_manifest_sha256 STRING, silver_run_id STRING,
  silver_manifest STRING, products_manifest STRING, silver_clicks_manifest STRING,
  previous_run_id STRING, held_scope_count BIGINT, available_tables_json STRING, code_ref STRING
)
PARTITIONED BY (channel STRING)
STORED AS PARQUET
LOCATION 's3://clothes-query-datalake/gold_a/catalog/'
TBLPROPERTIES ('projection.enabled'='false');

CREATE EXTERNAL TABLE IF NOT EXISTS gold_a.order_sales_hourly_runs (
  hour_start_kst STRING, order_count BIGINT, paid_order_count BIGINT, approved_amount BIGINT
)
PARTITIONED BY (run_id STRING)
STORED AS PARQUET LOCATION 's3://clothes-query-datalake/gold_a/runtime/trade/runs/'
TBLPROPERTIES ('projection.enabled'='false');

CREATE EXTERNAL TABLE IF NOT EXISTS gold_a.product_sales_daily_runs (
  sales_date_kst DATE, article_id STRING, product_code BIGINT, paid_order_count BIGINT,
  sold_quantity BIGINT, item_sales_amount BIGINT
)
PARTITIONED BY (run_id STRING)
STORED AS PARQUET LOCATION 's3://clothes-query-datalake/gold_a/runtime/trade/runs/'
TBLPROPERTIES ('projection.enabled'='false');

CREATE EXTERNAL TABLE IF NOT EXISTS gold_a.funnel_session_product_runs (
  session_id STRING, article_id STRING, product_code BIGINT, first_view_at_kst STRING,
  first_cart_at_kst STRING, first_order_at_kst STRING, first_paid_at_kst STRING,
  has_view BOOLEAN, has_cart BOOLEAN, has_order BOOLEAN, has_paid BOOLEAN, ordered_after_cart BOOLEAN
)
PARTITIONED BY (run_id STRING)
STORED AS PARQUET LOCATION 's3://clothes-query-datalake/gold_a/runtime/funnels/runs/'
TBLPROPERTIES ('projection.enabled'='false');

CREATE EXTERNAL TABLE IF NOT EXISTS gold_a.funnel_daily_runs (
  funnel_date_kst DATE, article_id STRING, product_code BIGINT, view_sessions BIGINT,
  cart_sessions BIGINT, order_sessions BIGINT, paid_sessions BIGINT, cart_order_sessions BIGINT,
  view_to_cart_rate DOUBLE, view_to_order_rate DOUBLE, view_to_paid_rate DOUBLE,
  cart_to_order_rate DOUBLE, order_to_paid_rate DOUBLE
)
PARTITIONED BY (run_id STRING)
STORED AS PARQUET LOCATION 's3://clothes-query-datalake/gold_a/runtime/funnels/runs/'
TBLPROPERTIES ('projection.enabled'='false');

CREATE EXTERNAL TABLE IF NOT EXISTS gold_a.review_product_daily_runs (
  review_date_kst DATE, article_id STRING, product_code BIGINT, review_count BIGINT,
  rating_sum BIGINT, low_rating_count BIGINT, average_rating DOUBLE, low_rating_rate DOUBLE
)
PARTITIONED BY (run_id STRING)
STORED AS PARQUET LOCATION 's3://clothes-query-datalake/gold_a/runtime/reviews/runs/'
TBLPROPERTIES ('projection.enabled'='false');

CREATE EXTERNAL TABLE IF NOT EXISTS gold_a.review_aspect_daily_runs (
  review_date_kst DATE, article_id STRING, product_code BIGINT, aspect STRING, model_version STRING, model_version_no STRING,
  scored_review_count BIGINT, score_sum BIGINT, score_neg2_count BIGINT, score_neg1_count BIGINT,
  score_zero_count BIGINT, score_pos1_count BIGINT, score_pos2_count BIGINT, average_score DOUBLE
)
PARTITIONED BY (run_id STRING)
STORED AS PARQUET LOCATION 's3://clothes-query-datalake/gold_a/runtime/reviews/runs/'
TBLPROPERTIES ('projection.enabled'='false');

CREATE EXTERNAL TABLE IF NOT EXISTS gold_a.refresh_holds_runs (
  table_name STRING, key_json STRING, reason STRING, previous_result_available BOOLEAN, last_normal_result_json STRING
)
PARTITIONED BY (channel STRING, run_id STRING)
STORED AS PARQUET LOCATION 's3://clothes-query-datalake/gold_a/catalog/holds/'
TBLPROPERTIES ('projection.enabled'='false');
