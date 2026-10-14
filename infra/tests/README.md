# Terraform mock tests

AWS와 Kubernetes provider를 mock 처리하며 계정 인증 및 실제 리소스 생성 없이 plan의 구조와 실패 조건을 확인한다. [ha.tftest.hcl](ha.tftest.hcl)의 CIDR·리소스 이름은 테스트 전용이며 배포 기본값이 아니다. [compute.tftest.hcl](compute.tftest.hcl)은 노드 용량 증감/On-Demand/네트워크 연결을, [apps-sizing.tftest.hcl](apps-sizing.tftest.hcl)은 WAS 독립 증설과 잘못된 자원/replica 입력 거부를 검증한다. 실제 Kubernetes CRD admission 및 EKS 동작 검증은 별도다.

```powershell
terraform -chdir=infra/tests init -backend=false
terraform -chdir=infra/tests test
```

검사: AZ별 NAT 및 S3 경로, subnet 공개 IP 차단, CIDR 중복 거부, 타 리전 AZ 거부, RDS Multi-AZ/백업/보호/SG, S3 버전 및 공개 차단. 실제 AWS quota, 엔진 조합, IAM 권한, 앱·클러스터 동작은 보증하지 않는다. 모든 run은 `command = plan`이며 테스트에 state/backend는 없다.

[apps-connections.tftest.hcl](apps-connections.tftest.hcl)은 기존 1차 연결 계약을 검사한다. HTTPS/인증서·허용 CIDR, ALB→WEB→WAS의 Service/포트·프록시 정합성, WAS의 DB 설정/외부 Secret 참조·Pod Identity 및 S3 prefix 최소 권한을 확인한다. 이미지/TLS 입력 없는 기초 단계와 잘못된 배포 입력도 확인한다. 실제 앱 이미지·Secret·인증서의 존재나 DB/S3 연결 성공을 검증하는 테스트는 아니다.

[rds-cdc.tftest.hcl](rds-cdc.tftest.hcl)은 기본 비활성화·명시적 CDC 파라미터/DB 연결·잘못된 예산/버전을, [workload-access.tftest.hcl](workload-access.tftest.hcl)은 기본 역할 없음·서비스별 prefix/action/trust/association·wildcard/중복/endpoint 불일치 거부를 확인한다. [network-access.tftest.hcl](network-access.tftest.hcl)은 명시적 optional endpoint action과 output·정책 일치를 확인하고 기존 HA 테스트는 기본 endpoint 권한 유지를 확인한다. 수치는 테스트 fixture이며 실측 기반 설정이 아니다. 전체 7개 suite의 mock plan 36개와 10개 root 정적 검증을 통과했다. 실제 적용·SDK·성능/복구 검증은 별도다.
