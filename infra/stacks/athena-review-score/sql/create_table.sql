-- Iceberg 테이블 생성 (한 번만 실행). 초안 2026-10-22 — 실제 Athena 에서 검증 전.
-- 자리표시자 {{...}} 는 SSM 설정 파라미터(/clothes-query/dev/athena-review-score/config)의 값으로 채운다. 버킷 이름을 파일에 적지 않기 위해서다.
--   {{database}}, {{table}}, {{table_location}}
-- 실행: Athena 워크그룹(config 의 workgroup)으로 실행한다. 이미 있으면 실패하므로 두 번 실행하지 않는다.
-- 열 설명
--   review_id      후기 ID
--   aspect         속성(11개 중 하나)
--   score          점수 -2~2
--   model_version  점수를 낸 모델 버전(예: 2.4b_score_s2c). 같은 후기를 다른 버전으로 다시 점수화하면 행이 따로 쌓인다
--   analyzed_at    분석 시각(UTC)
--   review_date    후기 작성일(KST). 파티션 열 — 실행한 날이 아니다
CREATE TABLE {{database}}.{{table}} (
  review_id     string,
  aspect        string,
  score         int,
  model_version string,
  analyzed_at   timestamp,
  review_date   date
)
PARTITIONED BY (review_date)
LOCATION '{{table_location}}'
TBLPROPERTIES (
  'table_type' = 'ICEBERG',
  'format' = 'parquet',
  'write_compression' = 'snappy',
  -- VACUUM 이 지울 스냅샷 기준: 7일보다 오래되고, 최소 5개는 남긴다(되돌려 볼 여지)
  'vacuum_max_snapshot_age_seconds' = '604800',
  'vacuum_min_snapshots_to_keep' = '5'
);
