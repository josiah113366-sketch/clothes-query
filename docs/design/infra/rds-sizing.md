> **현재 구성(2026-10-14):** 이전 HA 결정을 변경했다. 워커·앱·RDS는 ap-northeast-1a 한 AZ, NAT 1개, RDS Single-AZ다. AWS 서비스 요구사항 때문에 두 AZ의 서브넷은 유지한다. WEB 2개/WAS HPA 2~3개는 유지한다. 아래의 이전 HA 설명보다 infra/SINGLE_AZ.md의 최신 결정을 우선한다.

# RDS 시작 사양 검토

최신 상태: **인스턴스 크기 결정 보류** (사용자 요청, 2026-10-14). PostgreSQL 16.15·Single-AZ는 유지한다. micro 또는 스탠다드 어느 쪽도 확정하지 않았으며 Terraform의 `instance_class`는 필수 입력으로 남긴다. 아래 Multi-AZ 비교는 과거 검토다.

최종 비교 기록: 도쿄 PostgreSQL 16.15·Single-AZ, 월 730시간 + gp3 20 GiB 기준 `db.t4g.micro`(2 vCPU/1 GiB)는 $21.01, 지원되는 최소 스탠다드 크기 중 최저가 후보 `db.m6g.large`(2 vCPU/8 GiB)는 $164.09였다. 추가 사용료·세금은 제외하며 향후 결정 시 지원 여부와 요금을 다시 확인한다.

상태: PostgreSQL 16 결정 / 인스턴스 크기 미정 · 2026-10-14. 사용자는 17 대신 16을 선택하고 medium보다 작은 크기 재검토를 요청했다. 아래 기존 medium 검토는 비교 자료로 남긴다. 실제 생성은 수행하지 않았다.

## 최신 결정과 작은 사양 비교

도쿄 AWS API에서 PostgreSQL 16.15와 db.t4g.micro/small/medium 모두 Multi-AZ·gp3 최소 20 GiB 지원을 확인했다. Terraform 공통 입력과 예제에 16.15를 반영했고 인스턴스 크기는 미정으로 유지했다.

월 730시간, Multi-AZ 인스턴스와 gp3 20 GiB($5.52/월) 합계다. CPU credit, 추가 백업, 전송, Secrets Manager, 세금은 제외한다.

| 클래스 | vCPU / 메모리 | Multi-AZ 시간당 | 월 합계 |
|---|---|---|---|
| db.t4g.micro | 2 / 1 GiB | $0.050 | $42.02 |
| db.t4g.small | 2 / 2 GiB | $0.101 | $79.25 |
| db.t4g.medium | 2 / 4 GiB | $0.202 | $152.98 |

메모리는 인스턴스 한 대 기준이며 standby 메모리를 primary 처리에 합산하지 않는다. 세 클래스 모두 burstable이므로 vCPU 수가 같아도 지속 처리 성능이 같다는 의미는 아니다.

제안: 연결·저부하 실습부터 시작하는 비용 우선 선택은 micro다. WAS 연결과 향후 CDC를 함께 시험할 여유를 원하면 small을 고려한다. 충분한 성능은 아직 검증되지 않았다. 부하 시험에서 FreeableMemory, SwapUsage, CPU credit, DB 연결 수, 쓰기 지연을 측정해 증설한다. HPA가 DB 클래스를 자동 변경하지는 않는다. 클래스 변경은 서비스 영향과 plan을 별도로 검토한다.

이하 PostgreSQL 17 시작안은 사용자의 16 선택으로 대체된 과거 검토다.

## 후보와 지원 확인

- PostgreSQL 17 계열, db.t4g.medium, Multi-AZ DB instance, gp3 초기 20 GiB / 자동 증가 상한 100 GiB.
- 도쿄 AWS `describe-orderable-db-instance-options` 조회에서 위 클래스의 Multi-AZ·gp3 및 PostgreSQL 17.5~17.11 항목이 반환됐다. 최소 저장량은 20 GiB다. 정확한 minor는 배포 전 지원·패치 상태를 다시 확인해 고정한다.
- 현재 로컬 개발 환경은 PostgreSQL 16이다. 17 채택 전 앱·migration·향후 Debezium 지원 조합을 확인해야 한다. 이 검토를 이유로 로컬 DB나 팀원 코드를 변경하지 않는다.

## 비용

AWS 공식 도쿄 가격 목록(publicationDate 2026-10-06)에서 PostgreSQL Multi-AZ 항목을 조회했다. 월 730시간, 온디맨드 USD 기준이다.

| 항목 | 단가 | 월 예상 |
|---|---|---|
| db.t4g.medium Multi-AZ | $0.202/시간 | $147.46 |
| gp3 20 GiB Multi-AZ | $0.276/GB-month | $5.52 |
| 초기 합계 | 인스턴스 + 기본 저장량 | **$152.98** |
| 저장량이 실제 100 GiB까지 증가한 경우 | $147.46 + $27.60 | **$175.06** |

위 단가는 Multi-AZ를 포함하므로 standby 비용을 다시 2배로 계산하지 않는다. 자동 증가 상한 100 GiB를 설정했다고 처음부터 100 GiB 저장료가 붙는 것은 아니다. 백업 초과분, 전송, CPU credit, Secrets Manager, 세금 등은 제외했다. 전체 EKS/NAT/S3 비용도 별도다.

T4g는 CPU credit 기반이다. 지속적인 부하 생성으로 baseline을 넘는 경우 추가 credit 요금이 생길 수 있으므로 지속 부하에는 고정 성능 클래스와 비교해야 한다. [RDS PostgreSQL 가격](https://aws.amazon.com/rds/postgresql/pricing/), [AWS 공식 도쿄 가격 JSON](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonRDS/current/ap-northeast-1/index.json)

## 판단

간헐적인 실습과 초기 부하 측정의 시작안으로 검토할 수 있다. 충분한 처리량은 보장하지 않는다. HPA가 WAS를 늘리면 DB 연결 수도 늘 수 있으므로 Pod별 연결 풀 상한과 관리·migration 연결 여유를 함께 정한다.

고가용성 결정은 유지한다. 정확한 PostgreSQL 버전, 로컬 16과의 차이 처리, 사양과 월 비용을 확정한 다음 Terraform 입력에 반영한다. 현재 placeholder는 유지하며 apply하지 않았다.
