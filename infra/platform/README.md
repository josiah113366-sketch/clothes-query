# 플랫폼 runtime 준비

EKS·노드 생성은 기존 Terraform 스택이 관리한다. 플랫폼 runtime은 별도 Helm release로 설치한다. [Kafka·Connect](kafka/README.md)와 [개발용 Airflow](airflow/README.md)는 실제 EKS에 배포했다. Airflow는 기존 RDS의 전용 DB·Simple Auth Manager를 사용하며 API 인증, 전용 업무 Pod 실행, S3 로그, 5분 합성 cron을 검증했다. 실제 업무 DAG와 Spark 실행 연결은 후속이다. Helm release 저장 정보는 Kubernetes Secret에 저장되므로 Terraform state와 공유하지 않는다. 같은 리소스를 양쪽에서 관리하지 않는다.

[판정·조사 실행 신원](agent-access/README.md)은 별도 manifest로 agent namespace/ServiceAccount를 관리한다. Pod Identity 연결과 합성 S3/Athena 접근·정답표 차단을 실제 임시 Pod에서 검증했고 테스트 자원은 정리했다. 실제 업무 앱·DAG는 아직 배포하지 않았다.

[Spark 실행 기반](spark/README.md)은 업무 배포 전 준비다. 기본 이미지·EKS 합성 시험 후 임시 리소스를 정리했으며 전용 노드풀은 기본 비활성이다. 계정·권한·자원 프로필을 파일로 렌더한다. 최종 업무 이미지·DAG·S3 계약과 실제 데이터 검증은 후속이며 이번 통합에서는 노드를 생성하지 않았다.
