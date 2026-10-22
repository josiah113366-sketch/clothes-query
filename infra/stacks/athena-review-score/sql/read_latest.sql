-- 읽기 예시: 후기마다 가장 최근에 분석한 모델 버전의 결과만. 초안 2026-10-22 — 실제 Athena 에서 검증 전.
-- Gold 가 "최신 버전만 읽기" 규칙을 쓸 때의 한 방법이다(규칙 자체는 작업 지시서의 열린 질문).
-- 자리표시자: {{database}}, {{table}}, {{date}} (YYYY-MM-DD, 후기 작성일 KST)
SELECT review_id, aspect, score, model_version, analyzed_at
FROM (
  SELECT *,
         row_number() OVER (PARTITION BY review_id, aspect ORDER BY analyzed_at DESC) AS rn
  FROM {{database}}.{{table}}
  WHERE review_date = DATE '{{date}}'
)
WHERE rn = 1;
