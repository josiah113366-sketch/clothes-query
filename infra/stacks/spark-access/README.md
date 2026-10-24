# Spark 실행용 AWS 접근

## 거래 공개·재처리 연결

`enable_trade_publication=true`는 기존 역할을 유지하고 Bronze v2 거래 입력 읽기, Driver의 명시된 Silver/Gold A 표 파티션 등록, 재처리 요청/manifest 및 `gold_b/reprocess_events/silver-*` 추가 권한을 연결한다. Executor는 Glue 권한을 받지 않는다. DB·표 생성/변경·원본 쓰기·이벤트 삭제 권한은 주지 않는다. 판정 역할에는 `silver_runs`/`order_amount_checks` 및 공개 검사 결과 두 prefix의 읽기만 별도 추가한다.

등록 대상 DDL은 `pipelines/silver/silver_runs.sql`, `pipelines/silver/order_amount_checks.sql`, `pipelines/gold_a/tables.sql`이다. 배포 권한으로 문장별 실행하고 기존 schema/location 불일치는 덮어쓰지 않는다. 처리 역할은 파티션만 등록한다. 리뷰 Athena 조회와 퍼널/리뷰 출력 권한은 이번 거래 연결에 포함하지 않는다.

정상 시험은 새 실행 ID `trade-publication-20261024-104`를 사용하고 해당 실행의 Parquet rollback만 `rollback_run_ids`에 추가했다. 과거 결과의 삭제 범위를 넓히지 않는다. 실제 검증 결과는 [작업 기록](../../../docs/tasks/infra-silver-publication.md)을 따른다.

eks/storage/network state 이후 독립 key로 관리한다. 모듈 기본은 enabled=false·namespace=null이다. 2026-10-23 사용자 승인으로 공통 deployment.auto.tfvars.json의 첫 거래 검증 설정을 활성화해 pipelines의 Driver/Executor 역할·Pod Identity를 적용했다. ECR 개발자 push 권한은 ecr 스택, Kubernetes 계정/RBAC는 platform/spark runtime으로 분리한다.

첫 거래 검증용 입력은 trade-test.tfvars.example에 준비했다. pipelines의 Silver·Gold A 계정을 연결하고, 거래 공개 옵션을 켠 경우 본인의 Silver 재처리 이벤트만 추가할 수 있다. Gold B 적재 원장 접근은 주지 않는다. network S3 endpoint의 DeleteObject·ListMultipartUploadParts·ListBucketMultipartUploads 선행 적용을 확인해야 한다. 기존 workload-access binding은 변경하지 않는다. 노드풀 활성화·업무 Job·Glue 표 생성은 이 스택에 포함하지 않는다.

기본 terraform plan은 적용된 공통 설정을 사용한다. 검토 예시는 terraform plan -var-file=trade-test.tfvars.example이다. 현재 endpoint 선행 적용을 확인하는 사전조건은 통과했고 적용 후 plan은 변경 없음이다. 검사를 끄거나 가짜 remote output으로 우회하지 않는다. [최신 준비 결과](../../platform/spark/handoff/silver-gold-a-ready.md)를 따른다.
