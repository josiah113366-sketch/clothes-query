# Gold B 이미지와 체크포인트 연결

상태: 2026-10-24 이미지·권한·실행 설정 연결, 실제 EKS/S3 단독 적재와 정상 재시작 검증 완료. 시험 실행은 종료했고 Spark 노드 0대로 복귀했다. 상시 운영은 시작하지 않았다.

## 확정 항목

- 업무 이미지: `827913617635.dkr.ecr.ap-northeast-1.amazonaws.com/clothes-query-dev/gold-b@sha256:2a8acd10a157171c0663dcb7bce95b0947c446bbca2219392fcef83c55e308e3`
- 기준 커밋: `7d5ebd16c98ddb53eb2df30c2ac651c71f5bcaf4`. 도쿄 ECR 존재·태그 일치뿐 아니라 실제 실행에서 CODE_REF와 Spark 4.2.0·Python 3.10.12를 확인했다.
- 체크포인트: `s3a://clothes-query-datalake/gold_b/_checkpoints/streaming_ingest/`. 사용자가 제안 경로를 확정했다.

## 적용 범위

공유 `workload-access/deployment.auto.tfvars.json`의 `gold-b-ingest-driver`·`gold-b-ingest-executor` 두 binding에 체크포인트 prefix를 추가했다. 해당 객체 범위의 GetObject·PutObject·DeleteObject·AbortMultipartUpload·ListMultipartUploadParts와 prefix 조건의 ListBucket을 허용한다. 기존 원장 접근을 유지하고 다른 체크포인트·정답표·원장 삭제 권한은 넓히지 않는다. 재처리 역할은 이 체크포인트 권한을 받지 않는다.

최신 origin/main 포함을 확인한 뒤 Terraform fmt·validate·plan을 실행했다. 계획은 IAM inline policy 2개 update뿐이며 create/delete/노드/역할/Pod Identity 변경은 없었다. 같은 저장 계획을 적용했고 후속 plan 변경 0을 확인했다.

실제 두 역할에 대한 IAM 시뮬레이션에서 객체 권한 40개와 checkpoint ListBucket 2개를 확인했다. checkpoint 하위 객체 접근은 허용, 다른 checkpoint와 ground_truth 접근은 거부, 기존 원장 Get/Put은 허용하고 Delete·multipart 정리는 거부됐다. S3 객체를 생성·삭제한 시험은 아니다.

준비 도구는 명시한 checkpoint prefix를 권한 입력과 `GOLD_B_CHECKPOINT` 양쪽에 반영하도록 보완했다. 미지정 기본값은 계속 null이며 허용되지 않는 경로는 거부한다. 기존 Gold B 준비 테스트 7개가 통과했다.

## 실제 시험과 권한 보완

첫 시도는 S3A의 `getFileStatus`가 끝 `/`를 뺀 체크포인트 경로 자체를 HEAD하면서 403으로 종료했다. 원장·checkpoint 객체는 생기지 않았다. 제출기는 0으로 끝났지만 Driver는 1이므로 실패로 기록했다.

공용 IAM 모듈에 선택 항목 `s3_directory_reads`를 추가하고 적재 역할 두 개에 정확한 checkpoint 경로의 GetObject·동일 값의 ListBucket 조건만 추가했다. 부모·형제 경로와 정답표 접근은 늘리지 않았다. 계획은 해당 inline policy 2개 update뿐이었으며 적용 후 plan 변경 0을 확인했다. 전체 Terraform 24개 root·23개 mock suite의 105개 plan 검사와 준비 도구 7개 테스트가 통과했다.

기존 원장·checkpoint가 비었고 다른 Spark 작업이 없음을 확인한 뒤 전용 t3a.large 한 대에서 시험했다. Driver 350m/2GiB, Executor 1개 500m/1.25GiB, 제출기 100m/256MiB request를 사용했다. 기존 Silver·Gold A 설정은 변경하지 않았다. 실제 업무 이미지의 처리 함수를 호출하는 `validate_ingest.py`로 스트림 수명만 제한했다. 더미 메시지를 만들거나 Kafka·원장을 수정해 오류를 주입하지 않았다.

