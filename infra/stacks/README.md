# 배포 스택

- [bronze-lag-collector](bronze-lag-collector/README.md): eks/storage 이후, v2 지연 수집기 독립 AWS 기반. 별도 key를 사용하며 기존 workload-access를 덮어쓰지 않음

기존 bootstrap은 보존한다. 이번 구현은 dev 환경이며 backend key와 리소스 이름이 dev로 고정되어 있다. 다른 환경에는 새 key/이름 설계를 먼저 검토한다.

- [network](network/README.md)
- [eks](eks/README.md)
- [compute](compute/README.md)
- [spark-access](spark-access/README.md): eks/storage/network 이후 독립 state. namespace 확정 전 enabled=false로 유지한다.
- [rds](rds/README.md)
- [storage](storage/README.md)
- [ecr](ecr/README.md)
- [dashboard](dashboard/README.md): 대시보드 이미지 저장소(ECR). 별도 state
- [dashboard-access](dashboard-access/README.md): 기존 승인 화면 역할·Pod Identity·전용 workgroup과 패치노트 읽기. 별도 state
- [apps](apps/README.md)
- [workload-access](workload-access/README.md): network/eks/storage 이후 명시된 서비스 입력으로 AWS 접근 역할 준비
- [gold-b-access](gold-b-access/README.md): network/eks/storage 이후 판정·조사 역할과 전용 Athena workgroup (조회용 자원 적용 완료)
- [ecs-simulator](ecs-simulator/README.md): 거래·회원 시뮬레이터 Fargate 태스크 1개(컨테이너 3개)
- [team-access](team-access/README.md): 기존 EKS 이후 동료 WAS 배포 접근과 namespace 준비

설정과 검증 절차는 [전체 실행 안내](../IMPLEMENTATION.md)를 따른다. platform(Kafka/Spark/Airflow)은 후속 작업이다.
