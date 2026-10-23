# Silver·Gold A Spark data access

기존 workload-access bindings를 교체하지 않는 별도 opt-in 모듈이다. namespace 확정 전 enabled=false로 IAM·Pod Identity를 만들지 않는다. 제출기는 Kubernetes 제출 권한만 쓰고 Driver/Executor만 각 AWS 역할을 사용한다.

Bronze 거래 3개·요청/입력 manifest는 읽기, 거래 출력은 읽기·쓰기 및 multipart 조회/중단을 허용한다. 기본 DeleteObject는 출력의 runs/<run_id>/<dataset>/__magic_job-*/ 아래 작업 객체만 허용한다. rollback_run_ids를 명시하면 해당 실행의 part-*.parquet에 한해 실패 복구 삭제를 추가한다. manifest·완료 기록·current.json 삭제는 허용하지 않는다. reference_object_arns는 확인된 상품 스냅샷 두 객체만 허용하며 기본은 비어 있다. funnels/reviews·Glue 권한을 추정하지 않는다.

클러스터 ARN·namespace·ServiceAccount 태그로 Pod Identity 신뢰를 제한한다. 검토용 입력은 stacks/spark-access/trade-test.tfvars.example에 있다. 자동 설정은 계속 enabled=false다. network endpoint가 필요한 작업을 허용하지 않으면 역할의 plan을 거부한다. endpoint 통과 권한 자체가 S3 데이터 권한을 부여하는 것은 아니다.

커미터의 fs.s3a.committer.abort.pending.uploads 설정과 실제 작업 객체 경로는 업무 코드에서 확인해야 한다. bucket-level ListBucketMultipartUploads는 별도 opt-in이며 이 모듈의 기본값은 false다. 최종 AWS 쓰기 검증 전 정책 완성을 보장하지 않는다. 새 일반 DeleteObject prefix 권한을 workload-access에 중복 적용하지 않는다.
