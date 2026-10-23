# compute module

2026-10-22 Spark 준비: `spark_node_pool`은 기본 비활성이며 명시적으로 켤 때만 기존 private NodeClass를 사용하는 별도 tainted NodePool을 만든다. `WhenEmpty`/10분·유형/용량 예산을 독립 관리한다. [미적용 두 후보와 실행 계약](../../platform/spark/README.md)을 따른다. 기존 공용 풀 기본값은 유지한다.

EKS Auto Mode의 사용자 정의 NodeClass와 NodePool을 관리한다. EKS와 별도 state인 [compute 스택](../../stacks/compute/README.md)에서 호출한다.

## 입력과 출력

- 연결 입력: `name`, `node_role_name`, `app_subnet_ids`, `cluster_security_group_id`, `availability_zones`.
- 조정 입력: `instance_types`, `node_pool_cpu_limit`, `node_pool_memory_limit_gib`, `consolidate_after`. 타입과 기본값은 [variables.tf](variables.tf) 참고.
- 기본값: t3a.large, amd64, On-Demand, 6 vCPU/24GiB(세 대분의 용량 한도), 정리 대기 10분.
- 출력: `node_pool_name`, `capacity_limits`.

## 선행 및 실행

eks 스택이 custom node role과 EC2 access entry/AutoNodePolicy를 만든 뒤 적용한다. private app subnet과 cluster SG를 명시적으로 지정하여 RDS의 허용 SG와 일치시킨다. 두 기본 NodePool은 비활성화되어 있어 이 풀 밖으로 우회 증설하지 않는다.

실제 plan은 EKS API와 Auto Mode CRD가 있어야 가능하다. 2026-10-16 사용자 배포 요청으로 실제 NodeClass/NodePool과 private t3a.large 한 대를 생성했고 후속 plan 변경 없음을 확인했다. [배포 결과](../../../docs/tasks/infra-deploy-result.md).

## 운영/삭제 주의

이 NodePool은 시스템 Pod와 업무 Pod가 공유한다. 단일 Kafka와 운영자/측정 exporter의 한 대 배치는 확인했으며 Connect·Airflow·실제 업무를 포함한 전체 수용은 미검증이다. 고정 replicas나 최소 노드 수를 지정하지 않고, Pod의 requests와 배치 제약으로 수용할 수 없는 수요가 생기면 증설한다. CPU 사용률만으로 Kafka Pod나 broker 수가 자동 증가하지 않는다. 제네레이터는 팀원이 별도 ECS Fargate에 구성하므로 이 풀의 용량에 포함하지 않는다.

6 vCPU/24GiB는 t3a.large 세 대분이며 노드 수/요금의 엄격한 상한은 아니다. 동시 provisioning 중 일시 초과할 수 있고, 교체·시스템 Pod 용량도 공유한다. 입력 검증의 최소 4 vCPU/16GiB는 한 대와 교체 한 대분의 여유다. `WhenEmptyOrUnderutilized`와 10분 대기로 통합을 허용하지만 PDB와 배치 조건을 만족해야 한다. NodePool/NodeClass 삭제는 노드와 Pod 종료에 영향을 주므로 워크로드가 남은 채 삭제하지 않는다.

[Generator 부하에 따른 증설·축소 가이드](../../SCALING.md)를 따른다.
