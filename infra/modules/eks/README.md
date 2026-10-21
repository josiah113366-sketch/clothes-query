# eks module

개발 비용 절감을 위해 EKS 관리 로그 중 audit는 수집하지 않는다. api/authenticator/controllerManager/scheduler는 유지하고 로그 그룹은 30일 보관한다. 감사 로그 중단 이후 Kubernetes 작업의 중앙 감사 기록은 남지 않는다. [적용 기록](../../../docs/tasks/infra-eks-audit-cost.md).

전용 관리자 역할을 생성하고 `admin_trusted_principal_arns`의 사용자/역할만 assume하도록 준비한다. 선택 `admin_role_arns`는 별도 기존 관리자 역할용이다. `admin_role_arn` 출력은 compute/apps의 Kubernetes 인증에 사용한다. 현재 사용자·현재 PC부터 시작하며 팀원 추가 절차는 [접속 준비](../../EKS_ACCESS.md)를 따른다.

EKS Auto Mode와 cluster/node IAM 및 명시적 관리자 access entry를 관리한다.

## 입력과 출력

- 배포 사양: `kubernetes_version`, `admin_role_arns`, `public_access_cidrs`(/24 또는 더 좁은 관리자 CIDR). 리전에서 지원되는 표준 지원 버전을 고른다.
- 개발용 임시 개방: `allow_public_api_from_anywhere` 기본값은 false다. 명시적으로 true로 설정하면 EKS public API의 유효 IPv4 범위만 `0.0.0.0/0`으로 변경한다. 기존 `public_access_cidrs`는 보존하며 false로 바꿔 apply하면 해당 제한을 복원한다. IAM/RBAC·private endpoint는 유지하고 자동 원복 타이머는 없다.
- 연결 입력: `name`, `app_subnet_ids`. [호출 스택](../../stacks/eks/main.tf)에서 연결한다.
- 출력: `cluster_name`, `cluster_security_group_id`, `node_role_name`.
- 전체 타입/기본값: [variables.tf](variables.tf), [outputs.tf](outputs.tf).

## 실행과 주의점

[eks 스택](../../stacks/eks/README.md)에서 실행한다. 기본 NodePool은 비활성화하며 custom node용 EC2 access entry와 AmazonEKSAutoNodePolicy를 생성한다. 노드 구성은 별도 compute 스택에서 관리한다. compute 이전에는 노드가 없을 수 있다. 앱은 두 AZ에 분산하지만 무중단 여부는 실제 장애 테스트가 필요하다.

관리자 역할에만 명시적으로 cluster-admin을 부여한다. bootstrap creator 관리자 권한은 꺼져 있다. Auto Mode Pod Identity 기능을 사용하므로 별도 GitHub/EKS OIDC provider를 만들지 않는다.
