-- 시연 조회용 DDL 초안. 배포 담당 검수 후 문장별 적용한다. 이번 구현에서는 실행하지 않았다.
-- 운영 gold_a.gold_runs/current에는 등록하지 않는다. 모든 조회에서 run_id를 지정한다.
-- DB 이름·권한 확인 전 적용하지 않는다. 기존 파티션이 있으면 LOCATION을 먼저 대조하며 교체하지 않는다.
CREATE DATABASE IF NOT EXISTS gold_a_demo;

CREATE EXTERNAL TABLE IF NOT EXISTS gold_a_demo.funnel_session_product_runs (
  session_id STRING, article_id STRING, product_code BIGINT, first_view_at_kst STRING,
  first_cart_at_kst STRING, first_order_at_kst STRING, first_paid_at_kst STRING,
  has_view BOOLEAN, has_cart BOOLEAN, has_order BOOLEAN, has_paid BOOLEAN, ordered_after_cart BOOLEAN
)
PARTITIONED BY (run_id STRING)
STORED AS PARQUET LOCATION 's3://clothes-query-datalake/pipelines/demo/funnels/runs/'
TBLPROPERTIES ('projection.enabled'='false');

CREATE EXTERNAL TABLE IF NOT EXISTS gold_a_demo.funnel_daily_runs (
  funnel_date_kst DATE, article_id STRING, product_code BIGINT, view_sessions BIGINT,
  cart_sessions BIGINT, order_sessions BIGINT, paid_sessions BIGINT, cart_order_sessions BIGINT,
  view_to_cart_rate DOUBLE, view_to_order_rate DOUBLE, view_to_paid_rate DOUBLE,
  cart_to_order_rate DOUBLE, order_to_paid_rate DOUBLE
)
PARTITIONED BY (run_id STRING)
STORED AS PARQUET LOCATION 's3://clothes-query-datalake/pipelines/demo/funnels/runs/'
TBLPROPERTIES ('projection.enabled'='false');

-- 아래 두 문장은 해당 S3 실행의 completed.json/manifest.json/PASS를 확인한 뒤에만 실행한다.
ALTER TABLE gold_a_demo.funnel_session_product_runs
ADD IF NOT EXISTS PARTITION (run_id='funnels-demo-closed-20261025')
LOCATION 's3://clothes-query-datalake/pipelines/demo/funnels/runs/funnels-demo-closed-20261025/gold/funnel_session_product/';

ALTER TABLE gold_a_demo.funnel_daily_runs
ADD IF NOT EXISTS PARTITION (run_id='funnels-demo-closed-20261025')
LOCATION 's3://clothes-query-datalake/pipelines/demo/funnels/runs/funnels-demo-closed-20261025/gold/funnel_daily/';

-- 이 고정 시연 입력의 기대값: 각각 109행. 전체 방문자/전체 날짜 전환율이 아니다.
SELECT COUNT(*) AS detail_rows
FROM gold_a_demo.funnel_session_product_runs
WHERE run_id='funnels-demo-closed-20261025';

SELECT COUNT(*) AS daily_rows, SUM(view_sessions) AS views, SUM(cart_sessions) AS carts,
       SUM(order_sessions) AS orders, SUM(paid_sessions) AS paid
FROM gold_a_demo.funnel_daily_runs
WHERE run_id='funnels-demo-closed-20261025';
