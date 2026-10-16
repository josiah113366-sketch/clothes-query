> **최신 결정(2026-10-14): RDS만 Single-AZ.** VPC·EKS는 두 AZ, NAT는 AZ별 1개씩 총 2개, WEB/WAS와 Kafka는 두 AZ 분산을 유지한다. 전체 단일 AZ 설명과 NAT 1개 plan은 이전 오해에 따른 과거 기록이며 현재 배포 기준이 아니다. 최신 구성은 infra/TOPOLOGY.md를 따른다.

# 단일 AZ 워크로드 구성

상태: 결정 · 2026-10-14. 사용자가 기존 고가용성 결정을 변경하여 실제 워크로드를 한 AZ로 줄였다. 이전 HA 문서와 23개 생성 network plan은 현재 배포 기준이 아니다.

## 반영 내용

- network의 `workload_az` 기본값은 `ap-northeast-1a`다. NAT/EIP는 해당 AZ에 각각 1개만 만든다. 두 app route table은 이 NAT를 사용한다.
- compute는 network의 `workload_subnet_ids`와 `workload_az`만 받아 워커를 한 AZ에 배치한다.
- WEB/WAS zone spread의 `min_domains`는 1이다. WEB 2개 및 WAS HPA 2~3개, 노드 anti-affinity는 유지한다. **AZ 1개는 노드 1대라는 뜻이 아니다.** 노드 풀 8 vCPU/32 GiB 한도도 유지하며 부하와 배치에 따라 실제 수가 결정된다.
- RDS는 `multi_az=false`이며 같은 workload AZ에 배치한다. PostgreSQL 16.15, 인스턴스 크기는 아직 미정이다. 암호화·백업·삭제 보호는 유지한다.
- AZ 장애 시 워커·앱·DB는 다른 AZ로 자동 복구되는 구성이 아니다.

## 두 번째 AZ의 서브넷을 남기는 이유

EKS 생성에는 두 AZ의 서브넷이 필요하고 관리형 control plane을 단일 AZ로 바꿀 수 없다. ALB에도 두 AZ의 public subnet이 필요하다. Single-AZ RDS라도 DB subnet group에는 두 AZ의 subnet을 요구한다. 따라서 기존 a/c의 public/app/db subnet은 유지한다. c에는 워커·NAT·RDS standby를 만들지 않는다. ALB 및 EKS 관리용 네트워크 인터페이스는 c에도 존재할 수 있다.

- [EKS 요구사항](https://docs.aws.amazon.com/eks/latest/userguide/network-reqs.html)
- [ALB 요구사항](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/application-load-balancers.html)
- [RDS subnet group 요구사항](https://docs.aws.amazon.com/AmazonRDS/latest/APIReference/API_CreateDBSubnetGroup.html)

## DB 재조회 결과

2026-10-14 도쿄 API에서 PostgreSQL 16.15, gp3, db.t4g.micro/small의 a/c/d 지원을 확인했다. 월 730시간, Single-AZ 인스턴스와 20 GiB 저장소만 계산했다.

| 크기 | vCPU / 메모리 | 시간당 | 월 인스턴스 + 저장소 |
|---|---|---|---|
| db.t4g.micro | 2 / 1 GiB | $0.025 | **$21.01** |
| db.t4g.small | 2 / 2 GiB | $0.050 | **$39.26** |

gp3는 $0.138/GB-month이므로 20 GiB는 $2.76/월이다. CPU credit, 추가 백업, 전송, Secrets Manager, 세금과 다른 서비스 비용은 제외했다. 정확한 원화 비용은 결제 환율에 따라 다르다. [AWS 도쿄 공식 가격 JSON](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonRDS/current/ap-northeast-1/index.json)

크기는 이번 AZ 변경과 별도로 선택한다. 가장 작은 지원 후보는 micro이며 실제 처리량은 실측해야 한다. 기존 HA 사양·비용을 그대로 적용하지 않는다. 현재는 fmt/validate/mock plan 검증만 수행하며 실제 리소스 생성은 마지막에 진행한다. 최종 배포 전 network plan을 새로 생성하고 종속 state 출력도 새 코드와 맞춘다.
