> **현재 구성(2026-10-14):** 이전 HA 결정을 변경했다. 워커·앱·RDS는 ap-northeast-1a 한 AZ, NAT 1개, RDS Single-AZ다. AWS 서비스 요구사항 때문에 두 AZ의 서브넷은 유지한다. WEB 2개/WAS HPA 2~3개는 유지한다. 아래의 이전 HA 설명보다 infra/SINGLE_AZ.md의 최신 결정을 우선한다.

# Network 배포 전 검토

## 최신 검토: NAT 1개 구성 (2026-10-14)

실제 S3 backend 및 비공개 입력으로 network plan을 다시 실행했다. `fmt -check`, `validate`, backend init이 통과했고 plan 종료 코드 2는 변경 계획이 있음을 뜻한다.

- **21개 생성, 0개 변경, 0개 삭제, 교체 없음.** 아직 apply하지 않았다.
- NAT 1개와 EIP 1개는 a에만 생성한다. 이전 23개 생성 계획에서 c의 NAT/EIP 예정 리소스가 빠졌다. 기존 자산을 삭제하는 계획은 아니다.
- public/app/db subnet은 a/c에 총 6개 유지한다. route table 4개, association 6개, VPC/IGW/S3 Gateway Endpoint 각 1개다.
- 두 app route table은 단일 NAT를 참조한다. workload AZ 출력은 `ap-northeast-1a`다.
- 계획 파일은 `infra/stacks/network/network-single-az-review.tfplan`에 저장했고 Git 제외를 확인했다. 이전 `network-review.tfplan`은 사용하지 않는다. 실제 배포 시점에는 다시 plan을 생성·검토한다.
- 이 검토는 network 스택만 대상으로 한다. EKS/compute/RDS/apps의 실환경 plan 및 연결 검증을 대신하지 않는다.

아래는 이전 2-NAT 구성의 검토 기록이다.

상태: 주소 구성 결정 / plan 검증 완료 / apply 대기 · 2026-10-13

사용자가 VPC `10.70.0.0/16`과 아래 서브넷 구성을 승인했다. 대상 계정 도쿄 리전의 기존 VPC 대역은 `10.0.0.0/16`으로 겹치지 않았고, 기존 VPC에는 clothes-query 소유권을 나타내는 태그가 없었다. 기존 VPC는 이번 plan의 관리 대상이 아니다. 이 검사는 조회 계정·리전에 한정되며 외부 회사망/VPN 대역을 확인한 것은 아니다.

| 용도 | ap-northeast-1a | ap-northeast-1c |
|---|---|---|
| Public | 10.70.0.0/24 | 10.70.1.0/24 |
| Private App | 10.70.16.0/20 | 10.70.32.0/20 |
| Private DB | 10.70.64.0/24 | 10.70.65.0/24 |

두 AZ의 사용 가능 상태와 network state 경로에 기존 객체/잠금이 없음을 확인했다. 확정 입력은 Git 제외 `infra/stacks/network/deployment.local.tfvars.json`에 저장했다. 실제 계정 ID나 인증정보는 이 문서에 포함하지 않는다.

## 실제 plan 결과

S3 backend 초기화 후 `network-review.tfplan`을 저장하고 JSON으로 생성/변경/삭제를 검사했다. **23 create, 0 update, 0 delete/replace**다.

| 리소스 | 개수 |
|---|---:|
| VPC | 1 |
| Internet Gateway | 1 |
| Subnet | 6 |
| NAT Gateway | 2 |
| Elastic IP | 2 |
| Route Table | 4 |
| Route Table Association | 6 |
| S3 Gateway Endpoint | 1 |

## 배포 시 비용

도쿄 NAT의 시간당 $0.062와 공인 IPv4의 시간당 $0.005를 적용하면 NAT 2개/EIP 2개의 고정 비용은 `2 × (0.062 + 0.005) × 730 = $97.82/월`이다. 24시간 기준 약 $3.22다. 트래픽이 없어도 발생하며 NAT 처리량(도쿄 $0.062/GB), 별도 전송료, 세금은 제외한다. EKS/RDS/ALB 비용도 포함하지 않는다.

근거: [AWS 도쿄 NAT 요금 설명](https://aws.amazon.com/cn/blogs/china/amazon-vpc-regional-nat-gateway-az-nat-gateway-comparison/), [AWS VPC 공인 IPv4 요금](https://aws.amazon.com/vpc/pricing/).

이번 실행에서는 apply하지 않았다. 사용자가 생성과 비용을 승인하면 저장된 plan 및 변경 여부를 재확인하여 배포하고 subnet/route/NAT 가용 상태와 후속 no-change plan, S3 state 저장을 검증한다.
