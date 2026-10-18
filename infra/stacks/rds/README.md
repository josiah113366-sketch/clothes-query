> **현재 배포(2026-10-18):** RDS는 private Single-AZ로 유지한다. VPC는 두 AZ이며 NAT1개·EKS 노드1대·단일 Kafka 구성이다. 최신 전체 구조는 [TOPOLOGY.md](../../TOPOLOGY.md)를 따른다.

# rds stack

RDS-first 실행에서는 `use_eks_security_group=false`를 비공개 tfvars에 명시한다. 이 경우 EKS remote state를 읽지 않으며 network state만 선행한다. `database_clients={}`이면 코드가 추가하는 DB ingress는 없고, 나중에 같은 VPC의 클라이언트 보안 그룹을 이름별로 추가한다. private/TLS 및 앱 전용 계정을 유지하고 public 접속은 활성화하지 않는다. 기본 true는 기존 EKS 연동을 보존한다.

암호화된 private Single-AZ PostgreSQL과 SG 및 subnet group.

현재 승인값은 PostgreSQL 16.15, db.t4g.small(2 vCPU/2 GiB), gp3 초기 20 GiB / 자동 증가 최대 100 GiB다. 2026-10-16 RDS-first로 실제 생성했고 AWS available 상태를 확인했다. 사양과 비용 근거는 [RDS 검토](../../../docs/design/infra/rds-sizing.md)를 따른다.

2026-10-18 사용자 승인으로 논리 복제 설정과 재부팅·실제 CDC→S3 시험을 완료했다. 실배포 입력은 logical_replication 활성(slot 한도5/sender 요청10/WAL256MB)이다. SQL의 유효 sender는20이며 차이 원인은 미확정이다. 시험 schema/계정/publication/slot과 추가 EKS 접속 규칙은 제거했고, 논리 복제 기반 설정만 남겼다. 비공개 배포 입력을 기본 null 예시로 덮어쓰지 않는다. 업무용 CDC 예산·계정·allowlist는 별도 결정한다. [실제 결과](../../../docs/tasks/infra-pipeline-smoke.md).

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
