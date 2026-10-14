> **현재 구성(2026-10-14):** 이전 HA 결정을 변경했다. 워커·앱·RDS는 ap-northeast-1a 한 AZ, NAT 1개, RDS Single-AZ다. AWS 서비스 요구사항 때문에 두 AZ의 서브넷은 유지한다. WEB 2개/WAS HPA 2~3개는 유지한다. 아래의 이전 HA 설명보다 infra/SINGLE_AZ.md의 최신 결정을 우선한다.

# compute module

EKS Auto Mode의 사용자 정의 NodeClass와 NodePool을 관리한다. EKS와 별도 state인 [compute 스택](../../stacks/compute/README.md)에서 호출한다.

## 입력과 출력

- 연결 입력: `name`, `node_role_name`, `app_subnet_ids`, `cluster_security_group_id`, `availability_zones`.
- 조정 입력: `instance_types`, `node_pool_cpu_limit`, `node_pool_memory_limit_gib`, `consolidate_after`. 타입과 기본값은 [variables.tf](variables.tf) 참고.
- 기본값: m6i.large/m7i.large, amd64, On-Demand, 8 vCPU/32GiB, 정리 대기 10분.
- 출력: `node_pool_name`, `capacity_limits`.

## 선행 및 실행

eks 스택이 custom node role과 EC2 access entry/AutoNodePolicy를 만든 뒤 적용한다. private app subnet과 cluster SG를 명시적으로 지정하여 RDS의 허용 SG와 일치시킨다. 두 기본 NodePool은 비활성화되어 있어 이 풀 밖으로 우회 증설하지 않는다.

실제 plan은 EKS API와 Auto Mode CRD가 있어야 가능하다. 생성 테스트는 사용자가 마지막 단계로 미뤘으므로 현재는 validate와 mock plan만 검증한다.

## 운영/삭제 주의

이 NodePool은 시스템 Pod와 업무 Pod가 공유한다. 8 vCPU는 노드 수/요금의 엄격한 상한이 아니며 교체 여유와 시스템 사용량을 함께 계산한다. 고정 노드 2개를 예약하지 않고 Pod 수요와 배치 제약에 따라 증설한다. `WhenEmptyOrUnderutilized`와 10분 대기로 통합을 허용하지만 PDB와 배치 조건을 만족해야 한다. NodePool/NodeClass 삭제는 노드와 Pod 종료에 영향을 주므로 워크로드가 남은 채 삭제하지 않는다.

[Generator 부하에 따른 증설·축소 가이드](../../SCALING.md)를 따른다.
