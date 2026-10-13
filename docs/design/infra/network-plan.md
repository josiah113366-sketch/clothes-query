# Network 배포 전 검토

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
