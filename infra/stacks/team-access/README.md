# team-access stack

상태: 2026-10-19 실제 생성3개·사후 plan 변경 없음. 그룹 impersonation 허용3/거부5 검사 통과. 동료 본인 인증과 업무 앱 배포는 미검증이다. [실행 기록](../../../docs/tasks/infra-generator-was-access.md).

사용자 요청으로 Fargate 제네레이터와 EKS WAS를 함께 담당하는 동료에게 배포 접근을 연결한다. 이번 변경은 `clothes-query` namespace·EKS access entry·namespace RoleBinding만 관리한다. 도쿄의 기존 EKS·컴퓨트·DB·ALB 설정과 공유 IAM 그룹은 변경하지 않는다.

## 기존 권한과 실제 부여 범위

읽기 전용 사전 확인에서 제공된 IAM 사용자는 공통 지원 계정 그룹을 통해 ECS·ECR·IAM 등 광범위한 AWS 서비스 권한을 이미 받았다. ECS/ECR Allow 정책을 추가할 필요가 없다. 이 스택은 그 기존 권한을 제한하거나 제거하지 않으며, 이 사용자의 유효 권한 전체를 namespace로 격리했다고 주장하지 않는다. 특히 기존 AWS `eks:*`/`iam:*` 권한으로 접근 설정을 다시 변경할 수 있다. 공통 그룹 정책은 다른 사용자도 사용하므로 임의로 수정하지 않는다.

이 스택으로 추가하는 Kubernetes 권한은 다음과 같다.

- IAM user/role → EKS STANDARD access entry → `clothes-query:was-deployer` 그룹.
- `clothes-query` namespace에서 기본 Kubernetes `edit` ClusterRole을 RoleBinding으로 연결.
- WAS Deployment·Pod·Service·ConfigMap·Secret·Job 배포와 로그/exec/port-forward 등. namespace 내 Secret과 ServiceAccount 사용도 가능하므로 그 공간에 관리자나 채점용 자격증명을 두지 않는다.
- 이 RoleBinding으로는 Kafka/Airflow namespace, 노드, namespace 생성/삭제, ClusterRoleBinding, IAM·EKS 설정 관리 권한을 부여하지 않는다. 기존 IAM 정책에서 받은 AWS 권한은 별개다.

`edit`는 Ingress와 Service 변경도 허용하므로 동료가 LoadBalancer/Ingress를 배포하면 별도 ALB 등이 생성될 수 있다. 이번 적용에서는 그런 manifest·ALB를 만들지 않는다. 비용 발생 자원은 앞서 합의한 시점에 인프라 담당자와 plan을 확인한다.

## 네트워크와 후속 연결

동료는 현재 관리자와 같은 공인 IP 네트워크를 사용한다고 확인받았다. EKS public API의 기존 1개 허용 범위를 유지한다. 장소/출구 IP가 바뀌면 별도로 /32 허용을 검토한다. EKS 권한만으로 Fargate→ALB/WAS→RDS의 통신이 자동으로 열리지 않는다.

Fargate cluster/task·전용 Execution Role/Task Role·이미지·DB 계정·Secret·보안 그룹은 실제 앱 입력에 맞춰 연결한다. 현재 도쿄에 다른 팀원이 만든 review-simulator ECS/ECR이 있어 이 스택에서 재사용·수정하지 않는다. 제네레이터는 자기 전용 자원을 사용한다. 내부 ALB는 WAS API와 제네레이터 호출 준비 후 생성한다.

## 준비와 소유권

- 선행: 기존 bootstrap bucket·EKS state·관리자 Kubernetes 접속. `edit` ClusterRole이 존재해야 한다.
- state key: `clothes-query/dev/team-access/terraform.tfstate`.
- 비공개 입력: `expected_account_id`, `state_bucket`, `principal_arn` 및 기존 bucket/region의 `deployment.backend.hcl`.
- 기존 동명 namespace/access entry가 있다면 소유권을 먼저 확인하며 임의 import·덮어쓰기를 하지 않는다.
- `clothes-query` namespace 소유자는 이번 team-access state다. 아직 미배포인 기존 apps 모듈도 같은 namespace 생성을 가정하므로, **나중에 apps 스택을 사용할 때 namespace 재사용/소유권 처리를 먼저 구현·검토**한다. 동료가 manifest를 배포하는 현재 사용은 namespace 생성 없이 진행한다.

## 실행과 동료 인계

```powershell
terraform init -backend-config=deployment.backend.hcl -lockfile=readonly
terraform validate
terraform plan -var-file=deployment.local.tfvars.json -out=deployment.tfplan
```

신규3개·기존 자원 수정/삭제/교체0개인 계획만 적용한다. 실제 ARN·계정·endpoint를 포함한 plan/state는 비공개다. 원칙적으로 apply는 인프라 담당자가 수행하며, 이번 사용자 요청은 작업 지시서의 실제 권한 연결 특례를 따른다.

동료는 자신의 개인 인증 profile을 사용한다. 관리자 역할을 assume하거나 다른 사람 키를 받지 않는다.

```powershell
$env:AWS_PROFILE = '<동료 본인 프로필>'
$env:KUBECONFIG = Join-Path $env:TEMP 'clothes-query-was-kubeconfig'
aws eks update-kubeconfig --region ap-northeast-1 --name clothes-query-dev-eks --alias clothes-query-was
kubectl get pods -n clothes-query
kubectl auth can-i create deployments -n clothes-query
kubectl auth can-i get secrets -n kafka
```

namespace 내 배포는 yes, Kafka Secret 접근은 no가 기대값이다. kubeconfig에는 access key를 직접 넣지 않는다. ECR WAS 이미지는 기존 WAS 전용 repository를 사용하고, 다른 팀원의 repository에 push하지 않는다.

## 검증과 회수

EKS access entry의 신원·그룹을 확인하고, 관리자의 Kubernetes impersonation으로 해당 그룹의 WAS 배포 허용과 Kafka/Airflow·노드·RBAC 변경 거부를 검사한다. 이는 RBAC 검사이며 동료 본인 인증의 end-to-end kubectl 성공을 대신하지 않는다. 최종 접속은 동료가 확인한다.

접근 회수 시 access entry와 RoleBinding을 먼저 검토한다. namespace 삭제는 내부 WAS·Secret·PVC 등까지 삭제할 수 있으므로 운영 중에는 스택 전체 destroy를 실행하지 않는다. 다른 팀원의 자원과 기존 공통 그룹 권한은 그대로 유지한다.
