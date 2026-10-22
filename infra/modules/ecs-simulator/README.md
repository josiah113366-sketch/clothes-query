# ecs-simulator module

거래·회원 시뮬레이터(`simulator/`) ECS Fargate 실행 기반: ECR, ECS 클러스터, 태스크 SG(나가는 방향만), IAM 역할(실행·태스크),
데이터 오염용 DB 접속 문자열 Secret(값 없음), 로그 그룹. `image_digest`를 주면 태스크 정의(컨테이너 3개 + 공유 볼륨)와 서비스(태스크 1개)까지 만든다.
호출 스택: [stacks/ecs-simulator](../../stacks/ecs-simulator/README.md). 각 리소스 설명은 `main.tf` 주석.

| 입력 | 설명 |
|---|---|
| `name` | 이름 접두사 (기본 `clothes-query-dev-ecs-simulator`) |
| `region`, `vpc_id`, `subnet_ids` | network 스택 output (app subnet, NAT 경유) |
| `bucket_name`, `bucket_arn` | storage 스택 output (민감 값). 정답표 `ground_truth/incident_log/` 쓰기 |
| `image_digest` | 이 스택 ECR의 이미지 `sha256:…`. 비우면 기반만 |
| `api_url` | 업무 API 내부 ALB 주소 (민감 값, `image_digest`가 있으면 필수) |
| `desired_count` | 0(멈춤) 또는 1. 2 이상은 거부(트래픽·정답표가 겹침) |
| `cpu`, `memory` | 태스크 전체 크기 (기본 512 / 1024) |
| `log_retention_days`, `keep_images` | 로그 보관 14일, 이미지 10개 |

| 컨테이너 | 명령 (`ENTRYPOINT sim`) | 추가 입력 |
|---|---|---|
| `controller` | `controller serve --incident-log s3` | `S3_BUCKET`, `SIM_ALLOW_REMOTE_DB=1`, Secret → `DATABASE_URL` |
| `member` | `member live` | |
| `behavior` | `behavior live` | |

공통 환경 변수: `SIM_BACKEND=api`, `SIM_API_URL`, `SIM_CLICK_SINK=api`, `SIM_LIVE_SPEED=1`, `SIM_CONTROL_FILE=/control/control.json`, `AWS_REGION`.

출력: `ecr_repository_url`, `cluster_name`, `service_name`(이미지 전에는 빈 값), `security_group_id`(rds `database_clients`에 전달),
`secret_name`, `log_group_name`.
