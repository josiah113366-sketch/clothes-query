-- 한 번만 실행하는 이전(migration): 기존 점수 테이블에 model_version_no 열을 추가하고 값을 채운다. 초안 2026-10-22 — 실제 Athena 에서 검증 전.
-- 왜 필요한가: 점수 테이블은 이미 만들어졌고 Terraform 이 ignore_changes 로 스키마 변경을 적용하지 않는다(스키마 변경은 Athena ALTER TABLE).
--   새로 만들어지는 review_score_log 테이블은 처음부터 이 열이 있어서 이전이 필요 없다.
-- 자리표시자: {{database}}, {{table}}, {{log_table}}, {{model_version}}, {{model_version_no}}  (현재 값: 2.4b_score_s2c, 1.0)
-- 아래 문장을 하나씩 순서대로 실행한다(각각 별도 쿼리).

-- 1) 열 추가 (이미 있으면 오류가 나므로 두 번 실행하지 않는다)
ALTER TABLE {{database}}.{{table}} ADD COLUMNS (model_version_no decimal(4, 1));

-- 2) 기존 행 채우기: 지금까지의 모든 행은 2.4b_score_s2c = 1.0
UPDATE {{database}}.{{table}}
SET model_version_no = CAST('{{model_version_no}}' AS decimal(4, 1))
WHERE model_version = '{{model_version}}' AND model_version_no IS NULL;

-- 3) 확인: model_version_no 가 비어 있는 행이 없어야 한다
SELECT model_version, model_version_no, count(*) AS n
FROM {{database}}.{{table}}
GROUP BY 1, 2
ORDER BY 1, 2;

-- 4) 점수 로그 채우기(한 번만): 새 로그 테이블이 비어 있으면 이미 점수가 있는 후기까지 "미점수"로 보여 다시 점수화된다.
--    기존 점수 테이블에서 후기별 한 행을 만들어 넣는다. (속성이 0개였던 후기는 점수 행이 없어 여기서 만들 수 없다 → 한 번 다시 점수화되고 그때부터 로그에 남는다)
INSERT INTO {{database}}.{{log_table}}
SELECT review_id, model_version, model_version_no, max(analyzed_at), review_date, CAST(count(*) AS integer)
FROM {{database}}.{{table}}
GROUP BY review_id, model_version, model_version_no, review_date;
