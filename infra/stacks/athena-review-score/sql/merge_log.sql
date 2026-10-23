-- 하루치 후기별 점수 로그(staging)를 review_score_log 테이블에 반영(upsert). 초안 2026-10-22 — 실제 Athena 에서 검증 전.
-- 자리표시자: {{database}}, {{log_table}}, {{staging_log_table}}, {{year}}, {{month}}, {{day}}, {{model_version}}, {{model_version_no}}
-- 실행 순서: merge.sql 을 먼저, 이 파일을 나중에. 점수 반영이 실패했는데 로그만 먼저 들어가면 그 후기가 "점수 있음"으로 오인되어 다시 점수화되지 않는다.
-- 로그 한 행 = 점수를 매긴 후기 한 개(속성이 0개여도 n_aspects = 0 으로 한 행). 파싱에 실패한 후기는 Job 이 로그를 쓰지 않으므로 여기에 없다 → 다음 실행에서 다시 선택된다.
-- 같은 (review_id, model_version, review_date) 가 staging 에 여러 번 있으면 analyzed_at 이 가장 최근인 행만 남긴다.
MERGE INTO {{database}}.{{log_table}} AS t
USING (
  SELECT review_id,
         model_version,
         COALESCE(model_version_no, CAST('{{model_version_no}}' AS decimal(4, 1))) AS model_version_no,
         analyzed_at,
         review_date,
         n_aspects
  FROM (
    SELECT *,
           row_number() OVER (
             PARTITION BY review_id, model_version, review_date
             ORDER BY analyzed_at DESC
           ) AS rn
    FROM {{database}}.{{staging_log_table}}
    WHERE year = '{{year}}'
      AND month = '{{month}}'
      AND day = '{{day}}'
      AND model_version = '{{model_version}}'
      AND review_date = CAST(concat(year, '-', month, '-', day) AS date)
  )
  WHERE rn = 1
) AS s
ON  t.review_id     = s.review_id
AND t.model_version = s.model_version
AND t.review_date   = s.review_date
WHEN MATCHED THEN
  UPDATE SET model_version_no = s.model_version_no, analyzed_at = s.analyzed_at, n_aspects = s.n_aspects
WHEN NOT MATCHED THEN
  INSERT (review_id, model_version, model_version_no, analyzed_at, review_date, n_aspects)
  VALUES (s.review_id, s.model_version, s.model_version_no, s.analyzed_at, s.review_date, s.n_aspects);
