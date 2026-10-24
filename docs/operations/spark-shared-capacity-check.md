# Spark 전용 large 한 대 공유 검토

상태: 2026-10-24 격리 로컬 워크로드 시험 완료. EKS 배포·자원 설정 변경·ECR push는 하지 않음.

## 판단

작은 입력에서는 Gold B 상시 적재와 Silver·Gold A 배치가 Spark 전용 t3a.large 한 대를 공유하는 방안을 검토할 수 있다. 서로 다른 Spark 애플리케이션·Driver·Executor·ServiceAccount를 유지하고 같은 Spark NodePool에 배치하는 방식이다. Kafka·Airflow 공용 노드에 합치는 뜻이 아니다.

현재 Spark NodePool은 t3a.large, 한도 CPU 2·메모리 8Gi이다. 실행 중인 동일 타입 노드의 allocatable은 CPU 1,780m·메모리 7,215,740Ki였다. 따라서 Driver 1 CPU와 Executor 1 CPU를 각각 request로 지정하면 단독으로도 CPU 예약이 초과한다. 실제 사용량이 적더라도 예약이 초과하면 배치되지 않는다.

## 시험 조건과 결과

- 코드: main 6c00ddc. 팀 기본 ECR digest `sha256:9548d0949843699f8722a4eb78551129ab718a340a618a06f088483c0ac7985f`를 FROM으로 Gold B Dockerfile을 로컬 빌드했다. Spark 4.2.0·Python 3.10.12와 네 실행 모듈 import 통과.
- 외부로 연결되지 않는 Docker 내부 네트워크의 Kafka와 Spark standalone 사용. AWS 키·운영 데이터·운영 원장·실제 체크포인트를 사용하지 않았다. S3 대신 격리된 로컬 Parquet을 사용했다.
- Gold B는 실제 build_query·FormatChecker·write_batch를 연결했다. 60초 주기, 최대 20,000건, Executor 1개. 합성 정상 결제 1,000건 뒤 배치 시작 때 20,000건, 배치 Parquet 저장 중 20,000건을 추가했다.
- Silver·Gold A는 실제 spark_batch.py execute 경로로 연결된 주문·주문상품·결제 각 200건과 상품 기준정보를 읽어 결과를 공개했다. Gold B와 별도 Driver·Executor를 사용했다.
- 두 Driver와 Executor를 실행하는 worker의 Docker CPU 상한 합계 1.6 CPU, 메모리 상한 합계 6.25GiB. Gold B Driver heap 1GiB/container 2GiB, 배치 Driver heap 512MiB/container 1,280MiB, Executor heap 각 768MiB, 두 Executor와 standalone worker daemon을 담은 worker container 3GiB. 로컬 master·Kafka·짧게 실행한 입력 생성기는 이 합계에서 제외했다.
- 원장 검증: topic_messages 41,000줄, payment_events 41,000줄, malformed_events 0줄. 정상 결제만 넣은 이번 입력의 기대값과 일치했다.
- 배치 검증: PASS, 주문·성공 결제 각 200건, 매출 2,360,000, 판매 수량 400. Parquet을 별도 프로세스로 다시 읽어 확인했다.
- queryProgress 기준 1,000건 8.191초, 첫 20,000건 11.694초. 추가 20,000건도 원장 및 checkpoint commit 3까지 확인했다. 마지막 묶음의 queryProgress는 종료 직전 수집하지 못했고, checkpoint의 batchTimestampMs와 commit 파일 mtime 차이는 약 9.882초였다. 이 값은 queryProgress의 정확한 trigger duration과 구분한다.
- Docker stats 관측 최고 합산 메모리 2,609.856MiB(약 2.55GiB), 합산 CPU 약 1.24개. Gold B Driver 최고 688.1MiB, 배치 Driver 673.5MiB, worker 1,248.256MiB. 약 4~5초 간격 표본이므로 순간 최고치 보장은 아니다. worker 값에는 Executor 두 개와 standalone worker daemon이 포함된다.
- 두 업무 프로세스 exit code 0, OOMKilled=false. 배치는 시작부터 종료 확인까지 약 4분 15초였다. Driver CPU를 0.25개로 엄격하게 제한한 로컬 결과이므로 실제 배치 SLA로 사용하지 않는다.

