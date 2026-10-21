# team-access module

기존 EKS에 동료 IAM 신원을 연결하고 애플리케이션 namespace의 배포 권한을 부여한다. backend/provider는 호출 스택이 관리한다. [스택 안내](../../stacks/team-access/README.md)를 따른다.

리소스는 namespace·EKS access entry·namespace RoleBinding·운영 조회 ClusterRole/ClusterRoleBinding 총5개다. WAS 변경은 namespace `edit`로, 전체 운영 상태는 명시한 리소스의 get/list/watch로 연결한다. cluster-admin, 다른 namespace Secret, node proxy 및 다른 namespace exec 권한은 부여하지 않는다. 입력 principal은 sensitive이고 실제 ARN은 공개 Git에 넣지 않는다. `variables.tf`와 `outputs.tf`에 전체 입력/출력을 정의한다.
