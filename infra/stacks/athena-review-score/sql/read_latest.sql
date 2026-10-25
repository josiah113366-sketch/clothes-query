-- (2026-10-26 변경) 뷰 review_aspect_scores_latest 는 이제 버전 선택을 점수 로그(review_score_log)에서 하고 비교용 모델 버전(기본 2.4b_score_s2r)을 선택에서 뺀다.
--   그래서 새 버전이 속성 0개로 분석한 후기에 옛 버전 점수가 되살아나지 않고, 비교용 모델만 점수를 낸 후기는 뷰에 나오지 않는다.
--   이 파일의 쿼리는 점수 테이블만 보는 단순 예시라 그 두 규칙을 반영하지 않는다. Gold 는 뷰를 읽는다(후기 단위 상태는 review_score_status_latest).
-- 읽기: 후기마다 model_version_no 가 가장 큰 결과만 (Gold 의 읽기 규칙, 2026-10-22 결정).
-- 같은 로직이 Terraform 뷰 review_aspect_scores_latest 로 만들어져 있다(modules/athena-review-score/main.tf). Gold 는 뷰를 읽으면 되고, 이 파일은 테이블을 직접 읽는 하루치 예시다.
-- 자리표시자: {{database}}, {{table}}, {{date}} (YYYY-MM-DD, 후기 작성일 KST)
-- 후기 단위로 가장 높은 번호를 고르고 그 번호의 속성을 전부 가져온다(속성 단위가 아니다).
-- → 새 모델에서 빠진 속성이 옛 모델 결과로 되살아나지 않는다. 번호가 "x.y"(decimal) 라서 1.9 < 2.0 처럼 숫자로 비교된다.
SELECT review_id, aspect, score, model_version, model_version_no, analyzed_at, review_date
FROM (
  SELECT *,
         max(model_version_no) OVER (PARTITION BY review_id) AS max_no
  FROM {{database}}.{{table}}
  WHERE review_date = DATE '{{date}}'
)
WHERE model_version_no = max_no;
