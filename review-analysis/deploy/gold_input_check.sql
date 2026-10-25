-- Gold A 리뷰 점수 입력 검증 (읽기 전용, 2026-10-25)
-- 목적: 재채점 없이 기존 점수를 Gold A 에 쓸 수 있는지, 완료 Silver 실행과 review_id 로 맞물리는지 확인한다.
-- 실행: Athena 워크그룹 clothes-query-dev-athena-review-score. 쿼리는 "-- @q" 줄로 나뉜다. {{run_id}} 를 Silver 실행 ID 로 바꾼다.
-- 시점: 점수 채점 루프가 끝난 뒤(점수가 더 바뀌지 않을 때) 돌리고, 쿼리마다 조회 시각(UTC)과 QueryExecutionId 를 남긴다.
-- 원문(text)·주문/상품 식별 열은 읽지 않는다. 결과는 건수만 나온다.
-- 표: s = review_aspect_scores_latest(뷰, Gold 입력), t = review_aspect_scores(원본 Iceberg), l = review_score_log(후기별 로그),
--     v = silver_reviews_runs(완료 Silver 의 정상 후기만. 격리 후기는 별도 파일이라 여기 없다)

-- @q1 뷰 점수 행 수 · 고유 후기 수 · 작성일 범위
SELECT count(*) AS score_rows, count(DISTINCT review_id) AS reviews,
       min(review_date) AS min_review_date, max(review_date) AS max_review_date
FROM clothes_query_dev_review_score.review_aspect_scores_latest;

-- @q2 모델 버전별 행 수 · 후기 수 (원본 테이블 = 뷰가 고르기 전, 뷰 = Gold 가 받는 것)
SELECT 'table' AS src, model_version, CAST(model_version_no AS varchar) AS model_version_no,
       count(*) AS score_rows, count(DISTINCT review_id) AS reviews
FROM clothes_query_dev_review_score.review_aspect_scores GROUP BY 2, 3
UNION ALL
SELECT 'view', model_version, CAST(model_version_no AS varchar), count(*), count(DISTINCT review_id)
FROM clothes_query_dev_review_score.review_aspect_scores_latest GROUP BY 2, 3
ORDER BY 1, 3;

-- @q3 Silver 연결: 점수 연결 후기 / 점수 없는 Silver 후기 / Silver 밖 점수 후기
WITH v AS (SELECT DISTINCT review_id FROM clothes_query_dev_review_score.silver_reviews_runs WHERE run_id = '{{run_id}}'),
     s AS (SELECT DISTINCT review_id FROM clothes_query_dev_review_score.review_aspect_scores_latest)
SELECT (SELECT count(*) FROM v)                                                     AS silver_reviews,
       (SELECT count(*) FROM v JOIN s USING (review_id))                             AS linked_reviews,
       (SELECT count(*) FROM v WHERE NOT EXISTS (SELECT 1 FROM s WHERE s.review_id = v.review_id)) AS silver_without_score,
       (SELECT count(*) FROM s WHERE NOT EXISTS (SELECT 1 FROM v WHERE v.review_id = s.review_id)) AS score_outside_silver;

-- @q4 Silver 후기의 점수 상태(로그 기준): 점수있음 / 속성없음(n_aspects=0) / 미분석(로그 없음, 파싱 실패 포함)
WITH v AS (SELECT review_id, review_date_kst FROM clothes_query_dev_review_score.silver_reviews_runs WHERE run_id = '{{run_id}}'),
     l AS (SELECT review_id, max_by(n_aspects, model_version_no) AS n_aspects
           FROM clothes_query_dev_review_score.review_score_log GROUP BY review_id)
SELECT CASE WHEN l.review_id IS NULL THEN '미분석' WHEN l.n_aspects = 0 THEN '속성없음' ELSE '점수있음' END AS status,
       count(*) AS reviews
FROM v LEFT JOIN l ON v.review_id = l.review_id
GROUP BY 1 ORDER BY 1;

