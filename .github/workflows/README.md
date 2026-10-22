# 인프라 자동 검사

모니터링 Helm 렌더·격리 범위, Prometheus 설정·경보 동작 검사도 포함한다. 고정 Prometheus 이미지로 검사하며 AWS 배포 권한은 사용하지 않는다. [모니터링 안내](../../infra/platform/monitoring/README.md)를 따른다.

[infra-checks.yml](infra-checks.yml)은 Terraform/mock, Kafka Helm, 일회성 로컬 TLS/CDC/보존/지표, Connect 이미지 취약점 보고를 실행한다. AWS/클러스터 인증·배포·이미지 push는 없다. 실행 방법과 한계는 [검사 안내](../../infra/checks/README.md)를 따른다.
