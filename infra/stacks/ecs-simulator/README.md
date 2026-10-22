# ecs-simulator stack

거래·회원 시뮬레이터(`simulator/`)를 ECS Fargate 태스크 1개로 계속 실행한다. 담당: 시뮬레이터 담당자가 작성·apply 한다.
모듈은 [modules/ecs-simulator](../../modules/ecs-simulator/README.md), 이미지·실행 확인은 `simulator/README.md`(sim/ecs-image).

- 선행: bootstrap, network(VPC·app subnet·NAT), storage(데이터 버킷), 업무 API(내부 ALB, `api/README.md`).
- backend key: `clothes-query/dev/ecs-simulator/terraform.tfstate`.
- 구조: 태스크 1개 = 같은 이미지 컨테이너 3개(controller, member, behavior). 공유 볼륨 `/control`의 `control.json`으로 모드·장애를 주고받는다.
  시뮬레이터는 API로만 쓰고 읽는다(DB 계정·Kafka 인증서 없음). 예외: 컨트롤러 데이터 오염은 RDS에 직접 쓴다(오염 전용 계정).
- 네트워크: private app subnet, public IP 없음. SG는 들어오는 규칙 없음, 나가는 443(AWS API)·80(VPC, 내부 ALB)·5432(VPC, RDS).
- 서비스: 온디맨드, 태스크 1개, 교체할 때 옛 태스크를 먼저 내린다(min 0% / max 100%, 두 개가 겹쳐 돌지 않게). ECS Exec 켬.
- 비용: 0.5 vCPU / 1GB 상시 약 월 22달러 + Secret 0.4달러 + 로그. 멈추려면 `desired_count = 0`으로 apply.

## 실행 (Windows PowerShell, 이 폴더)

`deployment.backend.hcl`(bucket, region. 다른 스택과 같은 값)은 Git으로 관리한다(`infra/DEPLOYMENT_CONFIG.md`).
비공개 파일(커밋 안 됨)은 `deployment.local.tfvars.json` 또는 `deployment.local.tfvars`(`terraform.tfvars.example` 참고)이다.
PowerShell은 `-`로 시작하고 `.`이 든 인자를 둘로 쪼개므로 아래처럼 따옴표로 감싼다.

```powershell
cd infra/stacks/ecs-simulator
$env:TF_VAR_expected_account_id = "<계정 ID>"
terraform init "-backend-config=deployment.backend.hcl" "-lockfile=readonly"
terraform plan -input=false "-var-file=deployment.local.tfvars.json" "-out=ecs-simulator.tfplan"
terraform apply ecs-simulator.tfplan
```

**두 번 apply 한다.**

1. **기반**: `image_digest` 없이. 첫 plan은 모두 create(14개)여야 한다. destroy/replace가 보이면 멈춘다.
2. 이미지 push(`simulator/README.md`) 후 `deployment.local.tfvars.json`에 `image_digest`, `api_url`(내부 ALB `http://internal-…`)을 넣고 다시 plan·apply.
   추가는 태스크 정의 1개와 서비스 1개. 이후 새 이미지는 `image_digest`만 바꿔 apply한다(태스크 정의 새 리비전 → 서비스 교체).

## 이 스택 밖에서 같이 할 것

- **RDS 접근(데이터 오염)**: `infra/stacks/rds`의 비공개 입력 `database_clients`에 `"ecs-simulator": "<security_group_id 출력>"`을 넣고 rds plan·apply.
  plan에는 RDS SG 인바운드 규칙 1개 추가만 있어야 한다.
- **DB 오염 계정·Secret 값**: `simulator/` 문서의 SQL로 `clothes_sim_admin`을 만들고, 접속 문자열을 `secret_name` 출력의 Secret에 넣는다.
- **API ALB 허용 대역**: `api/deploy/chart/runtime.local.yaml`의 `inboundCIDRs`를 app subnet 대역으로 좁히고 `helm upgrade`.

## 삭제 및 운영 주의

- ECR은 `force_delete=false`라 이미지가 있으면 destroy가 멈춘다. 이미지는 최근 10개만 남는다.
- Secret은 삭제 후 7일 복구 기간이 있어 같은 이름으로 바로 다시 만들 수 없다.
- 태스크를 다시 띄우면 시뮬레이터 메모리에 있던 예약(결제·배송 전이)이 사라진다(`simulator/README.md` 알려진 한계).