-- @q4b 로그·점수 정합성: 로그(n_aspects>0)는 있는데 점수 행이 없는 (후기,버전) · 점수 행은 있는데 로그가 없는 (후기,버전)
--      · Silver 밖 점수의 작성일 범위(10/21~22 Bronze 시험분인지 보기 위함)
WITH l AS (SELECT DISTINCT review_id, model_version, n_aspects FROM clothes_query_dev_review_score.review_score_log),
     t AS (SELECT DISTINCT review_id, model_version, review_date FROM clothes_query_dev_review_score.review_aspect_scores),
     v AS (SELECT DISTINCT review_id FROM clothes_query_dev_review_score.silver_reviews_runs WHERE run_id = '{{run_id}}')
SELECT (SELECT count(*) FROM l WHERE l.n_aspects > 0 AND NOT EXISTS
          (SELECT 1 FROM t WHERE t.review_id = l.review_id AND t.model_version = l.model_version))  AS log_without_scores,
       (SELECT count(*) FROM t WHERE NOT EXISTS
          (SELECT 1 FROM l WHERE l.review_id = t.review_id AND l.model_version = t.model_version))  AS scores_without_log,
       (SELECT min(review_date) FROM t WHERE NOT EXISTS (SELECT 1 FROM v WHERE v.review_id = t.review_id)) AS outside_min_date,
       (SELECT max(review_date) FROM t WHERE NOT EXISTS (SELECT 1 FROM v WHERE v.review_id = t.review_id)) AS outside_max_date;

-- @q5 같은 (후기, 속성, 버전)의 정확한 중복 · 점수 충돌 (원본 테이블)
SELECT count(*) AS dup_keys,
       count_if(n_scores > 1) AS conflicting_keys,
       count_if(n_rows > n_scores) AS exact_dup_keys
FROM (SELECT review_id, aspect, model_version, count(*) AS n_rows, count(DISTINCT score) AS n_scores
      FROM clothes_query_dev_review_score.review_aspect_scores
      GROUP BY 1, 2, 3 HAVING count(*) > 1);

-- @q6 버전 혼재: 뷰에서 후기 하나에 버전 2개 이상(0이어야 함) · 원본에서 2개 이상 버전이 있는 후기 · 뷰 전체의 버전 종류 수
SELECT (SELECT count(*) FROM (SELECT review_id FROM clothes_query_dev_review_score.review_aspect_scores_latest
         GROUP BY 1 HAVING count(DISTINCT model_version) > 1))                               AS view_reviews_multi_version,
       (SELECT count(*) FROM (SELECT review_id FROM clothes_query_dev_review_score.review_aspect_scores
         GROUP BY 1 HAVING count(DISTINCT model_version) > 1))                               AS table_reviews_multi_version,
       (SELECT count(DISTINCT model_version) FROM clothes_query_dev_review_score.review_aspect_scores_latest) AS view_versions;

-- @q7 KST 작성일 불일치: 점수의 review_date 와 Silver 의 review_date_kst · 후기 하나에 review_date 2개 이상
WITH v AS (SELECT review_id, review_date_kst FROM clothes_query_dev_review_score.silver_reviews_runs WHERE run_id = '{{run_id}}'),
     s AS (SELECT DISTINCT review_id, review_date FROM clothes_query_dev_review_score.review_aspect_scores_latest)
SELECT count_if(s.review_date <> v.review_date_kst) AS date_mismatch_reviews,
       count(*) AS compared_reviews,
       (SELECT count(*) FROM (SELECT review_id FROM s GROUP BY 1 HAVING count(*) > 1)) AS reviews_multi_date,
       (SELECT count(*) FROM (SELECT review_id FROM v GROUP BY 1 HAVING count(*) > 1)) AS silver_dup_review_id
FROM s JOIN v ON s.review_id = v.review_id;

-- @q8 속성 목록 밖 값 · 점수 범위 밖 값 · 속성별 분포 (뷰)
SELECT aspect,
       count(*) AS score_rows,
       count_if(score NOT BETWEEN -2 AND 2) AS out_of_range,
       count_if(score = -2) AS m2, count_if(score = -1) AS m1, count_if(score = 0) AS z0,
       count_if(score = 1) AS p1, count_if(score = 2) AS p2,
       aspect NOT IN ('재질·촉감','사이즈·핏','색상·디자인','품질·내구성','가격·가성비','냄새','세탁·관리','활용성·사용감','배송','포장','교환·환불·CS') AS unknown_aspect
FROM clothes_query_dev_review_score.review_aspect_scores_latest
GROUP BY aspect ORDER BY score_rows DESC;
