-- 하루치 staging 점수 결과를 Iceberg 점수 테이블에 반영(upsert + 빠진 속성 삭제). 초안 2026-10-22 — 실제 Athena 에서 검증 전.
-- 자리표시자: {{database}}, {{table}}, {{staging_table}}, {{staging_log_table}}, {{year}}, {{month}}, {{day}}, {{model_version}}, {{model_version_no}}
--   year/month/day 는 후기 작성일(KST)이고 두 자리 월·일(예: 2026, 10, 05)이다. 실행한 날이 아니다.
--   model_version_no 는 "x.y" 형식(예: 1.0)이다. 평가 모델/로직이 바뀌면 메이저, 작은 수정이면 마이너를 올린다(마이너 0~9, x.9 다음은 메이저).
--
-- 동작
--   1) upserts    : staging 에서 같은 (review_id, aspect, model_version, review_date) 가 여러 번 있으면 analyzed_at 이 가장 최근인 행만 남긴다
--                   (Job 을 같은 날짜로 다시 실행하면 실행시각이 들어간 새 파일이 쌓이기 때문). 이렇게 하지 않으면 MERGE 가 "한 행에 여러 행이 대응"으로 실패한다.
--   2) batch      : 이번 배치에 들어온 review_id 모음 = 점수 행이 있는 후기 + 점수 로그에만 있는 후기(속성이 0개가 된 후기).
--   3) tombstones : 같은 model_version 의 기존 테이블 행 중, review_id 는 이번 배치에 있는데 aspect 는 새 결과에 없는 행 = 지울 행(is_delete = true).
--                   → 다시 점수화했더니 빠진 속성이 삭제된다. 이번 배치에 없는 후기는 건드리지 않는다.
--   4) MERGE      : 키가 같으면 갱신(is_delete 면 삭제), 없으면 추가(삭제 표시 행은 추가하지 않는다).
-- 키는 review_id + aspect + model_version(+ review_date). model_version(이름)과 model_version_no(번호)는 1:1 이라 키에는 이름을 쓰고 번호는 값으로 둔다
--   (번호 열이 없던 옛 행도 같은 키로 이어 붙을 수 있도록. 옛 staging 파일에 번호가 없으면 {{model_version_no}} 로 채운다).
-- 미검증(첫 실행에서 확인): ① MERGE ... USING (WITH ...) 형태, ② WHEN MATCHED AND <조건> / WHEN NOT MATCHED AND <조건>, ③ 대상 테이블을 USING 쿼리에서 읽는 것.
MERGE INTO {{database}}.{{table}} AS t
USING (
  WITH ranked AS (
    SELECT review_id,
           aspect,
           score,
           model_version,
           COALESCE(model_version_no, CAST('{{model_version_no}}' AS decimal(4, 1))) AS model_version_no,
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
  ),
  upserts AS (
    SELECT review_id, aspect, score, model_version, model_version_no, analyzed_at, review_date, false AS is_delete
    FROM ranked
    WHERE rn = 1
  ),
  batch AS (
    SELECT review_id FROM upserts
    UNION
    SELECT review_id
    FROM {{database}}.{{staging_log_table}}
    WHERE year = '{{year}}'
      AND month = '{{month}}'
      AND day = '{{day}}'
      AND model_version = '{{model_version}}'
  ),
  tombstones AS (
    SELECT t0.review_id, t0.aspect, t0.score, t0.model_version, t0.model_version_no, t0.analyzed_at, t0.review_date, true AS is_delete
    FROM {{database}}.{{table}} t0
    JOIN batch b ON t0.review_id = b.review_id
    LEFT JOIN upserts u
      ON u.review_id = t0.review_id AND u.aspect = t0.aspect AND u.model_version = t0.model_version
    WHERE t0.review_date = CAST(concat('{{year}}', '-', '{{month}}', '-', '{{day}}') AS date)
      AND t0.model_version = '{{model_version}}'
      AND u.aspect IS NULL
  )
  SELECT * FROM upserts
  UNION ALL
  SELECT * FROM tombstones
) AS s
ON  t.review_id     = s.review_id
AND t.aspect        = s.aspect
AND t.model_version = s.model_version
AND t.review_date   = s.review_date
WHEN MATCHED AND s.is_delete THEN
  DELETE
WHEN MATCHED THEN
  UPDATE SET score = s.score, model_version_no = s.model_version_no, analyzed_at = s.analyzed_at
WHEN NOT MATCHED AND NOT s.is_delete THEN
  INSERT (review_id, aspect, score, model_version, model_version_no, analyzed_at, review_date)
  VALUES (s.review_id, s.aspect, s.score, s.model_version, s.model_version_no, s.analyzed_at, s.review_date);
