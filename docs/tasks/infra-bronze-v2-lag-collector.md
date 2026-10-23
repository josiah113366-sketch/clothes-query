# Bronze v2 지연 수집기 배포

상태: AWS·EKS 적용 및 실제 수집 검증 완료 (2026-10-23)

브랜치: infra/bronze-v2-lag-collector

사용자가 측정 대상으로 v2를 지정했다. main 3a4e17c 기준 기존 collector 코드를 수정하지 않고 이미지·권한·네트워크·Pod 배포를 준비한다. Spark·새 노드는 만들지 않는다. 기존 API 노드의 예약 여유 680m/1331Mi를 확인했으며 수집기 요청은 25m/128Mi다.

전용 ECR·Pod Identity/S3 역할을 독립 Terraform key에서 관리한다. KafkaUser는 토픽 Read/Describe 및 v2 Sink 그룹 Describe만 허용해 Sink 처리 위치를 바꿀 수 없게 한다. 수집기 라벨/namespace만 기존 broker 9093 및 Connect 8083에 접근할 수 있게 추가 NetworkPolicy로 연결한다. broker/Connect CR은 변경하지 않아 재시작을 피한다.

## 작업 결과

렌더/권한 경계 검사 4개와 Terraform mock 1개, validate를 통과했다. 실제 plan은 ECR·IAM 역할·쓰기 정책·Pod Identity 4개 create뿐이었고 삭제·교체는 없다. 공용 provider 캐시를 재사용해 init했다.

승인된 v2 연결 범위에서 해당 저장 계획과 전용 KafkaUser/추가 NetworkPolicy 3개를 서버 dry-run 후 적용했다. 기존 Kafka/Connect CR은 변경하지 않았다. 사용자 Ready·생성 TLS Secret의 pipelines 복사 일치와 적용 후 Terraform 변경 없음을 확인했다. 인증서/키는 출력하거나 Git에 넣지 않았다.

## 실제 배포·검증

소스 커밋 `9e2fe98abc8f1a71c11c050acae3043b94a9f9ba`를 linux/amd64로 빌드했다. 네트워크 없이 UID 10001·읽기 전용 파일시스템에서 CLI와 로컬 Parquet 왕복을 검증했다. Python 3.12 / confluent-kafka 2.16.0 / PyArrow 26.0.0 / boto3 1.43.116을 확인했다. 기존 Spark 이미지·버전은 변경하지 않았다.

발행 이미지:
`827913617635.dkr.ecr.ap-northeast-1.amazonaws.com/clothes-query-dev/gold-b-lag-collector@sha256:fd040c0a05843c730ff62b4294edb7a851dd8afe6ec905a3cdc8fb77572d694f`

ECR manifest/config digest가 로컬 검증 이미지와 일치한다. 임시 ECR 로그인 파일은 로그아웃 후 제거했다. 전용 ServiceAccount·ConfigMap·Deployment 3개만 서버 dry-run 후 적용했다. `pipelines/gold-b-lag-collector` Deployment 1개가 기존 API 노드에서 `--interval 60`으로 실행된다.

2026-10-23 19:21:01 / 19:22:01 KST 두 측정이 정확히 60초 간격으로 쌓였다. 각 측정은 5개 토픽·15개 파티션이며 connector_state는 모두 RUNNING, committed_offset 누락은 0개였다. Athena `gold_b.bronze_lag_snapshots` 조회에서 최신 기록은 확인 시점 기준 27.55초 전이었다. 현재 UTC 날짜/시간 파티션만 조회했고 스캔량은 1,014 bytes다. S3의 실제 최신 Parquet도 별도로 읽어 15행·5개 토픽·RUNNING을 대조했다.

Kafka·Connect Pod UID와 restartCount, 전체 노드 UID가 배포 전과 같았다. 새 노드·Spark·업무 이벤트·더미 장부는 만들지 않았다. 실제 운영 측정 기록은 유지한다. 수집기 restartCount=0, 초기 측정 사용량은 CPU 0m(반올림)/메모리 58Mi였다. 요청 25m/128Mi, 제한 250m/384Mi는 유지하며 장기 사용량은 후속 관찰한다.

IAM 시뮬레이션 5개로 측정 prefix PutObject만 허용되고 해당 객체 읽기·삭제, payment_events 쓰기, ground_truth 읽기가 거부됨을 확인했다. 실제 S3 저장 성공으로 Pod Identity 경로도 확인했다. v2 Sink 그룹은 Describe만, 임시 측정 그룹만 Read가 있으므로 Sink offset을 커밋하지 않는다.

TLS 복사본과 원본 사용자 인증서·키가 일치하며 사용자 인증서 만료는 2027-10-23 08:54:24 UTC다. Strimzi 인증서 갱신 후에는 복사본 갱신과 수집기 재시작이 필요하다. 자동 인증서 복사·장기 수집기 신선도 알림은 이번 작업에서 추가하지 않았다. Running만으로 정상 판정하지 않고 최근 측정 시간과 R3 측정 누락 기준을 확인한다.

이 배포는 Bronze v2 지연 수집기이며 Gold B 상시 Spark 적재 잡 배포는 별개다. Git push·PR·승인·머지는 별도 요청 전 하지 않는다.
