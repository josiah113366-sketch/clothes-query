# 현재 배치 구성

2026-10-16 실행 결과: 비용 절감을 위해 RDS와 필요한 네트워크만 생성 완료. 비공개 입력에서 NAT를 비활성화하고 EKS state 참조를 끈다. EKS·compute·Kafka는 미배포다. [RDS-first](../docs/tasks/infra-rds-first.md).

2026-10-16 후속 변경: 향후 NAT 활성화 시 2개 대신 **한 개 공유**를 기본으로 사용한다. 두 AZ subnet은 유지한다. 현재 실제 NAT는 계속 0개다.

상태: 결정 · 2026-10-16 최소 운영 반영. **두 AZ subnet을 유지하지만 단일 노드 Kafka의 AZ 장애 시 중단을 허용한다.**

| 구성 | 현재 설정 |
|---|---|
| 리전 / AZ | 도쿄 / ap-northeast-1a, ap-northeast-1c |
| network | 두 AZ 각각 public/app/db subnet, 현재 NAT/EIP 0개·향후 활성화 시 각각 1개 공유 |
| app 기본 경로 | 현재 인터넷 기본 경로 없음. 향후 NAT 공유, S3 Gateway Endpoint는 유지 |
| EKS compute | 두 private app subnet에 배치 가능, t3a.large, On-Demand, Auto Mode 유지 |
| 노드 풀 상한 | 6 vCPU / 24 GiB(세 대분), 평소 한 대 배치 목표·실환경 미검증 |
| EKS 관리자 | 전용 역할, 현재 사용자·현재 PC /32부터 시작, 팀원은 추후 추가 |
| WEB / WAS / ALB / Spark | 이번 최소 배포에서 제외. 기존 앱 기본값은 별도 보존 |
| Kafka | 기본 비활성. 최소 배포 시 single-node 프로필로 broker/controller 1개·Connect 1개·RF 1·gp3 20 GiB·72시간, 업무 토픽 retentionMs=259200000 명시 |
| 제네레이터 | 팀원이 별도 ECS Fargate로 구성 예정. 같은 VPC에서 RDS·S3에 접근 |
| RDS | PostgreSQL 16.15, db.t4g.small, Single-AZ, 기본 배치 ap-northeast-1a, gp3 초기 20 GiB / 자동 증가 최대 100 GiB |

RDS의 위치는 `stacks/rds` 입력 `database_availability_zone`으로 바꿀 수 있으며 network의 AZ 중에서 선택한다. DB subnet group은 두 AZ의 subnet을 유지하지만 standby DB를 만들지 않는다. DB AZ 장애 시 standby failover는 없다. 암호화·백업·삭제 보호는 유지한다.

single-node 프로필은 RF=1/min ISR=1이며 broker 또는 해당 AZ 장애 시 Kafka가 중단된다. 노드 자동 확장은 broker 복제 수를 늘리지 않는다. 기존 standard 프로필의 replicas=3/RF=3/min ISR=2·두 AZ 배치는 보존하지만 최소 배포에서 선택하지 않는다. NodePool 한도는 엄격한 노드 수/요금 상한이 아니며 모든 워크로드가 한 대에 수용된다는 보장은 없다.

`SINGLE_AZ.md`의 전체 단일 AZ 계획과 NAT 1개·21개 생성 plan은 사용자 정정으로 폐기된 과거 검토다. 저장된 plan을 apply하지 않는다. 최종 배포 전에 현재 코드로 network plan을 새로 생성하고 나머지 스택도 선행 output에 맞춰 검토한다.

DB는 db.t4g.small로 생성 완료했다. Kafka/Connect, CDC 논리 복제, workload-access bindings, Connect ECR의 기본 비활성 설정은 유지한다.

업무 S3 clothes-query-datalake는 사용자 별도 승인으로 도쿄에 생성했다. 내부는 비어 있으며 경로는 미정이다. 앱·도메인/HTTPS는 보류했고 DB→Kafka 캡처 범위·업무 토픽은 팀원에게 받을 항목으로 남겼다. [입력 목록](../docs/design/infra/team-inputs.md)을 참고한다.
