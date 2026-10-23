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
