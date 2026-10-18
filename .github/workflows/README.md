# 인프라 자동 검사

[infra-checks.yml](infra-checks.yml)은 Terraform/mock, Kafka Helm, 일회성 로컬 TLS/CDC/보존/지표, Connect 이미지 취약점 보고를 실행한다. AWS/클러스터 인증·배포·이미지 push는 없다. 실행 방법과 한계는 [검사 안내](../../infra/checks/README.md)를 따른다.
