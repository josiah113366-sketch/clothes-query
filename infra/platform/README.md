# 플랫폼 runtime 준비

EKS·노드 생성은 기존 Terraform 스택이 관리한다. 플랫폼 운영자와 runtime은 별도 Helm release로 설치한다. 현재 [Kafka·Connect](kafka/README.md)만 준비했으며 Spark/Airflow는 미구현이다. Helm release 저장 정보는 Kubernetes Secret에 저장되므로 Terraform state와 공유하지 않는다. 같은 리소스를 양쪽에서 관리하지 않는다.
