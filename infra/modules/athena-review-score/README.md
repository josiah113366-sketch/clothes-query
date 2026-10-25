# athena-review-score module (초안)

리뷰 점수 결과를 Iceberg 테이블에 MERGE 로 반영하기 위한 Athena/Glue 기반: Glue 데이터베이스, Iceberg 테이블·staging 외부 테이블, Athena 워크그룹, Airflow 가 붙일 IAM 정책(`athena_runner`), 스크립트용 SSM 설정.
각 리소스 설명은 `main.tf` 주석.
호출 스택: [stacks/athena-review-score](../../stacks/athena-review-score/README.md).

| 입력 | 설명 |
|---|---|
| `name`, `component`, `region` | 이름 접두사(기본 `clothes-query-dev-athena-review-score`), 비용 태그, 리전 |
| `bucket_name`, `bucket_arn` | storage 스택 output (민감 값) |
| `staging_prefix` | SageMaker Job 이 점수 Parquet 을 임시로 쓰는 곳(기본 `staging/review-score`) |
| `table_prefix` | Iceberg 테이블 위치(기본 `silver/review_aspect_scores_iceberg`) |
| `staging_log_prefix`, `log_table_prefix` | 후기별 점수 로그 staging prefix(기본 `staging/review-score-log`)와 로그 Iceberg 테이블 위치(기본 `silver/review_score_log_iceberg`) |
| `results_prefix` | Athena 쿼리 결과 위치(기본 `athena-results/review-score`) |
| `database_name`, `table_name`, `staging_table_name` | Glue DB·점수 테이블 이름 |
| `latest_view_name` | Gold 가 읽는 Athena 뷰 이름(기본 `review_aspect_scores_latest`). 버전은 점수 로그 `review_score_log` 에서 후기마다 `model_version_no` 최대(비교용 제외)로 고르고, 점수 행은 점수 테이블에서 가져온다. Glue `VIRTUAL_VIEW` 로 생성 |
| `status_view_name` | 후기 단위 점수 상태 뷰 이름(기본 `review_score_status_latest`). 로그 기준 후기별 최신 버전(비교용 제외) 한 행 + `score_status`(`속성없음`/`점수있음`). 로그에 없는 Silver 후기는 Gold 가 LEFT JOIN 으로 미분석 판단 |
| `comparison_model_versions` | 비교용 모델 버전 목록(기본 `["2.4b_score_s2r"]`). 두 뷰의 버전 선택에서 제외한다. 비어 있으면 제외하지 않는다 |
| `log_table_name`, `staging_log_table_name` | 후기별 점수 로그 테이블(Iceberg)과 그 staging 외부 테이블 이름 |
| `bytes_scanned_cutoff` | 쿼리당 스캔 한도(기본 10GB, 최소 10MB) |
| `config_parameter_name` | 스크립트가 읽는 SSM 파라미터 이름 |

출력: `workgroup_name`, `database_name`, `runner_policy_arn`, `config_parameter_name`.
