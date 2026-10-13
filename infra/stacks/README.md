# 배포 스택

기존 bootstrap은 보존한다. 이번 구현은 dev 환경이며 backend key와 리소스 이름이 dev로 고정되어 있다. 다른 환경에는 새 key/이름 설계를 먼저 검토한다.

- [network](network/README.md)
- [eks](eks/README.md)
- [compute](compute/README.md)
- [rds](rds/README.md)
- [storage](storage/README.md)
- [ecr](ecr/README.md)
- [apps](apps/README.md)
- [workload-access](workload-access/README.md): network/eks/storage 이후 명시된 서비스 입력으로 AWS 접근 역할 준비

설정과 검증 절차는 [전체 실행 안내](../IMPLEMENTATION.md)를 따른다. platform(Kafka/Spark/Airflow)은 후속 작업이다.
