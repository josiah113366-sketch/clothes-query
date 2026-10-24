# ecs-review-simulator module

리뷰 시뮬레이터 ECS Fargate 실행 기반: ECR, ECS 클러스터, 태스크 SG(HTTPS, VPC 안 RDS 5432 나가기), IAM 역할(실행·태스크·스케줄러), Bedrock API 키 Secret, RDS 접속 주소 Secret,
꺼진 예약 실행(EventBridge Scheduler), 로그·태스크 종료 기록·오류 지표·대시보드, 스크립트용 SSM 파라미터, 선택적 알림·예산.
호출 스택: [stacks/ecs-review-simulator](../../stacks/ecs-review-simulator/README.md). 각 리소스 설명은 `main.tf` 주석.

| 입력 | 설명 |
|---|---|
| `name` | 이름 접두사 (기본 `clothes-query-dev-ecs-review-simulator`) |
| `region`, `vpc_id`, `subnet_ids` | network 스택 output (app subnet, NAT 경유) |
| `bucket_name`, `bucket_arn` | storage 스택 output (민감 값) |
| `lake_prefix`, `input_prefix` | 쓰기 `bronze_v2/reviews/*`, 읽기 `sim-input/review-simulator/*` |
| `cpu`, `memory` | 태스크 크기 (기본 512 / 1024, 스크립트가 태스크 정의 등록 때 사용) |
| `schedule_expression` | 예약 실행 시각 (`schedule_timezone` 기준, 기본 매일 00:00) |
| `schedule_timezone` | 예약 실행 시간대 (기본 `Asia/Seoul`, 2026-10-23 lemin: KST 0시 실행) |
| `alarm_email`, `budget_email`, `budget_limit_usd` | 선택. 비어 있으면 만들지 않음 |
| `bedrock_price_input`, `bedrock_price_output` | 대시보드 추정 비용 단가 (100만 토큰당 USD) |
| `config_parameter_name` | 스크립트가 읽는 SSM 파라미터 이름 |

출력: `ecr_repository_url`, `cluster_name`, `task_family`, `security_group_id`(RDS `database_clients` 에 전달), `secret_name`, `orders_db_secret_name`, `schedule_name`,
`config_parameter_name`, `dashboard_name`.
