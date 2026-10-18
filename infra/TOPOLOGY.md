# 현재 배치 구성

2026-10-16 실행 결과: RDS 선행 배포에 이어 PR #11 머지 후 NAT/EKS/compute/Kafka 최소 측정 환경을 생성했다. [실제 배포 결과](../docs/tasks/infra-deploy-result.md).

2026-10-18에는 실제 RDS → Kafka → S3 연결·CDC 중단 후 이어받기를 시험하고 더미 데이터와 시험 런타임/권한을 정리했다. RDS 논리 복제 설정과 데이터 없는 Connect ECR 이미지는 유지한다. [시험·정리 결과](../docs/tasks/infra-pipeline-smoke.md).

NAT는 두 개 대신 **한 개 공유**로 생성 완료했다. 두 AZ subnet은 유지하며 현재 t3a.large 노드/Kafka는 ap-northeast-1a에 있다.

상태: 결정 · 2026-10-16 최소 운영 반영. **두 AZ subnet을 유지하지만 단일 노드 Kafka의 AZ 장애 시 중단을 허용한다.**

| 구성 | 현재 설정 |
|---|---|
| 리전 / AZ | 도쿄 / ap-northeast-1a, ap-northeast-1c |
| network | 두 AZ 각각 public/app/db subnet, NAT/EIP 각 1개 공유 |
| app 기본 경로 | 두 app subnet에서 동일 NAT 사용. S3 Gateway Endpoint 유지. DB subnet은 외부 기본 경로 없음 |
| EKS compute | 1.36 Auto Mode ACTIVE, private t3a.large On-Demand 1대 Ready, ap-northeast-1a |
| 노드 풀 상한 | 6 vCPU / 24 GiB(세 대분), Kafka+시험 Connect 한 대 실행 확인·전체 플랫폼 수용 미검증 |
| EKS 관리자 | 전용 역할, 현재 사용자·현재 PC /32부터 시작, 팀원은 추후 추가 |
| WEB / WAS / ALB / Spark | 이번 최소 배포에서 제외. 기존 앱 기본값은 별도 보존 |
| Kafka | single-node+measurement 프로필 배포: broker/controller 1개·RF 1·암호화 gp3 20GiB·72시간, synthetic 토픽·TLS·JMX/lag. Connect 비활성 |
| Airflow | namespace만 생성, runtime·동료 권한은 후속 |
| 제네레이터 | 팀원이 별도 ECS Fargate로 구성 예정. 같은 VPC에서 RDS·S3에 접근 |
| RDS | PostgreSQL 16.15, db.t4g.small, Single-AZ, 기본 배치 ap-northeast-1a, gp3 초기 20 GiB / 자동 증가 최대 100 GiB |
| CDC 기반 | RDS 논리 복제 활성, 시험 계정/publication/slot·Connect는 제거. 업무 계약은 후속 |
| ECR | WEB/WAS/Connect 저장소3개, Connect 이미지 push·실제 EKS pull 확인 |

RDS의 위치는 `stacks/rds` 입력 `database_availability_zone`으로 바꿀 수 있으며 network의 AZ 중에서 선택한다. DB subnet group은 두 AZ의 subnet을 유지하지만 standby DB를 만들지 않는다. DB AZ 장애 시 standby failover는 없다. 암호화·백업·삭제 보호는 유지한다.

single-node 프로필은 RF=1/min ISR=1이며 broker 또는 해당 AZ 장애 시 Kafka가 중단된다. 노드 자동 확장은 broker 복제 수를 늘리지 않는다. 기존 standard 프로필의 replicas=3/RF=3/min ISR=2·두 AZ 배치는 보존하지만 최소 배포에서 선택하지 않는다. NodePool 한도는 엄격한 노드 수/요금 상한이 아니며 모든 워크로드가 한 대에 수용된다는 보장은 없다.

`SINGLE_AZ.md`의 전체 단일 AZ 계획과 NAT 1개·21개 생성 plan은 사용자 정정으로 폐기된 과거 검토다. 저장된 plan을 apply하지 않는다. 최종 배포 전에 현재 코드로 network plan을 새로 생성하고 나머지 스택도 선행 output에 맞춰 검토한다.

DB는 db.t4g.small로 생성 완료했다. Kafka는 최소 측정 배포를 유지하고 Connect와 workload-access bindings는 시험 후 비활성/빈 상태다. 실배포 비공개 입력은 RDS 논리 복제 활성·Connect ECR 활성으로 기록했다. 기본 예시로 덮어쓰지 않는다.

업무 S3 clothes-query-datalake는 사용자 별도 승인으로 도쿄에 생성했다. 이번 실행별 시험 경로는 모든 버전까지 정리했고 업무 데이터·형식/경로는 팀 계약을 따른다. 앱·도메인/HTTPS는 보류했고 DB→Kafka 캡처 범위·업무 토픽은 팀원에게 받을 항목으로 남겼다. [입력 목록](../docs/design/infra/team-inputs.md)을 참고한다.
