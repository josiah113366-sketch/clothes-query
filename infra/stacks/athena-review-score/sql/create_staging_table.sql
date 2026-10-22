-- staging Parquet 을 읽는 Hive 외부 테이블 (한 번만 실행). 초안 2026-10-22 — 실제 Athena 에서 검증 전.
-- SageMaker Job 이 <staging_location>year=YYYY/month=MM/day=DD/scores_<model_version>.parquet 로 쓴 파일을 읽는다.
-- 파티션 프로젝션을 쓰므로 MSCK REPAIR / 파티션 등록이 필요 없다(경로 규칙만 맞으면 됨).
-- 자리표시자: {{database}}, {{staging_table}}, {{staging_location}}  (staging_location 은 / 로 끝난다)
-- 참고: 이 테이블은 MERGE 의 입력일 뿐이다. 결과 조회는 Iceberg 테이블로 한다.
CREATE EXTERNAL TABLE {{database}}.{{staging_table}} (
  review_id     string,
  aspect        string,
  score         int,
  model_version string,
  analyzed_at   timestamp
)
PARTITIONED BY (year string, month string, day string)
STORED AS PARQUET
LOCATION '{{staging_location}}'
TBLPROPERTIES (
  'projection.enabled' = 'true',
  'projection.year.type' = 'integer',
  'projection.year.range' = '2026,2035',
  'projection.year.digits' = '4',
  'projection.month.type' = 'integer',
  'projection.month.range' = '1,12',
  'projection.month.digits' = '2',
  'projection.day.type' = 'integer',
  'projection.day.range' = '1,31',
  'projection.day.digits' = '2',
  'storage.location.template' = '{{staging_location}}year=${year}/month=${month}/day=${day}/'
);
