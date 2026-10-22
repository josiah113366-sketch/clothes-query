-- 하루치 staging 결과를 Iceberg 테이블에 반영(upsert). 초안 2026-10-22 — 실제 Athena 에서 검증 전.
-- 자리표시자: {{database}}, {{table}}, {{staging_table}}, {{year}}, {{month}}, {{day}}, {{model_version}}
--   year/month/day 는 후기 작성일(KST)이고 두 자리 월·일(예: 2026, 10, 05)이다. 실행한 날이 아니다.
-- staging 은 쌓이는 방식이다: SageMaker Job 이 같은 날짜·버전을 다시 실행하면 실행시각이 들어간 새 파일이 생기므로
--   같은 (review_id, aspect, model_version, review_date) 행이 staging 에 여러 번 있을 수 있다.
--   그래서 원본에서 analyzed_at 이 가장 최근인 행만 남긴다(row_number). 이렇게 하지 않으면 MERGE 가 "한 행에 여러 행이 대응"으로 실패한다.
-- 동작: 같은 키가 테이블에 있으면 score·analyzed_at 갱신, 없으면 추가.
-- review_date 는 Parquet 의 열(date)이다. 폴더 날짜(year/month/day)와 같은 행만 반영한다(둘이 다르면 반영하지 않는다).
-- 주의: 다시 점수화했더니 예전에 있던 속성이 사라진 경우, 그 옛 행은 남는다(MERGE 는 원본에 없는 행을 지우지 않는다) — 작업 지시서의 열린 질문.
MERGE INTO {{database}}.{{table}} AS t
USING (
  SELECT review_id, aspect, score, model_version, analyzed_at, review_date
  FROM (
    SELECT review_id,
           aspect,
           score,
           model_version,
           analyzed_at,
           review_date,
           row_number() OVER (
             PARTITION BY review_id, aspect, model_version, review_date
             ORDER BY analyzed_at DESC
           ) AS rn
    FROM {{database}}.{{staging_table}}
    WHERE year = '{{year}}'
      AND month = '{{month}}'
      AND day = '{{day}}'
      AND model_version = '{{model_version}}'
      AND review_date = CAST(concat(year, '-', month, '-', day) AS date)
  )
  WHERE rn = 1
) AS s
ON  t.review_id     = s.review_id
AND t.aspect        = s.aspect
AND t.model_version = s.model_version
AND t.review_date   = s.review_date
WHEN MATCHED THEN
  UPDATE SET score = s.score, analyzed_at = s.analyzed_at
WHEN NOT MATCHED THEN
  INSERT (review_id, aspect, score, model_version, analyzed_at, review_date)
  VALUES (s.review_id, s.aspect, s.score, s.model_version, s.analyzed_at, s.review_date);
