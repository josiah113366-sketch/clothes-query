-- 하루치 staging 결과를 Iceberg 테이블에 반영(upsert). 초안 2026-10-22 — 실제 Athena 에서 검증 전.
-- 자리표시자: {{database}}, {{table}}, {{staging_table}}, {{year}}, {{month}}, {{day}}, {{model_version}}
--   year/month/day 는 후기 작성일(KST)이고 두 자리 월·일(예: 2026, 10, 05)이다. 실행한 날이 아니다.
-- 동작: 같은 (review_id, aspect, model_version, review_date) 가 있으면 score·analyzed_at 갱신, 없으면 추가.
-- 주의:
--   * 원본(staging)에 같은 키가 두 번 있으면 MERGE 가 실패한다(한 행에 여러 행이 대응). 같은 날짜·버전 파일은 덮어써지므로 보통 없다.
--   * 다시 점수화했더니 예전에 있던 속성이 사라진 경우, 그 옛 행은 남는다(MERGE 는 원본에 없는 행을 지우지 않는다) — 작업 지시서의 열린 질문.
MERGE INTO {{database}}.{{table}} AS t
USING (
  SELECT review_id,
         aspect,
         score,
         model_version,
         analyzed_at,
         CAST(concat(year, '-', month, '-', day) AS date) AS review_date
  FROM {{database}}.{{staging_table}}
  WHERE year = '{{year}}'
    AND month = '{{month}}'
    AND day = '{{day}}'
    AND model_version = '{{model_version}}'
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
