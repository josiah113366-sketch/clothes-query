# eks module

EKS Auto Mode와 cluster/node IAM 및 명시적 관리자 access entry를 관리한다.

## 입력과 출력

- 배포 사양: `kubernetes_version`, `admin_role_arns`, `public_access_cidrs`(/24 이상으로 제한된 관리자 CIDR). 리전에서 지원되는 표준 지원 버전을 고른다.
- 연결 입력: `name`, `app_subnet_ids`. [호출 스택](../../stacks/eks/main.tf)에서 연결한다.
- 출력: `cluster_name`, `cluster_security_group_id`, `node_role_name`.
- 전체 타입/기본값: [variables.tf](variables.tf), [outputs.tf](outputs.tf).

## 실행과 주의점

[eks 스택](../../stacks/eks/README.md)에서 실행한다. 기본 NodePool은 비활성화하며 custom node용 EC2 access entry와 AmazonEKSAutoNodePolicy를 생성한다. 노드 구성은 별도 compute 스택에서 관리한다. compute 이전에는 노드가 없을 수 있다. 앱은 두 AZ에 분산하지만 무중단 여부는 실제 장애 테스트가 필요하다.

관리자 역할에만 명시적으로 cluster-admin을 부여한다. bootstrap creator 관리자 권한은 꺼져 있다. Auto Mode Pod Identity 기능을 사용하므로 별도 GitHub/EKS OIDC provider를 만들지 않는다.