시험 도구는 마지막 정상 stream 종료를 검사하는 사이 프로세스가 종료된 경쟁 조건으로 실패를 반환했다. 원본 결과의 오류는 보존했다. 두 프로세스 exit 0·배치 PASS·41,000건·금액·checkpoint를 독립 확인했으며 종료 검사 조건을 수정했다. 수정한 전체 도구를 재실행한 결과로 표시하지 않는다. 초기 로컬 Kafka 옵션/로그 경로 문제도 시험 환경 수정으로 해결했고 앱·운영 Kafka는 변경하지 않았다.

## EKS 적용 후보 — 미적용

| 역할 | CPU request | Spark heap | overhead | Pod 메모리 합계 |
|---|---:|---:|---:|---:|
| Gold B Driver | 350m | 1GiB | 1GiB | 2GiB |
| Gold B Executor 1개 | 500m | 768MiB | 512MiB | 1.25GiB |
| Silver·Gold A Driver | 250m | 512MiB | 768MiB | 1.25GiB |
| Silver·Gold A Executor 1개 | 500m | 768MiB | 512MiB | 1.25GiB |
| 배치 제출기 | 100m | 해당 없음 | 해당 없음 | 256MiB request |

동시 예약 합계는 CPU 1,700m·메모리 6GiB이다. Executor 자동 증가는 끄거나 최대 1개로 제한해야 한다. Kubernetes Pod overhead, 실제 admission 결과, 컨테이너별 request/limit와 초기화 컨테이너를 포함해 실환경에서 다시 계산해야 한다. 이 표는 로컬 구성에서 도출한 후보이며 EKS에서 해당 Pod 조합을 실행한 결과가 아니다. 기존 Silver·Gold A 설정은 아직 그대로다.

최종 이미지 digest·적재 전용 AWS/Kafka 권한·인증서·checkpoint 계약 연결 후, 같은 제한으로 EKS/S3 수동 시험을 해야 한다. 한대 상한에서 배치가 Pending이 되면 무작정 노드를 늘리지 않고 예약량·동시 실행·Executor 개수부터 확인한다. 배치 작업은 전용 pool 1슬롯 등으로 서로 겹치지 않게 관리하고, 상시 적재를 현재 Airflow 전체 parallelism=1 자리에서 계속 기다리게 해 다른 업무를 막지 않는다.

Gold B 적재를 상시 띄우면 입력이 없어도 Driver·Executor가 노드를 사용하므로 Spark 노드는 보통 한 대가 유지된다. 한 노드 공유는 두 번째 Spark 노드를 줄이는 선택이지 상시 적재 노드를 유휴 시 자동 0대로 만드는 선택은 아니다.

## 한계와 정리

이번에는 작은 정상 결제 한 종류·총 41,000건과 주문 200건만 시험했다. 큰 메시지·모든 토픽·대규모 오류·재처리·장기 누수·노드 장애·실제 S3 쓰기 지연·TLS·Pod Identity·EKS 스케줄링·스토리지 커미터는 검증하지 않았다. 작은 로컬 관측값만 보고 메모리 예약을 2.55GiB로 줄이지 않는다.

시험용 컨테이너 5개와 내부 네트워크는 종료·삭제했다. 합성 파일·checkpoint·검증 로그는 Git 제외 `.cache/spark-sharing-probe/`에 보존했고 로컬 빌드 이미지는 후속 확인용으로 남겼다. AWS 자원 추가·운영 데이터 변경·Git push/PR/승인/머지는 하지 않았다.
