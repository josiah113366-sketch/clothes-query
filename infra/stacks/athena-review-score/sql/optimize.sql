-- 작은 파일 합치기 (정기 유지보수, 예: 주 1회). 초안 2026-10-22 — 실제 Athena 에서 검증 전.
-- 자리표시자: {{database}}, {{table}}, {{since}} (YYYY-MM-DD, 이 날짜 이후 파티션만 합친다 — 스캔량·비용 절약)
-- MERGE 를 자주 하면 작은 파일이 쌓여 읽기가 느려지고 비용이 늘어난다.
OPTIMIZE {{database}}.{{table}} REWRITE DATA USING BIN_PACK
WHERE review_date >= DATE '{{since}}';
