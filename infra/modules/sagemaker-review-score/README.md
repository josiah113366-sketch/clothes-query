# sagemaker-review-score module

리뷰 점수화(s2c 합친 모델)를 SageMaker Processing Job 으로 돌리기 위한 **실행 기반**: Job 실행 IAM 역할, VPC 실행용 보안 그룹,
스크립트용 SSM 설정, Airflow 가 붙일 launcher 정책. Processing Job 자체와 스케줄·이메일 알림·예산은 만들지 않는다(Airflow silver DAG 종료 신호로 Airflow 가 실행, `main.tf` 맨 위 주석).
호출 스택: [stacks/sagemaker-review-score](../../stacks/sagemaker-review-score/README.md). 각 리소스 설명은 `main.tf` 주석.

| 입력 | 설명 |
|---|---|
| `name`, `component`, `region` | 이름 접두사(기본 `clothes-query-dev-sagemaker-review-score`), 비용 태그 Component 값, 리전 |
| `use_vpc`, `vpc_id`, `subnet_ids` | VPC 실행 여부(기본 true)와 network 스택 output (app subnet, NAT 경유) |
| `bucket_name`, `bucket_arn` | storage 스택 output (민감 값) |
| `review_input_prefix` | 읽기 전용 리뷰 입력, Silver 리뷰 (기본 `silver/reviews`) |
| `work_prefix` | `model/`·`code/` 를 두는 prefix, 읽기 전용 (기본 `review-score`) |
| `output_prefix`, `error_prefix` | 쓰기 전용. 결과 `staging/review-score`(Iceberg MERGE 입력, athena 스택의 staging 과 같아야 함), 오류 `silver/review_aspect_scores_error` (아래에 `year=/month=/day=/` 파티션) |
| `model_version` | 출력 열·파일명의 모델 버전(기본 `2.4b_score_s2c`), SSM 설정에 담김 |
| `dlc_registry_account_id`, `dlc_repository`, `dlc_image_tag` | AWS 공개 PyTorch DLC 이미지 (개인 계정에서 실측한 것과 동일) |
| `instance_type`, `volume_size_gb`, `max_runtime_seconds`, `job_name_prefix` | 스크립트가 SSM 설정에서 읽는 실행 기본값 |
| `config_parameter_name` | 스크립트가 읽는 SSM 파라미터 이름 |

출력: `role_arn`, `role_name`, `security_group_id`, `config_parameter_name`, `image_uri`, `launcher_policy_arn`.
