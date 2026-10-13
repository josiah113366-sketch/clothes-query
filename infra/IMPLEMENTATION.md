# 고가용성 Terraform 구현 및 실행 안내

상태: 코드 작성 및 로컬 검증 완료 · ECR만 사용자 요청으로 실배포 검증 완료 · 2026-10-13

## 최소 배포 검증 결과

사용자가 요청한 state 저장 테스트로 ECR 스택만 실행했다. 기존 이름/state 충돌을 확인한 후 저장한 plan(2 create, 0 change, 0 destroy)을 apply했다. 생성한 저장소는 `clothes-query-dev/web`, `clothes-query-dev/was`이며 이미지 push는 하지 않았다.

- S3 key `clothes-query/dev/ecr/terraform.tfstate` 저장 확인: 4,012 bytes, AES256 암호화, version ID 존재.
- 관리 리소스 2개, 후속 `plan -detailed-exitcode` 결과 0(no changes), S3 lock 해제 확인.
- AWS 인증 및 대상 계정/버킷 접근 확인 완료. 초기 제한된 실행 환경에서 인증이 보이지 않았던 문제는 해결됐다.
- 실제 계정 입력과 저장된 plan은 Git 제외 로컬 파일에만 보관했다. bootstrap 및 다른 스택은 apply하지 않았다.

아래의 인증/state 미확인 설명은 구현 시작 당시의 기록이며, 다른 스택의 배포 사양 및 bootstrap local state 관리 위치는 여전히 별도 확인 대상이다.

## 이번에 확정한 사항

사용자가 EKS Auto Mode와 고가용성을 선택했다. 도쿄/PostgreSQL을 유지하며 두 AZ 각각 NAT, private app/db subnet, Multi-AZ RDS, WEB/WAS 두 replica의 AZ 분산을 구현했다. 현재 브랜치는 사용자가 만든 `infra/analysis`를 유지한다. 원격 main은 작성 시작 시 로컬 기준 커밋 bbe9fae와 동일함을 확인했다.

기존 Terraform은 bootstrap뿐이고 사용자는 다른 팀원 환경에 배포되어 있을 것으로 설명했다. **기배포 여부와 소유 state는 아직 확인되지 않았다.** bootstrap은 변경하지 않았다. 실제 AWS에 추가 리소스가 있다면 이 코드를 바로 plan/apply하지 말고 소유 state/주소를 먼저 대조한다.

## 구성과 state 경계

`bootstrap 확인 → network → eks → compute → rds → apps`. storage와 ecr은 bootstrap 확인 후 독립적으로 준비할 수 있다. apps는 eks/compute/rds/storage의 remote state를 읽는다. EKS와 Kubernetes provider는 별도 state다. 기존 platform 역할을 앱 배포로 바꾸지 않았다. 현재 사용자 지시로 실제 생성 테스트는 마지막 준비 단계까지 보류한다.

- network: 2 AZ, 각 AZ NAT, public/app/db 분리, app S3 Gateway Endpoint. DB에 인터넷 기본 경로 없음.
- eks: Kubernetes 1.36 Auto Mode, 기본 NodePool 비활성화, custom node EC2 access entry/AutoNodePolicy, 명시적 관리자 access entry, API CIDR 제한, 30일 로그.
- compute: custom NodeClass/NodePool, 두 app subnet·cluster SG 명시, m6i.large/m7i.large On-Demand, 8 vCPU/32GiB 한도, 10분 consolidation 대기. 시스템과 앱이 공유한다.
- rds: PostgreSQL, Multi-AZ, 암호화, 백업 7일, 삭제 보호, master password는 RDS가 Secrets Manager에서 관리.
- storage: 업무 데이터 S3, 버저닝/SSE-S3/공개 차단/TLS 강제. bootstrap 버킷과 별개.
- ecr: WEB/WAS 저장소, immutable tag, 이미지 자동 삭제 없음.
- apps: Pod Identity로 지정 S3 prefix만 Get/Put/List, WEB/WAS Service와 Deployment, PDB 및 Auto Mode ALB.

각 스택의 backend는 기존 이름 관례의 고유 dev key를 가진다. bucket과 backend region은 비공개 `*.backend.hcl`에서 공급한다. 이는 새 스택에 대한 partial backend 구성이고 기존 bootstrap backend migration이 아니다. 리소스는 Terraform이 생성·관리하는 새 주소이므로 다른 state의 기존 자산과 자동 병합되지 않는다.

## 계정 및 state 확인

