# 현재 장애 감지 범위와 읽기 전용 점검

기존 Prometheus 경보 7개에 CDC/task 지표 부재와 Prometheus config reload 실패 3개를 추가했다. 지표가 없으면 정상으로 보이지 않게 한다. 이 읽기 점검 도구는 새 exporter·CloudWatch Logs·노드·알림 수신자를 만들지 않는다. 별도 승인된 자동 통보와 RDS CloudWatch 감시는 [NOTIFICATIONS.md](NOTIFICATIONS.md)를 따른다.

| 항목 | 계속 감시하는 기존 Prometheus | readiness.py 실행 시 |
|---|---|---|
| Kafka/Connect/lag scrape 및 CDC 연결·task 상태 | 경보 평가. 추가 3개는 배포 후 적용 | Pod Ready·지표·firing 경보 확인 |
| Kafka PVC 여유 | 수집 미연결 | 확인된 PVC mount의 df 조회, 80% 이상 경고 |
| RDS 백업·남은 공간·WAL | 수집 미연결 | 기존 RDS/CloudWatch 읽기: 2GiB 미만·WAL 예산 75% 이상 경고 |
| S3 도착 | 수집 미연결 | 주문/주문상품/결제 Bronze의 오늘·어제 UTC prefix만 제한 조회 |
| Airflow 업무 성공 | 상시 수집 미연결 | --pipeline에서 기존 scheduler의 메타DB를 읽어 최근 성공·실패·paused를 구분 |
| 외부 통보 | 선택적 Alertmanager→SNS 연결, 이메일 구독 확인 필요 | 전송 없음 |

## 실행

기존 AWS CLI·kubectl 인증을 사용하는 로컬 관리자용이다. 새 IAM 권한을 자동 부여하지 않는다. 대상은 계정 827913617635 / 도쿄 / clothes-query-dev-eks이며 kubeconfig context alias는 기본 clothes-query-dev다. 실제 EKS endpoint를 조회해 대상 주소를 대조하고, 일치하지 않으면 Kubernetes/Prometheus 점검을 중단한다. 다른 context alias이면 --kube-context로 지정한다.

```powershell
python -X utf8 infra/platform/monitoring/readiness.py --live --pipeline --format summary --output .cache/pipeline-status.json

# 기존 인프라 점검만 실행할 때:
python infra/platform/monitoring/readiness.py --live --output .cache/readiness.json
# 생성기를 가동해 새 데이터가 들어와야 할 때만 S3 지연을 경고로 취급한다.
python infra/platform/monitoring/readiness.py --live --expect-ingestion --output .cache/readiness-active-input.json
```

S3 기본 허용 지연은 30분이다. 현재 Sink의 약 15분 파일 묶음 간격을 고려한 초기 운영 기준이며, --s3-max-age-minutes로 변경할 수 있다. 입력을 기대하지 않는 기본 모드에서는 도착 정보를 INFO로 표시한다. 목록은 일별 최대 3페이지(각 1000개)만 읽으며, 오래된 객체만 본 상태에서 조회 한도에 도달하면 UNKNOWN이다. 객체 본문·Secret·업무 행은 읽지 않는다.

도구는 kubectl get, 실제 Kafka PVC의 df, Prometheus query, AWS STS/EKS/RDS/CloudWatch/S3 읽기 API만 사용한다. list/get 요청의 사용량 요금은 있을 수 있지만 새로운 과금 리소스는 만들지 않는다. stdout/보고서에는 상태·지표값과 자원 이름만 기록하고 명령 실패 시 원문 stderr를 노출하지 않는다. 보고서는 Git 제외 .cache에 둔다.

종료 코드: WARN이 있으면 1, WARN 없이 UNKNOWN이 있으면 2, 나머지는 0이다. 현재 업무 DAG 감시는 미연결이므로 AirflowBusinessRuns=UNKNOWN/exit 2가 남는 것이 정상이다. UNKNOWN을 숨기거나 성공으로 바꾸지 않는다. 한 번 실행하는 점검 도구이며 상시 경보 시스템이 아니다.

## 전체 흐름 옵션 --pipeline

