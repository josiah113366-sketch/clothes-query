# Airflow DAG 원본

이 경로는 업무 DAG의 공통 Git 공급 경로이기도 하다. 동료가 판정·조사·재처리 DAG를 작성해 PR로 제출하고 인프라 담당은 저장/실행 권한·자원·환경변수·Secret 참조를 검토한다. 업무 SQL·모델·판정·승인 로직은 담당자 소유다. main 수동 머지 후 Airflow GitDagBundle이 60초 간격으로 가져오며 새 DAG는 paused 상태로 등록한다. 활성화는 실제 이미지 digest·입력·자원 계약을 확인한 뒤 진행한다.

DAG 파일은 Python 표준 라이브러리와 현재 Airflow 이미지의 provider만 import한다. Git에 requirements.txt를 추가해도 패키지가 자동 설치되지 않는다. 무거운 업무 코드는 ECR의 판정/조사 이미지에 두고 KubernetesPodOperator로 별도 Pod에서 실행한다. 이미지에는 새 커밋 태그나 digest를 사용하고 정적 AWS 키를 넣지 않는다. ServiceAccount는 agent/detection-job 또는 agent/investigation-agent다.

`infra_probe.py`는 설치·인증·5분 cron·전용 Pod Identity 검증용 합성 DAG다. 업무용 판정/재처리 코드를 포함하지 않는다. 두 DAG는 생성 시 paused로 두고 검증 후 다시 pause한다.

실행 이미지 digest와 현재 노드 hostname은 비공개 ConfigMap을 통한 `AIRFLOW_INFRA_PROBE_CONFIG` JSON으로 공급한다. agent namespace의 `detection-job`, `investigation-agent` ServiceAccount와 scheduler의 Pod 실행 RBAC가 필요하다. [설치 안내](../README.md)를 따른다.