팀원에게 bootstrap 관리 PC/state 보관 위치, bucket/region, 사용 profile 또는 role, 이미 배포된 리소스 범위를 확인한다. state 파일을 이 공개 저장소에 복사하지 않는다. 계정 ID/ARN/endpoint는 비공개 입력에만 둔다.

모든 신규 AWS provider는 `expected_account_id`를 요구하고 `allowed_account_ids`로 다른 계정 실행을 차단한다. AWS profile 또는 역할 인증은 사용자 환경에서 설정한다. 앱 Kubernetes 인증도 AWS CLI를 사용하므로 Terraform AWS provider와 동일한 AWS_PROFILE/역할 세션이어야 한다.

## 입력 준비와 검증

각 스택의 `terraform.tfvars.example`을 `deployment.local.tfvars`로 복사한다. 예제 CIDR/용량은 샘플이지 사용자 승인된 실배포 값이 아니다. 버전·사양·AZ와 기존 네트워크의 충돌 여부를 먼저 확인한다.

필수 공통 환경변수는 `TF_VAR_expected_account_id`, 종속 스택은 `TF_VAR_state_bucket`이다. 리전이 다르면 backend와 remote state region도 담당자와 대조한다. AWS 비밀키를 tfvars에 넣지 않는다.

비공개 `deployment.backend.hcl`에는 아래 두 값만 실제 승인된 값으로 넣는다.

```hcl
bucket = "REPLACE_WITH_EXISTING_STATE_BUCKET"
region = "ap-northeast-1"
```

스택 폴더에서 정적 검사와 실제 plan을 구분한다.

```powershell
# 계정/backend 연결 없이 provider 및 문법 검증
terraform init -backend=false -lockfile=readonly
terraform fmt -check
terraform validate

# 기존 state 소유권과 AWS 인증 확인 후에만 실행
terraform init -backend-config=deployment.backend.hcl -lockfile=readonly
terraform plan -input=false -var-file=deployment.local.tfvars
```

기존 backend를 변경하거나 `-migrate-state`, import, state mv/rm을 실행하지 않는다. 실제 plan에서 기존 자산의 destroy/replace 또는 예상 외 생성이 보이면 중단하고 관리 주소를 대조한다. 사용자가 최종 plan을 검토한 후 apply한다. 새 스택의 선행 output이 아직 없으면 후속 plan부터 실행하지 않는다.

## WEB/WAS 두 단계 준비

