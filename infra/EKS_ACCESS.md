# EKS 관리자 접속 준비

상태: 본인 관리자 접속 검증 완료 / 동료 WAS namespace 배포 권한 연결 완료 · 2026-10-19

## 동료 WAS 배포 접근 — 2026-10-19

사용자 요청으로 제네레이터와 WAS 담당 동료의 IAM 신원을 EKS STANDARD access entry와 `clothes-query:was-deployer` 그룹으로 연결했다. `clothes-query` namespace의 RoleBinding은 기본 `edit` ClusterRole을 사용한다. cluster-admin이나 기존 관리자 역할 trust는 추가하지 않았다. 같은 공인 IP 네트워크를 사용한다고 확인받아 기존 public API 허용 범위1개를 유지했다.

실제 namespace/access entry/RoleBinding 생성3개·수정/삭제0개, 사후 plan 변경 없음. 그룹 impersonation으로 WAS 배포/로그/Secret 허용 및 Kafka/Airflow/노드/관리자 권한 변경 거부를 확인했다. 동료 본인 AWS 인증으로의 kubectl 확인은 아직 남았다. 동료의 기존 공통 지원 계정 그룹은 광범위한 ECS/ECR/IAM 권한을 이미 제공하고 있으며 이번 RBAC가 그 AWS 권한까지 제한하지 않는다.

동료는 본인 AWS profile로 `aws eks update-kubeconfig --region ap-northeast-1 --name clothes-query-dev-eks` 후 `kubectl get pods -n clothes-query`로 확인한다. [전체 인계](stacks/team-access/README.md), [적용 기록](../docs/tasks/infra-generator-was-access.md). Airflow 설치 권한은 이번 대상이 아니다. 아래는 기존 관리자 접속의 준비/추가 절차다.

같은 날 사용자의 권한 확대 요청으로 운영 조회 ClusterRole/Binding을 추가했다. `kubectl get nodes`, `kubectl get pods -A` 및 Kafka/Airflow 실행 상태·로그 조회를 허용한다. WAS 배포 권한은 유지하며 다른 namespace Secret·exec, node proxy·노드 삭제·클러스터 RBAC 변경은 추가하지 않는다. 기존 공통 IAM의 AWS 권한은 별개다.

## 현재 준비한 것

- EKS 스택이 전용 역할 clothes-query-dev-eks-admin을 생성했고 실제 assume 및 kubectl 접속을 확인했다.
- admin_trusted_principal_arns에 명시된 IAM 사용자/역할만 이 역할을 assume할 수 있다. root·와일드카드·STS session ARN은 입력 검증에서 거부한다.
- 역할의 AWS 권한은 해당 클러스터의 eks:DescribeCluster로 제한한다. Kubernetes 관리 권한은 EKS access entry와 AmazonEKSClusterAdminPolicy로 부여한다.
- 현재 사용자 ARN과 현재 공인 IPv4 /32는 stacks/eks/deployment.local.tfvars.json에만 저장했다. 계정·bucket 입력도 비공개이며 비밀키는 저장하지 않았다. 공인 IP는 배포 직전 다시 확인한다.
- compute/apps의 Kubernetes provider는 EKS state의 admin_role_arn으로 get-token을 실행한다. Terraform의 AWS 배포 신원은 기존 인증을 사용한다.
- 현재 권한은 해당 EKS 클러스터 전체 관리자다. 계정 전체 AWS AdministratorAccess를 부여하지 않는다.

현재 PC의 기존 kubeconfig는 덮어쓰지 않았다. 작업 폴더에서 아래처럼 Git 제외 설정을 선택하면 된다. 공인 IP가 바뀌면 먼저 허용 CIDR을 갱신해야 한다.

```powershell
$env:KUBECONFIG = "$PWD\.cache\eks-kubeconfig.private"
kubectl get nodes
kubectl get pods -n kafka
```

