# team-access module

기존 EKS에 동료 IAM 신원을 연결하고 애플리케이션 namespace의 배포 권한을 부여한다. backend/provider는 호출 스택이 관리한다. [스택 안내](../../stacks/team-access/README.md)를 따른다.

리소스는 namespace·EKS access entry·namespace RoleBinding 3개다. `edit` ClusterRole을 namespace RoleBinding으로 연결하며 ClusterRoleBinding이나 cluster-admin은 생성하지 않는다. 입력 principal은 sensitive이고 실제 ARN은 공개 Git에 넣지 않는다. `variables.tf`와 `outputs.tf`에 전체 입력/출력을 정의한다.