| 항목 | 첫 성공 실행 | 같은 checkpoint 재시작 |
|---|---|---|
| 배치 ID | 0, 1 | 2 |
| 읽은 메시지 | 39,981 | 19,991 |
| 메시지 원장 누적 | 39,981 | 59,972 |
| 결제 원장 누적 | 316 | 474 |
| 오류 원장 누적 | 0 | 0 |
| 메시지 위치 중복 | 0 | 0 |
| Driver·Executor·제출기 종료 코드 | 모두 0 | 모두 0 |

체크포인트 query ID 유지, commits 0·1·2 존재, 재시작 배치의 시작 offset과 직전 종료 offset 일치를 확인했다. 최종 Athena 메시지 건수는 세 성공 배치의 실제 입력 합계와 일치했다. 재시작 Driver의 STS 신원도 전용 `gold-b-ingest-driver` 역할로 확인했다. 존재하는 5개 토픽·15개 파티션에서 읽었고 `reviews.raw`가 없는 상태도 패턴 구독으로 통과했다.

재시작 도중 한 시점의 사용량은 Driver 671m/539Mi, Executor 478m/361Mi, 제출기 3m/289Mi였다. 최대 사용량이나 장시간 메모리 안정성을 측정한 값이 아니며 이 값으로 예약량을 더 낮추지 않았다.

## 설정 연결과 정리

- `pipelines/gold-b-ingest-runtime`에 확정 이미지·checkpoint 환경변수와 `ingest.config.json`을 반영했다. 시험용 script·배치 제한·Pod deadline은 제거하고 원래 template을 복원했다.
- `airflow/airflow-gold-b-runtime`의 `config`를 `AIRFLOW_GOLD_B_RUNTIME`으로 연결했다. 같은 Helm/Airflow 버전·이미지·자원·기존 환경변수·Secret·bundle을 유지했다. 실행 중 태스크가 없는 시점에 시작했고 재처리·합치기 DAG를 활성화하지 않았다.
- API·scheduler·DAG processor 3개 Ready 복귀 후 실제 Airflow 환경에서 두 DAG의 runtime 검사와 기존 모든 DAG pause 상태 보존을 확인했다. pool 1슬롯·전체 parallelism 1도 유지했다.
- 전체 로그 8개를 로컬 비공개 파일과 S3 `airflow-logs/infra-spark-validation/gold-b-20261024/`에 보존하고 해시를 대조했다. 시험에서 만든 종료 Pod·Job만 UID 확인 후 정리했다.
- 시험 노드에 DaemonSet만 남았음을 확인한 뒤 해당 시험 NodeClaim을 명시적으로 해제했다. EC2 terminated·Spark 0대·전체 노드 2대·NodePool 불변을 확인했다. 유휴 10분 자동 축소를 다시 시험한 결과는 아니다.
- 실데이터에서 만든 원장과 checkpoint는 삭제하지 않았다. Kafka 전체 backlog를 다 처리한 시험은 아니며 상시 적재는 현재 꺼져 있다.

## 후속

Silver·Gold A와의 동시 실행, 강제 종료 중 미커밋 배치 재처리, 장시간 상시 운영·자동 재제출, Gold B 재처리·파일 합치기 실제 실행은 후속이다. 이번 입력에서 오류 원장이 0건인 것은 오류 데이터 시험 통과를 뜻하지 않는다. Spark 종료 시 namespace 내 collection 정리 권한 부족 경고가 남아 종료 리소스를 명시적으로 정리했다. 이 경고를 이유로 공유 namespace의 PVC 일괄 삭제 권한을 넓히지 않았다. 상시 운영 전 정리 방식도 검토해야 한다.
