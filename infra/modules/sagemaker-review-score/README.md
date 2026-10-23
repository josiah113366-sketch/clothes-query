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
| `work_prefix` | `model/`(가중치)·`model-registry/releases/`(릴리스 묶음: manifest, 실행 코드, 패치노트)를 두는 prefix (기본 `review-score`). Job 역할은 가중치와 묶음의 `code/` 만 읽고, manifest 는 launcher 가 읽는다 |
| `output_prefix`, `error_prefix` | 쓰기 전용. 결과 `staging/review-score`(Iceberg MERGE 입력, athena 스택의 staging 과 같아야 함), 오류 `silver/review_aspect_scores_error` (아래에 `year=/month=/day=/` 파티션) |
| `dlc_registry_account_id`, `dlc_repository`, `dlc_image_tag` | AWS 공개 PyTorch DLC 이미지 (개인 계정에서 실측한 것과 동일). 새 릴리스 묶음의 기본 이미지(SSM `image_uri`)이고 Job 역할의 ECR 읽기 범위다. Job 은 manifest 의 이미지를 쓴다 |
| `instance_type`, `volume_size_gb`, `max_runtime_seconds`, `job_name_prefix` | 스크립트가 SSM 설정에서 읽는 실행 기본값 |
| `release` | 지금 점수화에 쓸 모델 버전 이름(기본 `2.4b_score_s2c`). 이 이름의 `manifest.json` 이 S3 에 있어야 한다. 모델 이름·번호·이미지·코드는 manifest 가 정하므로 SSM 에 두지 않는다(2026-10-23). 버전 변경·되돌림은 이 값만 바꾼다 |
| `score_log_prefix`, `unscored_input_prefix` | 후기별 점수 로그 staging(기본 `staging/review-score-log`, 쓰기)와 미점수 입력(기본 `staging/review-score-input`, 읽기) |
| `config_parameter_name` | 스크립트가 읽는 SSM 파라미터 이름 |

출력: `role_arn`, `role_name`, `security_group_id`, `config_parameter_name`, `image_uri`, `launcher_policy_arn`.
