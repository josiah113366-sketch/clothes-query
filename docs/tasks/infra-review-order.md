# 작업 지시서: infra/review-order

> 상태: 작업 완료 (코드 작성, PR 준비) · 브랜치: `infra/review-order` · 다음 작업: RDS 쪽 허용(`database_clients`)·읽기 전용 DB 계정·`ORDERS_SOURCE=rds` 전환(배포 순서 참고)

## 목표

리뷰 시뮬레이터(ECS)가 가짜 주문 대신 **RDS의 실제 주문(orders)** 을 읽어 리뷰를 만들 수 있게 한다(`--source rds`). 결제 후 리뷰까지의 기간을 0~7일(결제 당일 포함)로 바꾼다.
실행 방식(하루 1번)은 그대로이고, 기본 배포 상태는 가짜 주문(`ORDERS_SOURCE=fake`)이다. 실시간(계속 쓰기)과 RDS 쪽 허용·DB 계정 생성은 이 브랜치에서 하지 않는다.

## 먼저 읽을 것

- 루트 `CLAUDE.md`, `infra/CLAUDE.md`, `review-simulator/CLAUDE.md`
- `docs/tasks/sim-review-ecs.md` (선행: 리뷰 시뮬레이터 ECS 기반)
- `infra/stacks/ecs-review-simulator/README.md`, `infra/modules/ecs-review-simulator/`
- `review-simulator/deploy/README.md` ("RDS 주문 읽기" 절), `review-simulator/CHANGELOG.md` (0.2.1 ~ 0.3.1)

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- 2026-10-21 lemin 결정: 리뷰 시뮬레이터가 RDS orders 테이블을 읽는다(`--source rds`). 결제가 끝난 주문(상태 PAID·SHIPPED·DELIVERED, 결제 SUCCESS)의 주문 항목 하나에 리뷰 하나를 단다.
- 2026-10-21 lemin 결정: 결제 후 리뷰까지 기간 1~14일 → 1~7일 → 0~7일(결제 당일 포함).
- 2026-10-21 lemin 결정: 실시간(계속 쓰기)은 보류, 하루 1번 실행 유지.
- 개인정보 컬럼(이름·이메일·전화)은 읽지 않는다. 읽기 전용 DB 계정을 쓴다.
- 이 브랜치는 `infra/`(ECS 모듈·스택)와 `review-simulator/`(앱 코드·배포 스크립트)를 함께 담는다(같은 기능이라 한 브랜치로 진행, PR 본문에 명시).

## 시작 전 확인 (Claude가 한다)

- 브랜치를 최신 `main` 에서 만들었는지, `infra/ecs-review-simulator` 가 main 에 반영됐는지
- RDS 스택이 apply 되어 있고 `database_clients` 에 넣을 보안 그룹 값을 알 수 있는지
- 팀 계정 자격증명, `TF_VAR_expected_account_id` 와 state 버킷이 같은 계정인지

## 만드는 것

### 1. 인프라 (`infra/modules|stacks/ecs-review-simulator`)
- RDS 접속 주소를 담을 Secrets Manager secret (값은 Terraform에 없음, `deploy/secret.py --orders-db`로 넣음)
- 태스크 실행 역할이 이 secret도 읽을 수 있게 하는 권한
- 태스크 보안 그룹의 PostgreSQL(5432) 나가는 규칙 (같은 VPC 주소 범위로만)
- SSM 설정 `orders_db_secret_arn`, 출력 `orders_db_secret_name`

### 2. 리뷰 시뮬레이터 (`review-simulator`, 0.2.1 → 0.3.0 → 0.3.1)
- `rsim run --source rds`, RDS 값으로 프롬프트 구성(`product_info`, `age_group`), 리뷰의 `order_id`·`member_id`·`product_id`가 RDS 값
- 결제 후 리뷰 기간 0~7일
- 배포 스크립트: `secret.py --orders-db`, `switch.py --orders rds|fake`, `run_rds.py`, PowerShell 래퍼, 진입점 `ORDERS_SOURCE` 분기
- 의존성 `psycopg[binary]`, 설정 `ORDERS_DATABASE_URL`, 테스트(`test_rds_orders.py`, `test_deploy.py`)

## 만들지 않는 것

