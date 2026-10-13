# Terraform mock tests

AWS와 Kubernetes provider를 mock 처리하며 계정 인증 및 실제 리소스 생성 없이 plan의 구조와 실패 조건을 확인한다. [ha.tftest.hcl](ha.tftest.hcl)의 CIDR·리소스 이름은 테스트 전용이며 배포 기본값이 아니다. [compute.tftest.hcl](compute.tftest.hcl)은 노드 용량 증감/On-Demand/네트워크 연결을, [apps-sizing.tftest.hcl](apps-sizing.tftest.hcl)은 WAS 독립 증설과 잘못된 자원/replica 입력 거부를 검증한다. 실제 Kubernetes CRD admission 및 EKS 동작 검증은 별도다.

```powershell
terraform -chdir=infra/tests init -backend=false
terraform -chdir=infra/tests test
```

검사: AZ별 NAT 및 S3 경로, subnet 공개 IP 차단, CIDR 중복 거부, 타 리전 AZ 거부, RDS Multi-AZ/백업/보호/SG, S3 버전 및 공개 차단. 실제 AWS quota, 엔진 조합, IAM 권한, 앱·클러스터 동작은 보증하지 않는다. 모든 run은 `command = plan`이며 테스트에 state/backend는 없다.
