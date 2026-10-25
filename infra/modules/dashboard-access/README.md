# 승인 대시보드 접근

`enable_gold_a_reads=true`는 같은 역할에 Gold A 지표 전용 읽기 정책을 추가한다. 대상은 `gold_runs`와 지표·보류 테이블 7개이며 S3는 채널별 완료 목록과 해당 데이터셋의 실행별 Parquet 폴더로 제한한다. 제어 파일·Spark 체크포인트·Silver 원본·Gold A 쓰기/삭제·Glue DDL 권한은 추가하지 않는다. 기존 승인 쓰기 정책은 유지한다. [검증 기록](../../../docs/tasks/infra-dashboard-gold-a-read.md)을 참고한다.

기존 EKS의 dashboard/approval-dashboard Pod Identity, 전용 Athena workgroup과 S3 결과 경로를 준비한다. gold_b.anomaly_current 및 기반 anomaly, agent.investigation_reports, gold_b.reprocess_events 메타데이터·원본을 읽는다. 업무 쓰기는 gold_b/reprocess_events/에만 허용하며 객체 삭제·Glue DDL·Bedrock·다른 결과 경로·ground_truth 접근은 허용하지 않는다.

2026-10-23 모델 패치노트 조회를 위해 `model_registry_prefix`(기본 `review-score/model-registry/releases/`)의 GetObject와 제한된 목록 조회를 추가한다. 이 경로 쓰기·삭제·모델 가중치 읽기는 추가하지 않는다. 기존 역할·workgroup·Pod Identity는 같은 dashboard-access state에서 관리한다. 상세 배포·검증은 [작업 기록](../../../docs/tasks/infra-dashboard-runtime-connect.md)을 참고한다.

IAM은 REQUESTED/APPROVED 같은 행의 값을 검사하지 않는다. 상태 전이·승인자 검증·중복 방지는 앱 담당자가 구현한다. Airflow 인증은 IAM 정책과 별개이며 Kubernetes Secret으로 공급한다. Simple Auth의 user 역할은 특정 DAG만 허용하는 경계를 제공하지 않는다. 모듈은 기존 workload 역할이나 dashboard 앱을 변경하지 않는다.

`enable_pipeline_status_reads=true`는 기존 역할에 상태 화면용 읽기 정책 하나를 추가한다. 대상은 Gold B 원장 4개, `silver.silver_runs`, `gold_a.gold_runs`와 해당 원본·완료 목록이다. 기본값은 false이며 승인 쓰기 정책과 workgroup은 그대로 유지한다. `gold_runs`의 표 Location은 `gold_a/catalog/`지만 실제 channel 파티션은 `gold_a/runtime/<trade|funnels|reviews>/catalog/completed/`를 가리키므로 이 완료 목록만 함께 읽는다. 지표 runs 전체·리뷰 점수 Iceberg·새 원본 쓰기·삭제·Glue DDL은 허용하지 않는다. [적용 기록](../../../docs/tasks/infra-dashboard-status-read.md)을 따른다.

`enable_review_score_reads=true`는 감성분석 모델 화면용 읽기 전용 정책 `review-score-read-only`를 추가한다(2026-10-25). Glue는 DB `clothes_query_dev_review_score`의 점수 테이블·점수 로그·최신 뷰·`silver_reviews_runs` 조회만, S3는 점수 Iceberg 표 두 곳, Silver 리뷰 `current.json`·`completed/`·`runs/*/silver_reviews/`, 실행 요약 `staging/review-score/_summary_scores_*`의 읽기만 허용한다. 쓰기·Glue DDL·`ground_truth/` 접근은 없다. Silver 리뷰 실행 출력의 `text`(후기 원문)는 점수 차가 큰 후기를 확인하는 화면이 review_id 몇 건에 한해 읽는다(팀 내부용, 외부 반출 금지). apply는 인프라 담당(재영)이 한다.
