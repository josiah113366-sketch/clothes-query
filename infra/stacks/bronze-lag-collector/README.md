# Bronze 지연 수집기 AWS 기반

eks/storage 뒤에 init·validate·plan을 확인하고 적용한다. 독립 backend key로 ECR·IAM 정책/역할·Pod Identity 4개만 관리한다. 기존 workload-access 및 Kafka broker/Connect는 변경하지 않는다. Kubernetes 배포·cert 복사는 ../../platform/bronze-lag-collector를 따른다. 제거 전에 실행 Pod를 중지하고 측정 중단 영향을 확인한다.
