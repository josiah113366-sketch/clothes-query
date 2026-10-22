# 인프라 확인용 DAG

`infra_probe.py`는 설치·인증·5분 cron·전용 Pod Identity 검증용 합성 DAG다. 업무용 판정/재처리 코드를 포함하지 않는다. 두 DAG는 생성 시 paused로 두고 검증 후 다시 pause한다.

실행 이미지 digest와 현재 노드 hostname은 비공개 ConfigMap을 통한 `AIRFLOW_INFRA_PROBE_CONFIG` JSON으로 공급한다. agent namespace의 `detection-job`, `investigation-agent` ServiceAccount와 scheduler의 Pod 실행 RBAC가 필요하다. [설치 안내](../README.md)를 따른다.

## Silver·Gold A 수동 업무 DAG

`silver_gold_a.py`의 `silver_gold_a_batch`는 제출기 Pod에서 spark-submit cluster mode로 거래·리뷰 Spark 잡을 제출하고 Driver 최종 완료까지 기다린다. 기존 infra probe와 별개다. `AIRFLOW_PIPELINE_RUNTIME` JSON에 이미지 digest·namespace·제출기/Driver/Executor ServiceAccount·노드 배치를 공급한다. 요청은 dag_run.conf.config_uri로 고정 S3 JSON을 지정한다. [Spark 실행 명세](../../../../pipelines/README.md#운영-실행-연결--spark-거래-배치)를 따른다.

namespace·Pod Identity·S3 권한·Airflow의 대상 namespace Pod RBAC·ECR 이미지·실행 설정은 별도 준비가 필요하다. 인프라 확인 기준 main의 이 폴더는 약 60초마다 Airflow로 동기화되며 신규 DAG는 기본 일시정지 상태다. 별도 DAG ConfigMap/subPath 마운트를 추가하지 않는다. 이 파일은 이를 생성하지 않는다. 이미지가 없는 상태에서는 설정 확인 태스크에서 실패하며 Pod를 실행하지 않는다. 최초는 paused·schedule 없음·max_active_runs=1·재시도 0이다.

제출기는 Driver를 생성·관찰하고 Driver는 Executor Pod·Service·ConfigMap을 관리한다. Kubernetes 인증용 토큰을 쓰므로 일반 Python 시제품의 automount=false 설정을 그대로 적용하지 않는다. Driver·Executor의 S3 접근은 별도 Pod Identity로 연결한다. 자원 기본값은 전용 노드에 대한 제안이며 인프라 검토 후 spark_conf로 조정한다.
