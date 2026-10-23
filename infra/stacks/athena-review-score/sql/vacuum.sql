-- 오래된 스냅샷과 더 이상 참조되지 않는 파일 삭제 (정기 유지보수, 예: OPTIMIZE 뒤). 초안 2026-10-22 — 실제 Athena 에서 검증 전.
-- 자리표시자: {{database}}, {{table}}
-- 보존 기준은 Iceberg 테이블 속성 vacuum_max_snapshot_age_seconds / vacuum_min_snapshots_to_keep 이다(modules/athena-review-score 의 테이블 정의).
-- 안 하면 S3 에 옛 파일과 메타데이터가 계속 쌓인다. 실행 역할에 s3:DeleteObject (테이블 prefix) 가 있어야 한다.
VACUUM {{database}}.{{table}};
