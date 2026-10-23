# 현재 장애 감지 범위와 읽기 전용 점검

기존 Prometheus 경보 7개에 CDC/task 지표 부재와 Prometheus config reload 실패 3개를 추가했다. 지표가 없으면 정상으로 보이지 않게 한다. 이 읽기 점검 도구는 새 exporter·CloudWatch Logs·노드·알림 수신자를 만들지 않는다. 별도 승인된 자동 통보와 RDS CloudWatch 감시는 [NOTIFICATIONS.md](NOTIFICATIONS.md)를 따른다.

| 항목 | 계속 감시하는 기존 Prometheus | readiness.py 실행 시 |
|---|---|---|
| Kafka/Connect/lag scrape 및 CDC 연결·task 상태 | 경보 평가. 추가 3개는 배포 후 적용 | Pod Ready·지표·firing 경보 확인 |
| Kafka PVC 여유 | 수집 미연결 | 확인된 PVC mount의 df 조회, 80% 이상 경고 |
| RDS 백업·남은 공간·WAL | 수집 미연결 | 기존 RDS/CloudWatch 읽기: 2GiB 미만·WAL 예산 75% 이상 경고 |
| S3 도착 | 수집 미연결 | 주문/주문상품/결제 Bronze의 오늘·어제 UTC prefix만 제한 조회 |
| Airflow 업무 성공 | 수집 미연결 | UNKNOWN으로 표시. Pod Ready와 업무 성공을 구분 |
| 외부 통보 | 선택적 Alertmanager→SNS 연결, 이메일 구독 확인 필요 | 전송 없음 |

## 실행

기존 AWS CLI·kubectl 인증을 사용하는 로컬 관리자용이다. 새 IAM 권한을 자동 부여하지 않는다. 대상은 계정 827913617635 / 도쿄 / clothes-query-dev-eks이며 kubeconfig context alias는 기본 clothes-query-dev다. 실제 EKS endpoint를 조회해 대상 주소를 대조하고, 일치하지 않으면 Kubernetes/Prometheus 점검을 중단한다. 다른 context alias이면 --kube-context로 지정한다.

```powershell
python infra/platform/monitoring/readiness.py --live --output .cache/readiness.json
# 생성기를 가동해 새 데이터가 들어와야 할 때만 S3 지연을 경고로 취급한다.
python infra/platform/monitoring/readiness.py --live --expect-ingestion --output .cache/readiness-active-input.json
```

S3 기본 허용 지연은 30분이다. 현재 Sink의 약 15분 파일 묶음 간격을 고려한 초기 운영 기준이며, --s3-max-age-minutes로 변경할 수 있다. 입력을 기대하지 않는 기본 모드에서는 도착 정보를 INFO로 표시한다. 목록은 일별 최대 3페이지(각 1000개)만 읽으며, 오래된 객체만 본 상태에서 조회 한도에 도달하면 UNKNOWN이다. 객체 본문·Secret·업무 행은 읽지 않는다.

도구는 kubectl get, 실제 Kafka PVC의 df, Prometheus query, AWS STS/EKS/RDS/CloudWatch/S3 읽기 API만 사용한다. list/get 요청의 사용량 요금은 있을 수 있지만 새로운 과금 리소스는 만들지 않는다. stdout/보고서에는 상태·지표값과 자원 이름만 기록하고 명령 실패 시 원문 stderr를 노출하지 않는다. 보고서는 Git 제외 .cache에 둔다.

종료 코드: WARN이 있으면 1, WARN 없이 UNKNOWN이 있으면 2, 나머지는 0이다. 현재 업무 DAG 감시는 미연결이므로 AirflowBusinessRuns=UNKNOWN/exit 2가 남는 것이 정상이다. UNKNOWN을 숨기거나 성공으로 바꾸지 않는다. 한 번 실행하는 점검 도구이며 상시 경보 시스템이 아니다.

## 변경 적용

로컬 Helm 렌더·promtool rule/config·가짜 시계열 검사 후 기존 cq-monitoring release의 실제 values를 보존해 변경 범위를 비교한다. 이번 변경은 rules ConfigMap과 그 checksum에 따른 monitoring Deployment 재생성만 허용한다. 이미지·requests/limits·NodePool·PVC·Service/접근 경로는 그대로여야 한다. Recreate이므로 Prometheus/Grafana/Metrics Server가 잠시 중단될 수 있다. 실제 적용 기록은 작업 지시서에 남긴다.

[복구 절차](../../../docs/operations/incident-recovery.md)를 함께 따른다.