airflow namespace는 생성했지만 동료 역할/IP가 없어 동료 권한은 아직 부여하지 않았다. Airflow 담당자에게는 namespace 범위의 배포 권한을 준비하고, chart가 필요한 클러스터 공통 권한은 별도 검토한다. AWS Athena/S3/Secret 권한은 EKS 배포 권한과 별도로 연결한다.

같은 계정의 IAM 사용자를 role trust principal로 직접 지정하면 별도 identity allow 없이 assume할 수 있는 경우가 있다. 다만 명시적 deny·permissions boundary·SCP 등을 확인해야 하며, 역할을 신뢰 목록에 넣는 것만으로 모든 조직에서 역할 전환이 보장되지는 않는다. [IAM 정책 평가](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies.html)

## 나중에 팀원 추가

Git 제외 EKS 입력의 두 목록에 병합한다.

1. EKS 관리자가 될 사람만 admin_trusted_principal_arns에 IAM user/role ARN을 추가한다. 권한 범위를 이해한 뒤 추가하며 일반 개발자는 필요 시 별도의 namespace 권한을 준비한다.
2. 실제 접속 장소의 공인 IPv4 /32를 public_access_cidrs에 추가한다. 같은 네트워크면 출구 IP가 같을 수 있다. 허용 IP와 IAM 권한은 별개이므로 둘 다 준비한다.
3. EKS plan에서 역할 trust 및 endpoint CIDR만 의도대로 바뀌는지 검토한다. 최종 승인된 배포 절차에서 적용한다. 기본 역할 이름과 access entry는 유지한다.

admin_role_arns는 별도로 이미 존재하는 관리자 역할을 직접 추가할 때만 사용하는 선택 입력이다. 전용 역할을 사용할 팀원은 그 목록이 아니라 admin_trusted_principal_arns에 추가한다.

현재 PC만 허용하므로 다른 네트워크의 팀원은 지금 접속할 수 없다. 공인 IP 변경 시 기존 값을 무조건 누적하지 않고 더 이상 사용하지 않는 주소를 제거한다. CIDR은 EKS 관리 API용이며 서비스 ALB 접근 범위와 다르다. VPC 내부 private API는 유지한다.

## 마지막 배포 때 접속 확인

먼저 network와 eks를 배포하고, 전용 역할·access entry·policy가 준비됐는지 확인한다. EKS 스택 폴더에서 역할 ARN을 변수로 받아 kubeconfig를 준비하는 예시다. ARN을 공개 문서나 Git에 복사하지 않는다.

```powershell
$eksAdminRole = terraform output -raw admin_role_arn
aws eks update-kubeconfig --region ap-northeast-1 --name clothes-query-dev-eks --assume-role-arn $eksAdminRole --role-arn $eksAdminRole --alias clothes-query-dev
kubectl --context clothes-query-dev get namespaces
```

assume-role-arn은 클러스터 정보 조회용, role-arn은 이후 Kubernetes 인증용이다. 실행자는 전용 역할을 assume할 수 있어야 한다. 별도의 role profile을 이미 사용 중이라면 중복 assume 설정 없이 프로필 구성에 맞춘다. [AWS CLI update-kubeconfig](https://docs.aws.amazon.com/cli/latest/reference/eks/update-kubeconfig.html)

그다음 compute/apps를 준비한다. 직접 사용자 신원으로 받은 토큰과 역할 신원으로 받은 토큰을 혼동하지 않는다. 팀원에게 AWS 비밀키를 공유하지 않으며 각자의 승인된 인증을 사용한다.

## 검증 범위

eks/compute/apps validate와 전용 역할·trust·제한된 IAM 권한·관리자 연결·팀원 확장·잘못된 입력 거부 mock plan을 통과했다. 2026-10-16 실제 역할 assume, EKS API 접속과 namespace/노드/Pod 조회·설치를 확인했다. 동료 신원으로의 접속과 namespace 제한 권한은 해당 IAM 정보가 없어 미검증이다.
