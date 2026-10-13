# rds module

암호화된 private Multi-AZ PostgreSQL과 SG 및 subnet group를 관리한다.

## 입력과 출력

- 배포 사양: `engine_version`, `instance_class`, `allocated_storage`, `max_allocated_storage`, 선택 `database_name`(clothes). Multi-AZ 지원 조합을 배포 전 조회한다.
- 연결 입력: `name`, `vpc_id`, `db_subnet_ids`, `workload_security_group_id`. [호출 스택](../../stacks/rds/main.tf)에서 연결한다.
- 출력: `address`, `port`, `database_name`, `master_secret_arn`.
- 전체 타입/기본값: [variables.tf](variables.tf), [outputs.tf](outputs.tf).

## 실행과 주의점

[rds 스택](../../stacks/rds/README.md)에서 실행한다. Multi-AZ 비용이 발생한다. prevent_destroy와 deletion_protection이 켜져 있다. final snapshot 이름이 이미 있다면 삭제 작업 전에 별도 고유 이름과 복구 계획이 필요하다. 엔진 변경/import/교체는 자동 수행하지 않는다.
