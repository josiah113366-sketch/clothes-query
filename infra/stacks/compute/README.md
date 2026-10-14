> **현재 구성(2026-10-14):** 이전 HA 결정을 변경했다. 워커·앱·RDS는 ap-northeast-1a 한 AZ, NAT 1개, RDS Single-AZ다. AWS 서비스 요구사항 때문에 두 AZ의 서브넷은 유지한다. WEB 2개/WAS HPA 2~3개는 유지한다. 아래의 이전 HA 설명보다 infra/SINGLE_AZ.md의 최신 결정을 우선한다.

# compute stack

EKS Auto Mode의 노드 타입, 증설 한도 및 자동 정리 설정을 관리한다.

- 선행: network, eks의 실제 배포와 remote state. 별도 Kubernetes provider가 기존 EKS API에 연결한다.
- backend key: `clothes-query/dev/compute/terraform.tfstate`.
- 필수 비공개 입력: `expected_account_id`, `state_bucket`. 다른 AWS 인증정보는 코드에 넣지 않는다.
- 조정 입력: `instance_types`, `node_pool_cpu_limit`, `node_pool_memory_limit_gib`, `consolidate_after`.
- 출력: `node_pool_name`, `capacity_limits`. apps는 이 풀 이름을 nodeSelector로 사용한다.

## 실행

[전체 안내](../../IMPLEMENTATION.md)를 먼저 읽는다. `terraform.tfvars`는 승인된 초기값이고 비공개/변경 입력은 `deployment.local.tfvars`로 덮어쓴다. `terraform init -backend=false -lockfile=readonly`와 `terraform validate`는 클러스터 생성 없이 실행할 수 있다. 실제 plan은 network/eks 및 Auto Mode CRD가 준비된 뒤 수행한다.

순서는 `network → eks → compute → apps`이며 RDS와 storage도 apps 전에 필요하다. 현재는 생성 테스트를 하지 않는다. 모든 준비 후 최종 plan과 비용 검토를 거쳐 사용자 승인 범위에서 배포한다.

## 삭제와 용량 변경

노드 한도를 낮추는 것만으로 실행 중인 노드가 즉시 삭제되지 않는다. 먼저 workload를 줄이고 consolidation 및 재배치 상태를 관찰한다. 앱/PDB를 유지할 용량과 노드 교체 여유를 남긴다. 풀/클래스 삭제와 허용 타입 변경은 노드 종료/교체를 일으킬 수 있으므로 [증설·축소 가이드](../../SCALING.md)를 참고한다.
