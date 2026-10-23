# Gold B 실행 기반

Gold B 상시 Spark 적재와 Python 재처리·합치기의 실행 신원을 분리한다. `prepare.py`는 파일만 생성하며 AWS/kubectl/Helm을 호출하거나 Pod·Job·노드를 시작하지 않는다. CI 실패 수정과 #101 머지는 이 작업 범위가 아니다.

## 실행 신원과 데이터 경계

| ServiceAccount (`pipelines`) | 권한 |
|---|---|
| `gold-b-ingest-submitter` | 같은 namespace에서 Spark 제출·완료 관찰. AWS 역할 없음 |
| `gold-b-ingest-driver`, `gold-b-ingest-executor` | 별도 Pod Identity 역할. `gold_b/payment_events/`, `topic_messages/`, `malformed_events/` 읽기·쓰기. 원장 삭제 권한 없음 |
| `gold-b-ledger-jobs` | 재처리·합치기. 위 원장 3개와 `bronze_lag_snapshots/` 읽기·쓰기·삭제. `reprocess_events/`는 읽기·쓰기만. `bronze_v2/` 업무 5개 토픽 prefix 읽기만 |

어느 역할에도 `ground_truth/`, `agent/`, Silver·Gold A 접근을 추가하지 않는다. 기존 workload-access bindings는 보존하며 같은 이름의 다른 설정은 덮어쓰지 않는다. namespace 공유와 Pod 생성 권한 때문에 ServiceAccount 분리가 강한 보안 격리는 아니며 팀원 namespace 운영 권한도 함께 관리해야 한다.

체크포인트는 제안 경로만 있고 최종 확정 전이다. 기본 생성 결과에는 checkpoint 권한을 **넣지 않는다**. 확정된 뒤 `--checkpoint-prefix gold_b/_checkpoints/<확정 이름>/`를 지정하면 적재 Driver·Executor 역할에 해당 하위 prefix의 읽기·쓰기·삭제·멀티파트 정리만 추가된다. 체크포인트 삭제는 처리 위치를 초기화할 수 있으므로 운영 중 임의 정리하지 않는다.

## 준비 파일 생성

저장소 루트에서 PyYAML이 있는 Python으로 실행한다. 결과 폴더는 새 경로여야 한다.

```powershell
python infra/platform/gold-b/prepare.py --existing-vars infra/stacks/workload-access/deployment.auto.tfvars.json --output-dir .cache/gold-b-review
python -m unittest discover -s infra/platform/gold-b -v
```

- `foundation.json`: 계정 4개, namespace RBAC, Spark ConfigMap, KafkaUser 2개, Kafka ingress 정책. 실행 workload·Namespace·공유 quota·Secret은 생성하지 않는다.
- `workload-access.tfvars.json`: 기존 bindings와 Gold B 3개 역할을 합친 입력. 실제 적용 시 다른 로컬 var-file이 bindings 전체를 덮어쓰지 않는지 plan을 확인한다.
- `runtime.pending.json`: 재처리·합치기용 `AIRFLOW_GOLD_B_RUNTIME` 초안. 이미지가 null이므로 이 상태로 ConfigMap/환경변수에 공급하지 않는다. `bronze_root` 소비는 #101 머지·해당 코드가 들어간 최종 이미지가 필요하다.
- `ingest.pending.json`: 적재 제출 계정·이미지 내 진입점·환경변수 초안. image와 GOLD_B_CHECKPOINT가 null이므로 실행할 수 없다.
- `batch-shared-spark-conf.json`: 시험한 단일 노드 공유 후보. 기존 Silver·Gold A 설정에 자동 적용하지 않는다. 적용하려면 기존 AIRFLOW_PIPELINE_RUNTIME의 신원·이미지·템플릿은 보존하고 spark_conf에 병합한다.

## Kafka와 배치

TLS 사용자 `gold-b-ingest`, `gold-b-reprocess`는 6개 토픽의 Read/Describe와 자기 이름 접두사의 소비자 그룹 Read/Describe만 가진다. 토픽 쓰기·생성·cluster admin은 없다. Kafka namespace의 NetworkPolicy는 pipelines의 `app=gold-b-ingest` 또는 `app=gold-b-ledger-jobs` Pod에 9093만 허용한다.

원본 사용자 Secret의 `user.crt`·`user.key`와 **Kafka cluster CA**를 pipelines의 `gold-b-ingest-tls`, `gold-b-reprocess-tls`로 비공개 복사한다. 사용자 Secret의 ca.crt를 서버 CA로 간주하지 않는다. 인증서 갱신 때 복사·재시작이 필요하며 자동 mirror controller는 설치하지 않는다. 실제 Secret/인증서/키/접속용 비공개 파일은 Git에 올리지 않는다.

Gold B DAG는 Spark 전용 풀을 node_selector로 지정하면 해당 NoSchedule taint의 toleration을 함께 넣는다. `app=gold-b-ledger-jobs`는 Kafka 정책과 맞춘다. 적재 Driver·Executor template에도 Spark selector/toleration과 TLS 볼륨이 있다. 실제 DAG에 전달하는 Secret 기본 파일 모드는 읽기 가능해야 하며 적재 template의 fsGroup=185·0440 모드는 함께 유지한다.

재처리·합치기는 **Spark를 쓰지 않는 Python 작업**이다. 두 DAG의 pool은 `gold_b_ledger`, 슬롯 1개다. 상시 Spark 적재는 이 pool을 점유하지 않는다. Airflow 전체 parallelism=1은 그대로 유지하며 DAG를 임의로 켜지 않는다. 기존 `default_pool` 슬롯 수를 변경하지 않는다.

## 배포 종료 조건

최종 ECR 이미지 digest·적재 checkpoint 확정·권한 검증·runtime 공급 뒤 EKS/S3 수동 검증이 필요하다. ECR `clothes-query-dev/gold-b` 저장소 준비만으로 이미지 발행 완료가 아니며 새 팀원 publisher ARN을 추측해 권한을 추가하지 않는다. Spark 공유 자원 후보는 [시험 기록](../../../docs/operations/spark-shared-capacity-check.md)을 따른다.

실제 적용/검증 여부는 [현재 업무 목록](../../../docs/infra-work-queue.md)과 [이 브랜치 작업 기록](../../../docs/tasks/infra-applied-state-sync.md)을 우선 확인한다.
