# Terraform modules

각 모듈은 스택에서 호출하며 직접 배포하지 않는다. provider와 backend는 호출 스택에서 설정한다. AWS provider는 기존 bootstrap과 같은 6.68.0 lock을 사용한다.

- [network](network/README.md): 2개 AZ의 public/app/db subnet, AZ별 NAT, S3 Gateway Endpoint
- [eks](eks/README.md): EKS Auto Mode와 cluster/node IAM 및 명시적 관리자 access entry
- [compute](compute/README.md): 사용자 정의 NodeClass/NodePool, 노드 타입·한도·자동 정리
- [rds](rds/README.md): 암호화된 private Multi-AZ PostgreSQL과 SG 및 subnet group
- [storage](storage/README.md): state와 분리된 데이터 S3, 버저닝·암호화·공개 차단·TLS 정책
- [ecr](ecr/README.md): WEB/WAS용 ECR 두 개, immutable tag·scan on push
- [apps](apps/README.md): Namespace·Pod Identity·ConfigMap 및 선택적 WEB/WAS·HTTPS ALB Ingress
- [workload-access](workload-access/README.md): 명시된 namespace/ServiceAccount·S3 prefix/action별 역할 및 Pod Identity association

입출력은 각 모듈의 variables.tf/outputs.tf 및 README를 참고한다. terraform-docs가 로컬에 없어 표를 수동 작성했다.
