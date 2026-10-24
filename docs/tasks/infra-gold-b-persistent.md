# Gold B 상시 적재 시작

2026-10-24 사용자가 상시 적재·노드 운영을 승인했다. 이전 단기 시험 후 종료 상태를 해제했다.

## 배포

- `pipelines/gold-b-ingest` Deployment: Driver 1개, Recreate, restartPolicy Always.
- 기존 업무 이미지 `2a8acd10`와 정상 진입점 streaming_ingest.py를 사용한다. 시험 진입점·시간 제한·새 checkpoint를 사용하지 않는다.
- Driver 350m/2GiB·Executor 1개 500m/1.25GiB. 전용 t3a.large Spark 풀 한 대분(2CPU/8GiB) 한도를 유지했다.
- Driver는 client mode로 Deployment 내부에서 실행한다. headless Service의 RPC/BlockManager 포트를 Executor가 사용한다. 외부 ALB/공인 포트는 열지 않았다.
- 기존 Driver/Executor ServiceAccount·Pod Identity·Kafka TLS·S3 체크포인트를 재사용했다. 신규 IAM 권한·업무 이미지 변경·Kafka offset 초기화는 없다.

## 실제 확인

- 새 Spark 노드 1대 생성 후 Driver·Executor 모두 Running·Ready, 재시작 0으로 확인했다.
- 기존 checkpoint 이후 배치 3에서 메시지 19,992건·원장 파일 6개 처리 로그와 새 S3 commit 3을 확인했다.
- 이어서 S3 commit 4·5도 확인해 계속 진행 중임을 확인했다. 한 시점의 Driver 366m/753Mi·Executor 25m/510Mi 관측은 최대 사용량이나 장시간 안정성 보장이 아니다.
- 골격·단일 replica·계정/체크포인트 유지·시험 설정 차단을 포함한 Gold B 준비 검사 9개가 통과했다.
- 초기 노드 네트워크 정책 준비 지연은 컨테이너 시작 후 해소됐다. 첫 커밋 확인 시 처리 예외는 없었다.

## 운영 범위와 한계

Deployment가 프로세스/Pod 종료에 대응하지만 강제 장애 복구와 장시간 안정성 검증은 별도다. RPC readiness만으로 데이터 적재 성공을 판단하지 않는다. 실제 묶음과 체크포인트 진행을 함께 확인한다.

상시 잡이 남아 있으므로 Spark 노드는 상시 비용이 발생한다. 현재 전체 노드는 API 1·공용 2·Spark 1로 확인했으며 공용 풀 증설/통합은 이번 작업에서 변경하지 않았다.

Silver·Gold A 기본 최대 배치와 동시 실행은 단일 풀 예산을 초과할 수 있다. 자원 부족 시 Pod가 Pending일 수 있으며 이번 승인으로 풀 한도나 배치 크기를 늘리지 않았다. 별도 스케줄 조정·실측이 필요하다.

중지하려면 Deployment replicas를 0으로 내리고 관련 Executor 종료를 확인한다. 체크포인트는 삭제하지 않는다. 재개 시 replicas=1로 돌린다. 같은 체크포인트를 사용하는 별도 적재 잡을 동시에 제출하지 않는다. Recreate는 일반 업데이트의 중복을 줄이지만 네트워크 단절 시 완전한 분산 fencing을 보장하지 않는다.

공식 실행 근거: [Spark Kubernetes client mode](https://spark.apache.org/docs/4.2.0/running-on-kubernetes.html#client-mode).
