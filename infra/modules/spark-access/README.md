# Silver·Gold A Spark data access

2026-10-24 리뷰 입력 계약 변경: `bronze_v2/reviews/`는 기존 데이터에 컬럼을 추가한 완전 상위호환 경로다. 새 입력은 v2를 사용하며 아래 초기 적용 기록의 `bronze/reviews/` 읽기는 전환 검증 동안만 함께 유지한다. Bronze 쓰기·삭제는 추가하지 않는다. 생성기 배포와 고정 실행 요청의 경로 전환은 각각 실제 배포·검증해야 한다.

기존 workload-access bindings를 교체하지 않는 별도 opt-in 모듈이다. namespace 확정 전 enabled=false로 IAM·Pod Identity를 만들지 않는다. 제출기는 Kubernetes 제출 권한만 쓰고 Driver/Executor만 각 AWS 역할을 사용한다.

Bronze 거래 3개·요청/입력 manifest는 읽기, 거래 출력은 읽기·쓰기 및 multipart 조회/중단을 허용한다. 기본 DeleteObject는 출력의 runs/<run_id>/<dataset>/__magic_job-*/ 아래 작업 객체만 허용한다. rollback_run_ids를 명시하면 해당 실행의 part-*.parquet에 한해 실패 복구 삭제를 추가한다. manifest·완료 기록·current.json 삭제는 허용하지 않는다. reference_object_arns는 확인된 상품 스냅샷 두 객체만 허용하며 기본은 비어 있다. funnels/reviews·Glue 권한을 추정하지 않는다.

클러스터 ARN·namespace·ServiceAccount 태그로 Pod Identity 신뢰를 제한한다. 검토용 입력은 stacks/spark-access/trade-test.tfvars.example에 있다. 모듈 기본은 disabled이고 실제 공통 배포 설정은 승인 후 스택에서 별도로 관리한다. network endpoint가 필요한 작업을 허용하지 않으면 역할의 plan을 거부한다. endpoint 통과 권한 자체가 S3 데이터 권한을 부여하는 것은 아니다.

커미터의 fs.s3a.committer.abort.pending.uploads 설정과 실제 작업 객체 경로는 업무 코드에서 확인해야 한다. bucket-level ListBucketMultipartUploads는 별도 opt-in이며 이 모듈의 기본값은 false다. 최종 AWS 쓰기 검증 전 정책 완성을 보장하지 않는다. 새 일반 DeleteObject prefix 권한을 workload-access에 중복 적용하지 않는다.

`enable_funnel_access=true`는 확정된 `bronze_v2/clickstream/` 읽기와 `silver/runtime/clicks/`·`gold_a/runtime/funnels/` 출력/멀티파트/작업 객체 정리를 두 역할에 추가한다. Driver만 기존 `gold_a.funnel_daily_runs`·`funnel_session_product_runs`의 Glue 조회·파티션 등록을 받는다. `funnel_rollback_run_ids`로 승인한 실행에 한해 두 출력 및 공통 Silver 거래 중간 결과의 최종 Parquet 정리가 가능하다. 기본값은 false/빈 집합이며 리뷰·Iceberg·대시보드 권한은 이 옵션에 포함하지 않는다. [실제 적용 기록](../../../docs/tasks/infra-silver-funnel-access.md)을 따른다.

`enable_review_access=true`는 운영 원문 `bronze/reviews/` 읽기, `silver/runtime/reviews/`·`gold_a/runtime/reviews/` 출력과 magic 정리를 두 역할에 연결한다. Driver만 기존 `clothes-query-dev-athena-review-score` 조회, 최신 점수 뷰·기반 Iceberg 읽기, 전용 Athena 결과·`pipelines/input-manifests/review-scores/` 쓰기, 기존 리뷰 Gold 표 2개의 파티션 등록을 받는다. Executor는 Athena·Iceberg 원본 권한 없이 고정 점수 파일을 읽는다. `review_rollback_run_ids`는 승인한 실행의 실패 Parquet 정리에만 사용하고 기본은 비어 있다. 기존 Driver inline policy 용량을 보존하기 위해 새 읽기/출력 권한은 관리형 정책 2개와 attachment 3개로 연결한다. [권한과 실제 읽기 확인](../../../docs/tasks/infra-silver-review-access.md)을 따른다.

2026-10-26 변경(정의 파일만 수정, apply 전): 최신 점수 뷰 `review_aspect_scores_latest` 가 버전 선택을 점수 로그 `review_score_log` 에서 하도록 바뀌었고 후기 단위 상태 뷰 `review_score_status_latest` 가 추가됐다. Athena 가 뷰를 읽으면 기반 테이블 접근이 필요하므로 `enable_review_access=true` 의 Driver 조회 정책(`review-query`)에 읽기 전용으로 추가했다: Glue GetTable 등 대상에 `review_score_log`·`review_score_status_latest`, S3 GetObject·ListBucket 에 로그 Iceberg 위치 `review_log_iceberg_prefix`(기본 `silver/review_score_log_iceberg/`, athena-review-score 의 `log_table_prefix` 와 같아야 함). 쓰기·와일드카드 권한은 없다. apply 후 확인: Spark 에서 점수 뷰 조회가 AccessDenied 없이 도는지 본다.