같은 계정·실제 EKS endpoint 대조가 통과한 뒤에만 추가 점검을 수행한다. 새 Pod·Job·노드·권한·경보는 만들지 않는다. 기존 API 읽기와 기존 scheduler/collector 안의 읽기 명령만 실행한다.

| 표시 | 의미 |
|---|---|
| OK | 해당 점검 범위에서 정상. 예: Pod Ready, 최근 판정 성공 |
| INFO | 참고 정보. 예: 노드 수, 오류 원장에 오류 파일 없음 |
| WAITING | 미연결·미등록·의도적으로 paused. 정상 동작 완료로 계산하지 않음 |
| UNKNOWN | 권한/접속/지표 부재·오래된 관측·조회 한도 때문에 확인 못 함 |
| WARN | 확인한 실패·압박·기대 출력 지연 |

추가 확인 범위는 노드 Ready/Pressure·실제 CPU/메모리와 Pod 요청량, namespace별 Pod 상태, Connector/Task, 실제 수집기의 v2 대상과 Connect REST 상태, Glue 뷰·#95 컬럼, 원장 Parquet 메타데이터, 판정·조사 최근 성공과 paused, 재처리 DAG 등록 여부다. Glue 정의가 있다는 것과 Athena 실제 쿼리 성공, S3 객체가 있다는 것과 업무 행의 정확성은 다르다.

- 노드 CPU 90%/메모리 85%를 초기 경고값으로 사용하며 각각 --node-cpu-warn-percent/--node-memory-warn-percent로 조정한다. 순간 관측이며 장기 피크 검증이 아니다.
- --ledger-max-age-minutes 기본 3분은 상시 1분 수집기의 신선도 기준이다. Gold B 상시 적재가 없으면 빈 정상 원장은 WAITING, 빈 오류 원장은 INFO다. 적재 Pod가 있고 --expect-ingestion도 지정한 경우에만 payment_events/topic_messages의 신규 출력 지연을 경고한다. 원장별 최대 3페이지/3,000개만 읽으므로 한도에 걸린 오래된 목록은 UNKNOWN이다.
- --gold-b-ingest-prefix 기본 gold-b-ingest는 향후 확정할 Pod 이름의 접두사다. 다른 이름으로 배포하면 반드시 맞춘다. 이름 일치·Pod Ready만으로 checkpoint와 원장 정확성을 검증하지 않는다.
- --dag-max-age-minutes 기본 15분이다. 새 회차 running 중에도 최근 성공을 별도로 확인하며 최신 failed는 WARN이다. paused는 WAITING으로 표시한다. 조사·재처리 DAG를 켜거나 실행하지 않는다.
- 최종 재처리 DAG ID가 달라지면 --reprocess-dags <GoldB-ID> <Silver-ID>로 지정한다. 등록 확인은 승인 입력·완료 이벤트 계약 검증이 아니다.
- 추가로 필요한 기존 권한: Glue GetTables, KafkaConnector/노드/Pod/metrics 읽기, scheduler와 collector의 pods/exec. Secret과 후기/결제 원문은 조회하지 않고, Athena 쿼리·Bedrock 호출·업무 INSERT도 하지 않는다.

--format summary는 한 줄씩 상태를 보여주며 --output 파일은 항상 JSON이다. 보고서는 Git 제외 경로에 저장한다. --pipeline 종료 코드는 WARN=1, WARN 없이 UNKNOWN=2, 둘 없이 WAITING=3, 나머지=0 순이다. 따라서 미배포 서비스가 남은 지금은 exit 3이 나올 수 있다. 기본 옵션만 실행할 때는 기존 UNKNOWN/exit 2 동작을 유지한다.

## 변경 적용

로컬 Helm 렌더·promtool rule/config·가짜 시계열 검사 후 기존 cq-monitoring release의 실제 values를 보존해 변경 범위를 비교한다. 이번 변경은 rules ConfigMap과 그 checksum에 따른 monitoring Deployment 재생성만 허용한다. 이미지·requests/limits·NodePool·PVC·Service/접근 경로는 그대로여야 한다. Recreate이므로 Prometheus/Grafana/Metrics Server가 잠시 중단될 수 있다. 실제 적용 기록은 작업 지시서에 남긴다.

[복구 절차](../../../docs/operations/incident-recovery.md)를 함께 따른다.
