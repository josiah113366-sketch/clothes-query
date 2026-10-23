# Silver·Gold A Spark data access

기존 workload-access bindings를 교체하지 않는 별도 opt-in 모듈이다. namespace 확정 전 enabled=false로 IAM·Pod Identity를 만들지 않는다. 제출기는 Kubernetes 제출 권한만 쓰고 Driver/Executor만 각 AWS 역할을 사용한다.

Bronze 거래 3개·요청/입력 manifest는 읽기, 거래 출력은 읽기·쓰기 및 multipart 조회/중단, DeleteObject는 출력의 runs/<run_id>/<dataset>/__magic_job-*/ 아래 작업 객체만 허용한다. 정상 Parquet·manifest·완료 기록의 삭제 권한은 없다. 향후 funnels/reviews·상품 기준정보·Glue 권한을 추정하지 않는다.

커미터의 fs.s3a.committer.abort.pending.uploads 설정과 실제 작업 객체 경로는 업무 코드에서 확인해야 한다. bucket-level ListBucketMultipartUploads는 별도 opt-in이며 이 모듈의 기본값은 false다. 최종 AWS 쓰기 검증 전 정책 완성을 보장하지 않는다. 새 일반 DeleteObject prefix 권한을 workload-access에 중복 적용하지 않는다.
