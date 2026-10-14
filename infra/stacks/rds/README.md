> **최신 결정(2026-10-14): RDS만 Single-AZ.** VPC·EKS는 두 AZ, NAT는 AZ별 1개씩 총 2개, WEB/WAS와 Kafka는 두 AZ 분산을 유지한다. 전체 단일 AZ 설명과 NAT 1개 plan은 이전 오해에 따른 과거 기록이며 현재 배포 기준이 아니다. 최신 구성은 infra/TOPOLOGY.md를 따른다.

# rds stack

암호화된 private Single-AZ PostgreSQL과 SG 및 subnet group.

현재 승인값은 PostgreSQL 16.15, db.t4g.small(2 vCPU/2 GiB), gp3 초기 20 GiB / 자동 증가 최대 100 GiB다. `terraform.tfvars`에 반영했으며 실제 생성은 마지막에 진행한다. 사양과 비용 근거는 [RDS 검토](../../../docs/design/infra/rds-sizing.md)를 따른다.

- 선행: 기존 bootstrap 및 network, eks.
- backend key: `clothes-query/dev/rds/terraform.tfstate`.
- 입력: `engine_version`, `instance_class`, `allocated_storage`, `max_allocated_storage`, 선택 `database_name`(clothes). Single-AZ 지원 조합을 배포 전 조회한다.
- 모든 스택은 `expected_account_id`를 비공개 환경변수로 받는다. 종속 state 읽기에는 `state_bucket`, 필요시 `state_region`도 입력한다.
- 출력: `address`, `port`, `database_name`, `master_secret_arn`.
- 선택 `logical_replication`은 기본 null. 활성화에는 명시적 `max_replication_slots`, `max_wal_senders`, `max_slot_wal_keep_size_mb`가 필요하다. 추가 출력은 설정 요청 여부 `logical_replication_enabled`와 `cdc_parameter_group_name`이다.

## 실행

[전체 안내](../../IMPLEMENTATION.md)를 먼저 읽는다. `terraform.tfvars.example`을 `deployment.local.tfvars`로 복사하고 승인된 값으로 편집한다. 파일을 복사하는 것만으로 배포할 수 없으며 계정/state 확인이 선행되어야 한다.

이 디렉터리에서 `terraform init -backend=false`, `terraform validate`로 정적 검증할 수 있다. 실제 backend 초기화와 plan은 전체 안내의 계정/state 확인 후 진행한다. apply는 사용자가 검토된 plan에 대해 실행한다.

## 삭제 및 운영 주의

Single-AZ 인스턴스 비용이 발생하며 AZ 장애 시 standby 전환은 없다. prevent_destroy와 deletion_protection이 켜져 있다. final snapshot 이름이 이미 있다면 삭제 작업 전에 별도 고유 이름과 복구 계획이 필요하다. 엔진 변경/import/교체는 자동 수행하지 않는다.

CDC 입력은 [실측 전 준비와 배포 조건](../../../docs/design/infra/data-path-readiness.md)을 확인한 뒤 비공개 파일에서 공급한다. 테스트 수치를 배포 기본값으로 사용하지 않는다. 실제 family/파라미터 지원·연결 예산·WAL 여유·재시작 시점을 검토한다. slot/계정/캡처 범위와 복구 검증은 DB/CDC 담당자와 함께 진행한다.
