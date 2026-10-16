> **최신 결정(2026-10-14): RDS만 Single-AZ.** VPC·EKS는 두 AZ, NAT는 AZ별 1개씩 총 2개, WEB/WAS와 Kafka는 두 AZ 분산을 유지한다. 전체 단일 AZ 설명과 NAT 1개 plan은 이전 오해에 따른 과거 기록이며 현재 배포 기준이 아니다. 최신 구성은 infra/TOPOLOGY.md를 따른다.

# rds module

암호화된 private Single-AZ PostgreSQL과 SG 및 subnet group를 관리한다.

## 입력과 출력

- 배포 사양: `engine_version`, `instance_class`, `allocated_storage`, `max_allocated_storage`, 선택 `database_name`(clothes). Single-AZ 지원 조합을 배포 전 조회한다.
- 연결 입력: `name`, `vpc_id`, `db_subnet_ids`, 선택 `workload_security_group_id`(기존 EKS, 기본 null), `database_clients`(이름별 클라이언트 SG, 기본 빈 map). [호출 스택](../../stacks/rds/main.tf)에서 연결한다. 두 클라이언트 입력이 비어 있으면 DB ingress를 만들지 않는다. 기존 EKS ingress는 moved 블록으로 인덱스 주소를 보존한다.
- 출력: `address`, `port`, `database_name`, `master_secret_arn`.
- 선택 CDC 입력: `logical_replication`에 slot/sender/유한 WAL 예산을 명시. 기본 null이며 이때 custom parameter group은 만들지 않는다. engine major에 맞는 family를 사용한다.
- 추가 출력: `logical_replication_enabled`(설정 요청 여부), `cdc_parameter_group_name`. 실제 DB 적용 상태를 조회한 출력이 아니다.
- 전체 타입/기본값: [variables.tf](variables.tf), [outputs.tf](outputs.tf).

## 실행과 주의점

[rds 스택](../../stacks/rds/README.md)에서 실행한다. Single-AZ 인스턴스 비용이 발생하며 AZ 장애 시 standby 전환은 없다. prevent_destroy와 deletion_protection이 켜져 있다. final snapshot 이름이 이미 있다면 삭제 작업 전에 별도 고유 이름과 복구 계획이 필요하다. 엔진 변경/import/교체는 자동 수행하지 않는다.

CDC 활성화는 WAL 발생·보존 및 DB 저장 공간에 영향을 줄 수 있다. 이번 코드 준비는 DB 사양·노드 규모를 바꾸지 않는다. parameter group은 pending-reboot로 준비하고 DB `apply_immediately=false`를 유지한다. DB 재시작·계정·publication/slot 생성과 기존 CDC 해제/이관은 자동 수행하지 않는다. [활성화 입력과 검증 조건](../../../docs/design/infra/data-path-readiness.md)을 따른다.
