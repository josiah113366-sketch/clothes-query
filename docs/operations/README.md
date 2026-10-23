# 운영·장애 대응

- [현재 단일 노드 구성의 복구 절차](incident-recovery.md): Kafka/CDC/RDS/입력 경로별 보존 대상·확인 순서·복구 한계.
- [장애 점검 실행](../../infra/platform/monitoring/READINESS.md): 기존 Kubernetes·Prometheus·RDS 지표·S3를 읽는 일회성 점검. 정기 수집기·자동 복구·외부 알림은 아님.
