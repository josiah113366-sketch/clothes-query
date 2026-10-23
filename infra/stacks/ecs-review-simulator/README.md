# ecs-review-simulator stack

리뷰 시뮬레이터(`review-simulator/`)를 ECS Fargate 에서 돌리기 위한 기반. 담당: 리뷰 시뮬레이터 담당자(lemin)가 작성·apply 한다.
모듈은 [modules/ecs-review-simulator](../../modules/ecs-review-simulator/README.md), 배포·운영 스크립트는 [review-simulator/deploy](../../../review-simulator/deploy/README.md).

- 선행: bootstrap(state 버킷), network(VPC·app subnet·NAT·S3 endpoint), storage(데이터 버킷). 두 스택 output 을 remote state 로 읽는다.
- backend key: `clothes-query/dev/ecs-review-simulator/terraform.tfstate`.
- 만드는 것: ECR `clothes-query-dev/ecs-review-simulator`, ECS 클러스터, 태스크 SG(나가는 443 만), IAM 역할 3개
  (태스크 실행·태스크·스케줄러), Bedrock API 키 Secret(값 없음), 예약 실행(**DISABLED**), 로그 그룹 2개, 오류 지표,
  CloudWatch 대시보드, 스크립트용 SSM 파라미터. 선택: 실패 알림 SNS·알람, 월 예산.
- 태스크 정의는 만들지 않는다. `deploy/deploy.py`·`switch.py` 가 리비전을 등록한다(이미지 태그·실행 비율이 자주 바뀜).
- 태스크 역할 권한: `bronze/reviews/*` PutObject, `sim-input/review-simulator/*` GetObject 만. `ground_truth/`·`gold_b/` 권한 없음.
- 비용: 만들어 두기만 하면 거의 0 (Secret $0.40/월, 로그·대시보드 몇 센트. 대시보드 3개까지 무료). 실행 비용은 deploy README 참고.
- 출력: `ecr_repository_url`, `cluster_name`, `task_family`, `security_group_id`(RDS 스택 `database_clients` 에 전달, 2026-10-21 `--source rds`),
  `secret_name`, `orders_db_secret_name`(값은 `deploy/secret.py --orders-db`), `schedule_name`, `config_parameter_name`, `dashboard_name`.

## 실행

[전체 안내](../../IMPLEMENTATION.md)와 같은 방식이다. 비공개 입력은 Git 제외 파일에만 둔다.

```powershell
cd infra/stacks/ecs-review-simulator
# 비공개 파일 2개 (커밋 안 됨): deployment.backend.hcl (bucket, region), deployment.local.tfvars (terraform.tfvars.example 복사)
$env:TF_VAR_expected_account_id = "<계정 ID>"

terraform init -backend=false -lockfile=readonly   # 정적 검사
terraform fmt -check
terraform validate

terraform init -backend-config=deployment.backend.hcl -lockfile=readonly
terraform plan -input=false -var-file=deployment.local.tfvars -out=ecs-review-simulator.tfplan
terraform apply ecs-review-simulator.tfplan             # plan 을 확인한 담당자가 실행
```

첫 plan 은 모두 create 여야 한다(이 스택은 다른 스택 리소스를 바꾸지 않는다). destroy/replace 가 보이면 멈추고 확인한다.

## 삭제 및 운영 주의

- ECR 은 `force_delete=false` 라 이미지가 있으면 destroy 가 멈춘다. 이미지는 최근 10개만 남는다.
- Secret 은 삭제 후 7일 복구 기간이 있어 같은 이름으로 바로 다시 만들 수 없다.
- 예약 실행의 켜짐/꺼짐과 실행 리비전은 `deploy/onoff.py` 가 바꾸며 Terraform 은 그 두 값을 되돌리지 않는다(ignore_changes).
- 로그 리소스 정책(EventBridge → 로그)은 계정당 10개 한도에 1개를 쓴다.