1. AWS 선행 스택 준비 후 apps를 기본 `deploy_workloads=false`로 plan하고 승인 후 배포한다. Namespace, ServiceAccount, IAM 역할/권한, Pod Identity, ConfigMap 및 Metrics Server add-on을 준비한다. WEB/WAS Deployment·Service·Ingress·HPA는 만들지 않는다.
2. 앱 담당자가 PostgreSQL 앱 계정을 만들고 DB schema를 검토된 migration으로 적용한다. 해당 계정은 RDS master와 별개다. 만들어진 namespace에 `was-database` Secret을 승인된 비밀 공급 방식으로 준비한다. 키는 `DB_USER`, `DB_PASSWORD`다. Terraform에는 Secret 값을 넣지 않으며 비밀 값을 조회해 state에 저장하지 않는다. 회전 및 재시작 책임도 공급 도구/담당자에게 있다.
3. PostgreSQL/S3를 지원하는 WAS 이미지를 빌드해 ECR에 push한다. 기존 ZIP의 PyMySQL 앱은 그대로 사용할 수 없다. WAS 계약은 8000 포트, /health, /api/*, DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD, AWS_REGION/S3_BUCKET/S3_PREFIX 및 Pod Identity를 지원하는 AWS SDK 기본 자격증명 체인이다. DB 연결은 TLS 및 CA 검증을 앱에서 적용한다.
4. WEB 이미지는 nginx의 /etc/nginx/conf.d/default.conf를 사용하고 /usr/share/nginx/html에서 정적 파일을 제공해야 한다. ConfigMap이 /api/를 was-service:8000으로 프록시한다. 다른 웹 서버라면 이 계약을 먼저 수정한다.
5. 두 이미지 digest, 발급 완료된 같은 리전 ACM 인증서, hostname, 공개 허용 CIDR을 비공개 입력에 넣고 `deploy_workloads=true`로 plan한다. HTTPS 443만 구성한다. 도메인 DNS를 ALB에 연결하는 작업은 도메인 관리자가 별도로 수행한다.
6. 실제 rollout/ALB target health, WEB → WAS → PostgreSQL/S3, Pod 교체 및 AZ 장애 대응을 검증한다. 정적 validate 성공이나 foundation 배포 성공을 서비스 성공으로 기록하지 않는다.

S3 권한에는 삭제를 넣지 않았다. bronze/silver/gold 전체 권한을 WAS에 자동 부여하지 않고 `s3_prefix`만 허용한다. 테스트 객체 정리가 필요하면 담당자의 승인된 경로로 정리한다. ConfigMap 변경은 checksum으로 rollout을 유도하지만 외부 Secret 변경은 별도 rollout/회전 처리가 필요하다.

## 고가용성 및 비용 한계

AZ별 NAT는 1개 구성보다 NAT 시간/EIP 비용이 추가되고, Multi-AZ RDS는 Single-AZ보다 비용이 높다. 앱 replicas와 분산 조건은 두 AZ의 노드 용량을 요구한다. 승인된 초기 NodePool 한도는 8 vCPU/32GiB이며 고정 노드 수나 엄격한 요금 상한을 뜻하지 않는다. Generator 부하에 따른 Pod 수/자원과 풀 한도 변경은 [증설·축소 가이드](SCALING.md)를 따른다. WAS HPA(2~3개, CPU 70%, 축소 안정화 300초)와 Metrics Server를 코드로 준비했다. 실제 생성은 마지막에 진행한다.

기존 분석의 월 $200~400은 NAT 1개·Single-AZ 개발 가정이므로 이번 HA 구성에 적용할 수 없다. 노드/DB 사양·시간·LCU·전송량이 정해지면 도쿄 단가로 새 견적을 내야 한다. EKS 지원 버전은 STANDARD로 설정해 연장 지원 요금 대신 버전 수명주기 관리가 필요하다.

- [EKS/Auto Mode 가격](https://aws.amazon.com/eks/pricing/)
- [VPC/NAT 가격](https://aws.amazon.com/vpc/pricing/)
- [RDS PostgreSQL 가격](https://aws.amazon.com/rds/postgresql/pricing/)
- [Auto Mode ALB 설정](https://docs.aws.amazon.com/eks/latest/userguide/auto-configure-alb.html)
- [Auto Mode IAM](https://docs.aws.amazon.com/eks/latest/userguide/auto-cluster-iam-role.html)

고가용성 코드는 중단 시간 0을 보장하지 않는다. 앱의 DB failover 재연결, 읽기/쓰기 트랜잭션, 노드 배치와 PDB 동작은 통합 검증이 필요하다. custom NodeClass가 cluster SG를 선택하도록 하여 RDS 허용 SG와 일치시켰다. Pod 전용 SG를 도입하면 함께 수정한다.

## 검증 결과와 남은 작업

bootstrap 및 초기 6개 스택 validate에 이어 compute 추가와 eks/apps 변경을 검증했다. 신규 코드 fmt와 AWS/Kubernetes mock plan 검증도 수행한다. mock 테스트는 실제 리소스를 생성하지 않는다. 결과는 [작업 기록](../docs/tasks/infra-analysis.md)에 기록한다. network 미배포로 선행 state가 없으며, EKS/CRD도 아직 없어 eks/compute/apps의 실환경 plan은 현재 실행할 수 없다. 이를 위해 가짜 state나 실제 리소스를 만들지 않는다.

2026-10-14 후속 검토에서 빈 인증서·공백 hostname의 배포 입력 검증을 보완하고 기존 연결 계약 테스트를 추가했다. 9개 root의 정적 검사와 총 24개 mock plan을 통과했다. 상세와 미검증 범위는 [1차 연결 검증 기록](../docs/tasks/infra-first-stage-checks.md)을 참고한다.

기존 작업 기록에서 ECR은 실제 plan/apply와 S3 backend 저장을 검증했고, network는 23개 생성·변경/삭제 없음의 실제 plan까지만 확인했다. 다른 스택의 실환경 plan과 ECR 이외 배포는 미실행이다. network 상세는 [배포 전 검토](../docs/design/infra/network-plan.md)를 따른다. 이 내용은 기존 기록이며 이 PC에서 AWS를 재조회한 결과가 아니다. 앱 소스 수정/이미지 빌드/DB 계정·Secret 공급/DNS는 별도 선행 작업이다. bootstrap lock/state는 변경하지 않았다.

삭제는 앱과 ALB → 종속 스택 → eks → network 순서를 검토하되 RDS/데이터 S3/state S3는 보호되어 있다. 삭제 보호를 자동 해제하거나 테스트 목적으로 전체 destroy하지 않는다.
