# 현재 배치 구성

상태: 결정 · 2026-10-14 사용자 정정 반영. **RDS만 Single-AZ이며 VPC·EKS는 기존 두 AZ 구성을 유지한다.**

| 구성 | 현재 설정 |
|---|---|
| 리전 / AZ | 도쿄 / ap-northeast-1a, ap-northeast-1c |
| network | 두 AZ 각각 public/app/db subnet, NAT/EIP 각각 2개 |
| app 기본 경로 | 각 AZ의 NAT 사용, S3 Gateway Endpoint 공유 |
| EKS compute | 두 app subnet에 배치 가능, m6i.large/m7i.large, On-Demand |
| 노드 풀 상한 | 8 vCPU / 32 GiB 유지 |
| EKS 관리자 | 전용 역할, 현재 사용자·현재 PC /32부터 시작, 팀원은 추후 추가 |
| WEB / WAS | WEB 2개, WAS HPA 2~3개, zone spread minDomains=2 |
| Kafka | 기본 비활성, 활성화 시 broker/controller 3개를 두 AZ·서로 다른 호스트에 배치, broker당 EBS gp3 20 GiB(총 60 GiB), 초기 보관 24시간 |
| RDS | PostgreSQL 16.15, Single-AZ, 기본 배치 ap-northeast-1a, 크기·저장량 미정 |

RDS의 위치는 `stacks/rds` 입력 `database_availability_zone`으로 바꿀 수 있으며 network의 AZ 중에서 선택한다. DB subnet group은 두 AZ의 subnet을 유지하지만 standby DB를 만들지 않는다. DB AZ 장애 시 standby failover는 없다. 암호화·백업·삭제 보호는 유지한다.

Kafka는 replicas=3/RF=3/min ISR=2를 유지한다. 두 AZ 중 한쪽에 controller 두 개가 배치되므로 그 AZ 장애까지 견디는 quorum 구성은 아니다. 두 AZ 사용이 모든 구성요소의 AZ 장애 극복을 보장하지 않는다.

`SINGLE_AZ.md`의 전체 단일 AZ 계획과 NAT 1개·21개 생성 plan은 사용자 정정으로 폐기된 과거 검토다. 저장된 plan을 apply하지 않는다. 최종 배포 전에 현재 코드로 network plan을 새로 생성하고 나머지 스택도 선행 output에 맞춰 검토한다.

DB 크기 결정 및 실제 리소스 생성 테스트는 계속 보류한다. Kafka/Connect, CDC 논리 복제, workload-access bindings, Connect ECR의 기본 비활성 설정도 유지한다.

업무 S3 clothes-query-datalake는 사용자 별도 승인으로 도쿄에 생성했다. 내부는 비어 있으며 경로는 미정이다. 앱·도메인/HTTPS는 보류했고 DB→Kafka 캡처 범위·업무 토픽은 팀원에게 받을 항목으로 남겼다. [입력 목록](../docs/design/infra/team-inputs.md)을 참고한다.
