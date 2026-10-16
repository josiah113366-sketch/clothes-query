# compute stack

EKS Auto Mode의 노드 타입, 증설 한도 및 자동 정리 설정을 관리한다.

2026-10-16 사용자 결정: `t3a.large` On-Demand만 허용하고 한도는 6 vCPU/24GiB(세 대분), 통합 대기는 10분이다. 평소 한 대 운영은 배치 목표이며 보장된 최소/고정 수가 아니다. 실제 노드는 Pod requests·배치 제약에 따라 생성하며 동시 provisioning 중 한도를 일시 초과할 수 있다. ECS Fargate 제네레이터는 팀원 담당으로 이 스택에서 생성하지 않는다. [연결 입력](../../../docs/design/infra/team-inputs.md).

- 선행: network, eks의 실제 배포와 remote state. 별도 Kubernetes provider가 기존 EKS API에 연결한다.
- backend key: `clothes-query/dev/compute/terraform.tfstate`.
- 필수 비공개 입력: `expected_account_id`, `state_bucket`. 다른 AWS 인증정보는 코드에 넣지 않는다.
- 조정 입력: `instance_types`, `node_pool_cpu_limit`, `node_pool_memory_limit_gib`, `consolidate_after`.
- 출력: `node_pool_name`, `capacity_limits`. apps는 이 풀 이름을 nodeSelector로 사용한다.

## 실행

[전체 안내](../../IMPLEMENTATION.md)를 먼저 읽는다. `terraform.tfvars`는 승인된 초기값이고 비공개/변경 입력은 `deployment.local.tfvars`로 덮어쓴다. `terraform init -backend=false -lockfile=readonly`와 `terraform validate`는 클러스터 생성 없이 실행할 수 있다. 실제 plan은 network/eks 및 Auto Mode CRD가 준비된 뒤 수행한다.

최소 실행의 순서는 `network(NAT 1개 활성화) → eks → compute → Kafka 운영자 → Kafka/Connect(single-node profile)`다. RDS와 storage는 이미 선행 배포했다. WEB/WAS·ALB·Spark는 이번 최소 배포에 포함하지 않는다. standard Kafka의 3 broker 배치와 앱의 두 AZ/anti-affinity 조건을 활성화하면 한 대 운영이 불가능하므로 축소 프로필을 명시적으로 선택한다. 실제 생성은 아직 수행하지 않았으며 최종 plan과 비용 검토 후 배포한다.

## 삭제와 용량 변경

노드 한도를 낮추는 것만으로 실행 중인 노드가 즉시 삭제되지 않는다. 먼저 workload를 줄이고 consolidation 및 재배치 상태를 관찰한다. 앱/PDB를 유지할 용량과 노드 교체 여유를 남긴다. 풀/클래스 삭제와 허용 타입 변경은 노드 종료/교체를 일으킬 수 있으므로 [증설·축소 가이드](../../SCALING.md)를 참고한다.
