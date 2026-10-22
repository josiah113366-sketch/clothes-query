# 인프라 확인용 DAG

`infra_probe.py`는 설치·인증·5분 cron·전용 Pod Identity 검증용 합성 DAG다. 업무용 판정/재처리 코드를 포함하지 않는다. 두 DAG는 생성 시 paused로 두고 검증 후 다시 pause한다.

실행 이미지 digest와 현재 노드 hostname은 비공개 ConfigMap을 통한 `AIRFLOW_INFRA_PROBE_CONFIG` JSON으로 공급한다. agent namespace의 `detection-job`, `investigation-agent` ServiceAccount와 scheduler의 Pod 실행 RBAC가 필요하다. [설치 안내](../README.md)를 따른다.
