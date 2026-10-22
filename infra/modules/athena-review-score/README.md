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
| `results_prefix` | Athena 쿼리 결과 위치(기본 `athena-results/review-score`) |
| `database_name`, `table_name`, `staging_table_name` | Glue DB·테이블 이름 |
| `bytes_scanned_cutoff` | 쿼리당 스캔 한도(기본 10GB, 최소 10MB) |
| `config_parameter_name` | 스크립트가 읽는 SSM 파라미터 이름 |

출력: `workgroup_name`, `database_name`, `runner_policy_arn`, `config_parameter_name`.