- RDS 쪽 허용(`infra/stacks/rds` 의 `database_clients`) → RDS 담당의 별도 apply
- 읽기 전용 DB 계정 생성(DB 관리자가 SQL로) → `deploy/README.md` 순서
- 실시간(계속 쓰기) 실행 → 보류
- 리뷰 컬럼(review.v2)과 `PROMPT_VERSION` 변경 → 그대로

## 작업 순서

1. 시작 전 확인을 하고, **계획을 먼저 제시해 사용자 확인을 받는다**
2. 모듈·스택 → 시뮬레이터 코드 → 배포 스크립트 → 문서 순으로 작성한다
3. `terraform fmt` → `validate` → `plan`(destroy/replace 가 있으면 먼저 알린다), `ruff`, `pytest`
4. 재영이 plan 확인 후 apply, 결과를 PR 에 첨부한다
5. 배포 순서(아래) 진행 후 "완료 확인"을 실행하고 결과를 이 문서 맨 아래에 기록한다

### 배포 순서 (merge 후)

① ECS 스택 apply → ② RDS 스택 `database_clients` 에 태스크 보안 그룹 ID 추가 후 apply(RDS 담당) → ③ DB 관리자가 읽기 전용 계정 생성 → ④ `python deploy/secret.py --orders-db` → ⑤ `python deploy/deploy.py` → ⑥ `python deploy/switch.py --orders rds`.

## 완료 확인

아래를 **실제로 실행**해서 결과를 보고한다. (2026-10-22 작성자 lemin 이 전부 실행해 이상 없음을 확인함. 수치·로그는 PR 본문에 첨부)

- [x] `terraform fmt -check`, `terraform validate`
- [x] `ecs-review-simulator` plan 에 destroy/replace 없음
- [x] `ruff check . && ruff format --check .`
- [x] `pytest` (`test_rds_orders.py`, `test_deploy.py` 포함)
- [x] apply 후 `terraform plan` 이 변경 없음
- [x] `python deploy/onoff.py once --fake` 로 `RDS 주문 항목 N건 읽음` 로그 확인
- [x] `python deploy/run_rds.py` 1회 실제 생성 결과와 Bedrock 비용
- [x] 저장소에 DB 주소·계정·비밀번호가 없음 (`git grep`)

## README 갱신

- `infra/stacks/ecs-review-simulator/README.md`, `infra/modules/ecs-review-simulator/README.md`
- `review-simulator/README.md`, `review-simulator/deploy/README.md`, `review-simulator/CHANGELOG.md`
- `docs/BRANCHES.md` 대장 한 줄 (작성함, 머지 때 상태 변경)

## 작업 결과 (머지 전에 작성한다. 사람과 AI가 나중에 이 브랜치가 무엇을 했는지 읽는 곳이다)

- **한 줄 요약:** 리뷰 시뮬레이터가 RDS의 실제 주문을 읽어 리뷰를 만들 수 있게 하는 ECS 기반과 앱·배포 스크립트.
- **무엇을 만들었나:** 위 "만드는 것" 1·2.
- **왜 그렇게 했나:** 리뷰의 주문·회원·상품 키가 RDS 값이면 레이크에서 거래 데이터와 바로 조인된다. 접속 주소는 Secrets Manager 에만 두어 저장소에 비공개 값이 없다.
  기본은 가짜 주문을 유지하고 순서를 마친 뒤 사람이 전환하게 해서, RDS 허용·DB 계정이 준비되기 전에 태스크가 깨지지 않는다.
- **입력과 출력:** 입력 RDS orders 계열 테이블(읽기 전용 계정), 출력 S3 `bronze/reviews/` 날짜 파티션(기존과 같음). 연동 값은 Secret `.../orders-database-url`, SSM 설정 `orders_db_secret_arn`.
- **확인한 결과:** 2026-10-22 작성자가 위 "완료 확인" 항목(terraform fmt·validate·plan, ruff, pytest, apply 후 무변경 plan, `once --fake` 로그, `run_rds.py` 실제 생성, 비공개 값 검사)을 모두 실행해 이상 없음을 확인했다. 상세 수치는 PR 본문에 첨부.
- **알려진 한계·남은 일:** RDS 쪽 허용·읽기 전용 계정·전환, 같은 날짜를 다시 돌리면 0~7일 규칙 때문에 그 날짜에 걸리는 주문이 바뀜, 실시간 실행(보류).
