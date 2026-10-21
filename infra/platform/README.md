# 플랫폼 runtime 준비

EKS·노드 생성은 기존 Terraform 스택이 관리한다. 플랫폼 운영자와 runtime은 별도 Helm release로 설치한다. [Kafka·Connect](kafka/README.md)를 준비했고 [Airflow](airflow/README.md)는 별도 로컬 실행 후보를 검증한다. Airflow의 AWS/Helm 배포와 Spark는 미구현이다. Helm release 저장 정보는 Kubernetes Secret에 저장되므로 Terraform state와 공유하지 않는다. 같은 리소스를 양쪽에서 관리하지 않는다.

[판정·조사 실행 신원](agent-access/README.md)은 별도 manifest로 agent namespace/ServiceAccount를 관리한다. Pod Identity 연결과 합성 S3/Athena 접근·정답표 차단을 실제 임시 Pod에서 검증했고 테스트 자원은 정리했다. 실제 업무 앱·DAG는 아직 배포하지 않았다.
