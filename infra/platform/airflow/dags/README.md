# 인프라 확인용 DAG

`infra_probe.py`는 설치·인증·5분 cron·전용 Pod Identity 검증용 합성 DAG다. 업무용 판정/재처리 코드를 포함하지 않는다. 두 DAG는 생성 시 paused로 두고 검증 후 다시 pause한다.

실행 이미지 digest와 현재 노드 hostname은 비공개 ConfigMap을 통한 `AIRFLOW_INFRA_PROBE_CONFIG` JSON으로 공급한다. agent namespace의 `detection-job`, `investigation-agent` ServiceAccount와 scheduler의 Pod 실행 RBAC가 필요하다. [설치 안내](../README.md)를 따른다.

## Silver·Gold A 수동 업무 DAG

`silver_gold_a.py`의 `silver_gold_a_batch`는 작업을 선택해 별도 처리 Pod에서 실행한다. 기존 infra probe와 별개다. `AIRFLOW_PIPELINE_RUNTIME` JSON에 이미지 digest·namespace·ServiceAccount·노드 배치를 공급한다. 수동 실행 입력·S3 결과 계약은 [파이프라인 운영 안내](../../../../pipelines/README.md#운영-실행-연결--수동-배치)를 따른다.

namespace·Pod Identity·S3 권한·Airflow의 대상 namespace Pod RBAC·ECR 이미지·DAG ConfigMap/subPath 마운트는 별도 준비가 필요하다. 이 파일은 이를 생성하지 않는다. 이미지가 없는 상태에서는 설정 확인 태스크에서 실패하며 Pod를 실행하지 않는다. 최초는 paused·schedule 없음·max_active_runs=1·재시도 0이다.
