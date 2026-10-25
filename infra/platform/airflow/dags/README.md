# 인프라 확인용 DAG

`infra_probe.py`는 설치·인증·5분 cron·전용 Pod Identity 검증용 합성 DAG다. 업무용 판정/재처리 코드를 포함하지 않는다. 두 DAG는 생성 시 paused로 두고 검증 후 다시 pause한다.

실행 이미지 digest는 비공개 ConfigMap의 `AIRFLOW_INFRA_PROBE_CONFIG` JSON으로 공급한다. 설치 확인 Pod도 특정 hostname 대신 공용 compute 풀을 사용한다. 과거 hostname 키는 사용하지 않는다. agent namespace의 `detection-job`, `investigation-agent` ServiceAccount와 scheduler의 Pod 실행 RBAC가 필요하다. [설치 안내](../README.md)를 따른다.

## Silver·Gold A 수동 업무 DAG

`silver_gold_a.py`의 `silver_gold_a_batch`는 제출기 Pod에서 spark-submit cluster mode로 거래·리뷰 Spark 잡을 제출하고 Driver 최종 완료까지 기다린다. 기존 infra probe와 별개다. `AIRFLOW_PIPELINE_RUNTIME` JSON에 이미지 digest·namespace·제출기/Driver/Executor ServiceAccount·노드 배치를 공급한다. 요청은 dag_run.conf.config_uri로 고정 S3 JSON을 지정한다. [Spark 실행 명세](../../../../pipelines/README.md#운영-실행-연결--spark-거래-배치)를 따른다.

namespace·Pod Identity·S3 권한·Airflow의 대상 namespace Pod RBAC·ECR 이미지·실행 설정은 별도 준비가 필요하다. 인프라 확인 기준 main의 이 폴더는 약 60초마다 Airflow로 동기화되며 신규 DAG는 기본 일시정지 상태다. 별도 DAG ConfigMap/subPath 마운트를 추가하지 않는다. 이 파일은 이를 생성하지 않는다. 이미지가 없는 상태에서는 설정 확인 태스크에서 실패하며 Pod를 실행하지 않는다. 최초는 paused·schedule 없음·max_active_runs=1·재시도 0이다.

제출기는 Driver를 생성·관찰하고 Driver는 Executor Pod·Service·ConfigMap을 관리한다. Kubernetes 인증용 토큰을 쓰므로 일반 Python 시제품의 automount=false 설정을 그대로 적용하지 않는다. Driver·Executor의 S3 접근은 별도 Pod Identity로 연결한다. 자원 기본값은 전용 노드에 대한 제안이며 인프라 검토 후 spark_conf로 조정한다.

### Spark 전용 노드·종료 검증

- 제출기 toleration은 clothes-query/dedicated=spark:NoSchedule이다. runtime_configmap(기본 silver-gold-a-runtime)을 /opt/spark/infra에 마운트해 Driver·Executor 인프라 Pod template도 사용한다. 두 template에도 같은 toleration이 필요하며 Driver가 Executor template을 읽을 수 있도록 같은 ConfigMap을 마운트한다.
- 제출 명령은 python3 -m pipelines.submit_spark다. 내부 spark-submit 종료 코드와 Driver phase=Succeeded 및 spark-main 컨테이너 종료 코드 0을 함께 확인한다. waitAppCompletion만으로 성공 판정을 하지 않는다.
- namespace Pod get 권한으로 최종 상태를 관찰한다. Driver 자동 삭제는 포함하지 않으며 중단·시간 초과 시 운영자가 상태를 확인한다. 3,000초 대기 상한·자동 재시도 0이며 실패·관찰 불능은 Airflow 실패로 전달한다. 실제 EKS 검증은 별도다.

## Gold B 재처리·파일 합치기 DAG

`gold_b.py`에 DAG 2개가 있다. 잡은 Gold B 이미지(`pipelines/gold_b/Dockerfile`)에서 파이썬으로 돌고 Spark를 쓰지 않는다. 잡이 하는 일은 [Gold B 잡 설명](../../../../pipelines/gold_b/jobs/README.md)에 있다.

| DAG | 주기 | Pod 명령 | Airflow 재시도 |
|---|---|---|---|
| `gold_b_reprocess` | 5분마다 | `python3 -m pipelines.gold_b.jobs.reprocess` (승인된 재처리 요청 하나, 없으면 바로 끝남) | 0 (다시 돌릴지는 잡이 `reprocess_events`를 보고 정함) |
| `gold_b_compact` | 매일 00:30 UTC | `python3 -m pipelines.gold_b.jobs.compact --day <날짜 입력>` (비우면 끝난 어제 UTC) | 2번, 10분 간격 |

- 둘 다 꺼진 채로 만들어지고, 밀린 실행은 하지 않으며(catchup 끔) 한 번에 하나만 돈다. 실행 상한은 재처리 2시간, 파일 합치기 1시간이다.
- 파일 합치기를 손으로 실행할 때 날짜 입력(`day`, `YYYY-MM-DD`)을 넣으면 그 날을 합친다. 예약 실행은 빈 값이라 어제(UTC)다. 적재 잡이 Kafka를 따라잡으며 쌓은 지난 날이나 늦게 들어온 줄을 합칠 때 쓴다. 끝나지 않은 날(그 날 끝 + 10분 전)은 잡이 거부한다 (2026-10-25).
- 두 DAG의 Pod는 같은 pool에 넣는다. 재처리가 승인 범위 밖 결제 시각 폴더도 고칠 수 있어서 둘이 같은 시간에 돌면 안 된다.
- 승인 화면(`agent/approval`)은 R1·R4·R5 재처리를 Airflow로 부르지 않고, 이 DAG가 5분마다 승인 줄을 읽는다고 본다. 켜지 않으면 승인된 Gold B 재처리가 시작되지 않는다.
- 재처리는 Kafka 보관 기간(7일)이 지난 시간대를 Bronze v2 파일에서 읽는다. `bronze_root`가 없으면 그런 요청은 시작 전에 거부한다.
- Pod는 k8s API 토큰을 붙이지 않고(automount 끔) EC2 메타데이터를 끈다. 자원은 요청 0.25 CPU·512Mi, 상한 1 CPU·2Gi이고 끝나면 지운다.

실행 설정은 비공개 ConfigMap을 통한 `AIRFLOW_GOLD_B_RUNTIME` JSON으로 공급한다 (Silver의 `AIRFLOW_PIPELINE_RUNTIME`과 따로). 없거나 틀리면 확인 태스크에서 멈추고 Pod를 띄우지 않는다. `agent`·`kafka`·`kube-system` namespace는 거부한다.

```json
{
  "image": "<Gold B 이미지>@sha256:<digest>",
  "namespace": "<잡 namespace>",
  "service_account": "<잡 ServiceAccount>",
  "ledger_root": "s3://<버킷>/gold_b",
  "kafka_bootstrap": "<Kafka TLS 리스너 주소>",
  "kafka_tls_secret": "<Kafka 인증서 Secret>",
  "bronze_root": "s3://<버킷>/bronze_v2",
  "pool": "gold_b_ledger",
  "node_selector": {}
}
```

| 키 | 필수 | 뜻 |
|---|---|---|
| `image` | 예 | Gold B 이미지 digest (빌드는 [Gold B README](../../../../pipelines/gold_b/README.md) 「이미지」) |
| `namespace`, `service_account` | 예 | 잡 Pod를 띄울 자리와 실행 신원 (Pod Identity) |
| `ledger_root` | 예 | 원장 위치 `s3://<버킷>/gold_b` |
| `kafka_bootstrap`, `kafka_tls_secret` | 재처리만 | Kafka TLS 주소와 인증서 Secret. Secret은 `/opt/kafka-tls`에 붙이고 키는 `ca.crt`(Kafka 클러스터 CA), `user.crt`, `user.key`다 |
| `bronze_root` | 아니오 (재처리만) | Bronze v2 위치 `s3://<버킷>/bronze_v2`. 재처리 Pod에 `GOLD_B_BRONZE_ROOT`로 준다. 없으면 Kafka 보관 기간(7일)이 지난 시간대의 요청을 거부한다 |
| `pool` | 아니오 | 두 DAG가 같이 쓰는 Airflow pool (슬롯 1개). 없으면 기본 pool. 지금은 Airflow 전체 동시 작업이 1개라 겹치지 않는다 |
| `node_selector` | 아니오 | Pod 배치 (없으면 지정하지 않음) |

켜기 전에 준비할 것 (인프라):

- Airflow에 `AIRFLOW_GOLD_B_RUNTIME` 공급. `pool`을 쓰면 그 pool(슬롯 1개)을 먼저 만든다. 없는 pool 이름을 주면 태스크가 돌지 않는다.
- Airflow의 잡 namespace Pod 실행 RBAC
- 실행 신원 권한 (두 DAG가 같이 씀): S3 `gold_b/payment_events/`·`topic_messages/`·`malformed_events/`·`bronze_lag_snapshots/` 읽기·쓰기·지우기, `gold_b/reprocess_events/` 읽기·쓰기. `bronze_root`를 쓰면 `bronze_v2/` 읽기(목록 포함)
- Kafka (재처리만): TLS 사용자에 6개 토픽 `Read`·`Describe`, 잡 namespace를 클라이언트 리스너에 허용. 잡은 임시 그룹 이름(`gold-b-reprocess-…`)으로 파티션을 직접 지정해 읽고 커밋하지 않는다. 그룹 권한 오류가 나면 이름 앞부분 `gold-b-reprocess-`로 준다. Strimzi 사용자 Secret의 `ca.crt`는 클라이언트 CA라서, 클러스터 CA를 `ca.crt`로 넣은 Secret을 잡 namespace에 만든다.
