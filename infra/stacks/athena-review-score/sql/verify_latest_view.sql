-- 새 읽기 뷰 적용 후 확인 (읽기 전용, 2026-10-26)
-- 목적: review_aspect_scores_latest(로그 기준 버전 선택, 비교용 제외)와 review_score_status_latest 가 의도대로 나오는지 본다.
-- 실행: Athena 워크그룹 clothes-query-dev-athena-review-score. 쿼리는 "-- @q" 줄로 나뉜다. apply 후 lemin 이 돌린다.
-- 원문(text)은 읽지 않는다. 결과는 건수만 나온다.
-- 표: v = review_aspect_scores_latest(뷰), t = review_aspect_scores(원본), l = review_score_log, st = review_score_status_latest(뷰)

-- @q1 (a) 새 latest 뷰의 행 수 · 고유 후기 수 — 점수 테이블 s2c 기준(30,048행, 18,514 후기)과 같아야 한다
SELECT count(*) AS score_rows, count(DISTINCT review_id) AS reviews
FROM clothes_query_dev_review_score.review_aspect_scores_latest;

-- @q1b 같은 기준값: 점수 테이블의 s2c 행 수 · 후기 수
SELECT count(*) AS score_rows, count(DISTINCT review_id) AS reviews
FROM clothes_query_dev_review_score.review_aspect_scores
WHERE model_version = '2.4b_score_s2c';

-- @q2 (b) 후기당 버전 수가 2 이상인 후기 수 — 0 이어야 한다
SELECT count(*) AS reviews_with_multiple_versions
FROM (
  SELECT review_id, review_date
  FROM clothes_query_dev_review_score.review_aspect_scores_latest
  GROUP BY review_id, review_date
  HAVING count(DISTINCT model_version_no) > 1
);

-- @q3 뷰에 비교용 모델(2.4b_score_s2r)이 섞였는지 — 0 행이어야 한다
SELECT model_version, count(*) AS score_rows, count(DISTINCT review_id) AS reviews
FROM clothes_query_dev_review_score.review_aspect_scores_latest
WHERE model_version = '2.4b_score_s2r'
GROUP BY model_version;

-- @q4 (c) status 뷰의 점수있음 / 속성없음 건수 (후기 수)
SELECT score_status, model_version, count(*) AS reviews
FROM clothes_query_dev_review_score.review_score_status_latest
GROUP BY score_status, model_version
ORDER BY score_status, model_version;

-- @q5 status 뷰는 후기당 한 행이어야 한다 — 0 이어야 한다
SELECT count(*) AS duplicated_reviews
FROM (
  SELECT review_id, review_date
  FROM clothes_query_dev_review_score.review_score_status_latest
  GROUP BY review_id, review_date
  HAVING count(*) > 1
);

-- @q6 두 뷰의 일관성: status 가 '점수있음'인 후기는 latest 뷰에 있고 '속성없음'인 후기는 없어야 한다 — 두 값 모두 0 이어야 한다
SELECT
  count_if(st.score_status = '점수있음' AND v.review_id IS NULL) AS scored_but_missing_in_latest,
  count_if(st.score_status = '속성없음' AND v.review_id IS NOT NULL) AS no_aspect_but_in_latest
FROM clothes_query_dev_review_score.review_score_status_latest st
LEFT JOIN (
  SELECT DISTINCT review_id, review_date
  FROM clothes_query_dev_review_score.review_aspect_scores_latest
) v
  ON st.review_id = v.review_id AND st.review_date = v.review_date;
