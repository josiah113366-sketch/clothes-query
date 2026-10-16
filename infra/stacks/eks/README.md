# eks stack

EKS Auto Mode와 cluster/node IAM 및 명시적 관리자 access entry.

- 선행: 기존 bootstrap 및 network.
- backend key: `clothes-query/dev/eks/terraform.tfstate`.
- 입력: `kubernetes_version`, `admin_trusted_principal_arns`(전용 역할을 assume할 사용자/역할), 선택 `admin_role_arns`(별도 기존 관리자 역할), `public_access_cidrs`(/24 또는 더 좁은 관리자 CIDR). 현재 PC는 /32로 준비한다.
- 모든 스택은 `expected_account_id`를 비공개 환경변수로 받는다. 종속 state 읽기에는 `state_bucket`, 필요시 `state_region`도 입력한다.
- 출력: `cluster_name`, `cluster_security_group_id`, `node_role_name`, 민감 출력 `admin_role_arn`. compute/apps는 이 역할로 Kubernetes 토큰을 받는다. 초기 버전은 사용자 승인에 따라 1.36으로 설정했다.

## 실행

관리자 신원·접속 장소 결정과 후속 Kubernetes provider의 인증 연결은 [EKS 접속 준비](../../EKS_ACCESS.md)를 따른다.

[전체 안내](../../IMPLEMENTATION.md)를 먼저 읽는다. `terraform.tfvars.example`을 `deployment.local.tfvars`로 복사하고 승인된 값으로 편집한다. 파일을 복사하는 것만으로 배포할 수 없으며 계정/state 확인이 선행되어야 한다.

이 디렉터리에서 `terraform init -backend=false`, `terraform validate`로 정적 검증할 수 있다. 실제 backend 초기화와 plan은 전체 안내의 계정/state 확인 후 진행한다. apply는 사용자가 검토된 plan에 대해 실행한다.

## 삭제 및 운영 주의

기본 NodePool은 비활성화하고 노드 역할의 EC2 access entry/AutoNodePolicy를 만든다. 그다음 [compute 스택](../compute/README.md)이 custom NodeClass/NodePool을 만든다. 노드 용량은 [증설·축소 가이드](../../SCALING.md)에 따라 조정한다. 기존 배포된 클러스터에 이 코드를 적용할 경우 기본 풀 제거로 기존 노드가 종료될 수 있으므로 별도 전환 계획이 필요하다. 현재 클러스터는 아직 배포하지 않았다.
