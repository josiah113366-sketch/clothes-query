# 운영·장애 대응

- [현재 공유 노드 구성의 복구 절차](incident-recovery.md): 증상별 첫 확인·복구 완료 기준, Kafka/CDC/RDS/입력 경로별 보존 대상과 한계.
- [장애 점검 실행](../../infra/platform/monitoring/READINESS.md): 기존 Kubernetes·Prometheus·RDS 지표·S3를 읽는 일회성 점검. 정기 수집기·자동 복구·외부 알림은 아님.
- [이메일 장애 알림](../../infra/platform/monitoring/NOTIFICATIONS.md): Kafka·CDC 경보 전달과 EKS 외부의 RDS CloudWatch 경보. 이메일 확인 및 감시 공백을 별도로 확인한다.
- [최근 실제 연결 검증](runtime-verification-20261024.md): #95 배포·노드 통합 후 확인 및 업무 입력 대기 목록.
- [인프라 Git 공유 준비](infrastructure-share-review.md): 변경 묶음·검증 결과·기존 draft PR 처리안과 PR 본문 초안.
- [담당자별 전달문](team-requests-20261024.md): 바로 전달할 수 있는 진행 상황과 필요한 실행 명세. 실제 메시지는 보내지 않음.
