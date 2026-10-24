# Gold B 접근 준비

후속 저장 계약(2026-10-21): 조사 데이터는 Glue DB `agent`, S3 `agent/`로 분리한다. `enable_investigation_catalog`, `investigation_database_name`, `investigation_write_prefixes`는 비공개 입력으로 활성화한다. 판정의 `detection_write_prefixes`는 `gold_b/anomaly/`, `gold_b/detection_runs/`, `gold_b/reprocess_events/`다. 기존 쿼리 결과 쓰기는 각 `athena-results/` 경로로 유지한다. 조사 역할은 Gold B 쓰기를 받지 않고 판정 역할은 agent 쓰기를 받지 않는다. [후속 작업 기록](../../../docs/tasks/infra-agent-data-write.md).

아래 조회 전용 설명은 최초 적용 이력이다. 후속 변경에서는 조사 Glue DB만 만들며 테이블은 만들지 않는다. 표 이름·DDL·파티션·INSERT SQL을 받은 뒤 실제 업무 INSERT와 필요한 Glue 파티션 변경 권한을 검증한다. 현재 역할에는 Glue 테이블 생성/변경/파티션 생성·S3 삭제를 허용하지 않는다. 경로 권한 준비만으로 Athena INSERT 성공을 보장하지 않는다.

후속 적용은 DB 1개 추가·정책 2개 수정, mock 13건·IAM simulation 32건 통과·후속 변경 없음까지 확인했다. 과거 조회 전용 코드로 재적용하면 쓰기 권한이 회수될 수 있으므로 현재 코드와 비공개 입력을 함께 유지한다.

상태: 2026-10-21 사용자 요청으로 조회용 자원 실제 적용 완료. 기존 network/eks/storage state 이후 독립 key `clothes-query/dev/gold-b-access/terraform.tfstate`를 사용한다. 관리 자원은 workgroup 2개·역할 2개·inline policy 2개·Pod Identity association 2개다. 새 버킷·컴퓨팅·Glue DB/테이블·개발자 권한은 만들지 않는다. namespace/ServiceAccount는 [별도 manifest](../../platform/agent-access/README.md)로 생성해 실제 Pod 신원·합성 S3/Athena 접근·정답표 차단을 검증했다. 업무 Pod와 판정 업무 기록 쓰기는 아직 후속이다.

- `agent/detection-job` → `clothes-query-dev-detection-job`, workgroup `clothes-query-dev-detection`.
- `agent/investigation-agent` → `clothes-query-dev-investigation-agent`, workgroup `clothes-query-dev-investigation`.
- 기존 데이터 버킷의 `athena-results/detection/` 및 `athena-results/investigation/`를 강제하고 SSE-S3를 사용한다. prefix는 tfvars에서 나중에 변경할 수 있다. 변경해도 과거 결과 파일을 자동 이동/삭제하지 않는다.
- 변경 입력은 `terraform.tfvars`의 `workgroup_names`, `results_prefixes`, `bytes_scanned_cutoff_per_query`다. 이름/경로를 바꾸면 대응하는 IAM 정책도 함께 갱신된다. workgroup 이름 변경은 기존 그룹의 단순 표시명 수정이 아니라 교체/신규 생성이 될 수 있으므로 매번 plan을 확인한다. 실행 코드의 workgroup 설정도 함께 맞춘다.
- 우선 쿼리당 1GiB 제한이다. 월 예산·누적 비용 상한이 아니며 취소된 쿼리도 읽은 데이터에 요금이 발생할 수 있다. workgroup의 추가 CloudWatch 지표 게시를 끈다. S3 결과 저장·요청 및 Athena 조회는 실제 사용 시 과금된다.
- 개발자는 운영 역할 trust에 포함하지 않는다. 기존 사용자 권한을 제한하는 변경이 아니다. 운영 역할에 접근 가능한 데이터/허용된 쿼리 결과로만 범위를 제한한다. 다른 주체가 정답표를 gold_b/에 복사하면 경로 차단만으로 내용의 유출을 막을 수는 없다.

## 실행과 확인

2026-10-23 확정된 JP Claude Haiku 4.5 프로필 및 도쿄/오사카 목적지 모델만 조사 역할에 추가 적용했다. #53의 표 4개와 anomaly_current 뷰도 기존 DB에 배포했고, 실제 판정 ServiceAccount 첫 INSERT·SELECT를 통과했다. 업무 이미지/ConfigMap 연결 및 실제 모델 호출은 이 단계에 포함하지 않는다. [현재 적용 기록](../../../docs/tasks/infra-agent-bedrock-catalog.md)을 따른다. 아래는 초기 준비 시점의 일반 검증 안내다.

실제 계정/state bucket은 Git 제외 `deployment.local.tfvars.json`, backend bucket은 `deployment.backend.hcl`로 공급한다. [전체 안내](../../IMPLEMENTATION.md)에 따라 init, fmt, validate, mock, plan 후 적용한다. 실제 적용 전 동일 역할/workgroup/association의 존재와 소유권을 확인한다. 보류 중인 `infra/athena-query-base`는 같은 판정 workgroup 이름을 사용하므로 두 스택을 함께 적용하지 않는다. 이번 스택으로 통합해 쓸 경우 기존 미적용 후보는 대체한다.

이 스택은 IAM/Workgroup만 관리한다. namespace/ServiceAccount 소유권은 별도 manifest에 있으며 Airflow/업무 chart에서 재사용한다. scheduler가 판정 Pod를 띄우는 RBAC도 별도로 연결해야 한다. 판정의 업무 기록 쓰기는 실제 저장 prefix·writer 방식이 확정될 때까지 빈 목록으로 유지한다. Athena INSERT와 S3 직접 Parquet append의 요구 권한은 다를 수 있다. 읽기 전용 Glue 권한만으로 신규 테이블 생성은 불가능하다.

적용 후 검증은 각 역할의 gold_b 읽기와 자기 결과 쓰기 성공, ground_truth 객체/version/list와 상대 결과 읽기 거부, 쿼리 스캔 한도·뷰 의존·실제 Athena 성공을 포함한다. Lake Formation 등록 또는 KMS 암호화가 있다면 별도 권한 계약을 확인한다. policy simulation/mock은 실제 Pod Identity 세션·업무 SQL의 성공을 대신하지 않는다. 결과 보관/정리 정책은 아직 추가하지 않아 결과가 누적될 수 있다. [작업 기록](../../../docs/tasks/infra-gold-b-access-prep.md).

참고: [workgroup 결과 경로 강제](https://docs.aws.amazon.com/athena/latest/ug/query-results-specify-location-workgroup.html), [Glue 카탈로그 접근](https://docs.aws.amazon.com/athena/latest/ug/fine-grained-access-to-glue-resources.html), [Pod Identity trust](https://docs.aws.amazon.com/eks/latest/userguide/pod-id-role.html).
