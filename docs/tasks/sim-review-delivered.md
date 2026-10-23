# 작업 지시서: sim/review-delivered

> 상태: 작업 완료 (코드 작성, PR 준비) · 브랜치: `sim/review-delivered` · 선행: `infra/review-order` (RDS 주문 읽기, 0.3.0~0.3.1) · 다음 작업: 배포(아래 "배포 순서")

## 목표

리뷰 시뮬레이터(`--source rds`)가 **배송완료(DELIVERED) 주문 항목에만** 리뷰를 쓰고, 리뷰 시각을 **배송완료 시각 + 0~7일**로 정한다.
하루 1번 예약 실행을 **KST 0시**로 옮기고, 날짜를 안 주면 쓰는 "어제"를 **KST 달력**으로 센다.

## 먼저 읽을 것

- 루트 `CLAUDE.md`, `infra/CLAUDE.md`, `review-simulator/CLAUDE.md`
- `docs/tasks/infra-review-order.md` (선행: RDS 주문 읽기)
- `review-simulator/src/rsim/review/orders.py` (주문 읽기·리뷰 시각 규칙), `review-simulator/CHANGELOG.md` (0.3.2)
- `infra/modules/ecs-review-simulator/` (예약 실행 `aws_scheduler_schedule.daily`)

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- 2026-10-23 lemin 결정: RDS 주문 중 **배송완료(DELIVERED)** 항목에만 리뷰를 단다(예전: PAID·SHIPPED·DELIVERED).
- 리뷰 시각의 기준은 결제 시각이 아니라 **배송완료 시각(`orders.updated_at`)** 이다. 받기 전에 쓴 리뷰가 나오지 않게 하려는 것(Claude 제안 기본값, lemin 이 이 브랜치에 반영).
  리뷰 컬럼 `purchased_at` 은 그대로 결제 시각이다. 배송완료는 결제 5~12시간 뒤(simulator behavior 기본값).
- 2026-10-23 lemin 결정: 예약 실행을 00:30 UTC(09:30 KST) → **00:00 KST** 로 바꾼다.
  주문 시뮬레이터가 KST 벽시계 시각을 UTC 처럼 RDS 에 넣으므로, 데이터의 날짜 D 는 사실상 KST 날짜 D 다. 그래서 "어제"도 KST 달력으로 센다.
- 리뷰 컬럼(review.v2), S3 경로·파티션 이름, `PROMPT_VERSION` 은 바꾸지 않는다.
- 이 브랜치는 `review-simulator/`(앱·배포 스크립트)와 `infra/`(ECS 리뷰 시뮬레이터 모듈·스택의 스케줄 값)를 함께 담는다(같은 기능이라 한 브랜치, PR 본문에 명시).

## 만드는 것

### 1. 리뷰 시뮬레이터 (`review-simulator`, 0.3.1 → 0.3.2)
- `orders.py`: `RDS_REVIEW_STATUSES = ("DELIVERED",)`, SQL 이 `o.updated_at AS delivered_at` 을 읽고 읽는 범위도 배송완료 시각으로 자름
- `Order.delivered_at`, `Order.review_base_at`(배송완료가 있으면 그것, 없으면 결제 시각), `ReviewTiming.due_at` 이 `review_base_at` 기준
- `run.py`: `rsim run` 기본 날짜 = 어제(KST 달력)
- 컨테이너 `entrypoint.sh`: `RUN_DATE` 기본 = 어제(KST 달력, 시간대 데이터 없이 UTC+9 로 계산)
- 배포 스크립트: `aws_common.yesterday_utc` → `yesterday_kst`(`run_rds.py`, `run_incident.py`), `onoff.py`·`.ps1` 도움말, `status.py` 가 스케줄에 저장된 시간대를 그대로 출력(예전엔 "UTC" 고정 문구)
- 테스트 `test_rds_orders.py`: DELIVERED 만, 배송완료 기준 범위, "리뷰 시각이 배송완료 이후 7일 이내" 확인 추가

### 2. 인프라 (`infra/modules|stacks/ecs-review-simulator`)
- 모듈 변수 `schedule_timezone`(기본 `Asia/Seoul`) 추가, `schedule_expression_timezone = var.schedule_timezone`
- `schedule_expression` 기본값과 스택 `terraform.tfvars` 값을 `cron(0 0 * * ? *)` 로

## 만들지 않는 것

- 주문 시뮬레이터의 시각 저장 방식(KST 를 UTC 처럼 넣는 것) 수정 → 그대로 두고 리뷰 쪽이 맞춤
- `--source orders`(JSONL 가짜 주문)·`random` 동작 → 그대로(배송 정보가 없어 결제 시각 기준 유지)
- 예전 가짜 주문 리뷰가 남은 bronze 날짜 폴더 정리 → 사람이 S3 에서 직접(아래 "남은 일")

## 작업 순서

1. 코드 → 테스트 → 문서(README, CHANGELOG, CLAUDE.md) → 인프라 값 순으로 수정
2. `ruff`, `pytest`, `sh -n entrypoint.sh`, `terraform fmt -check`·`validate`
3. 사용자가 `terraform plan`(스케줄 값만 바뀌는지) → `apply`
4. 배포 순서 진행 후 "완료 확인" 결과를 이 문서 맨 아래에 기록

### 배포 순서 (merge 후)

① `infra/stacks/ecs-review-simulator` 에서 `terraform plan` → 스케줄의 `schedule_expression`·`schedule_expression_timezone` 만 바뀌는지 확인 후 `apply`
→ ② `.\scripts\deploy.ps1` (0.3.2 이미지·새 태스크 정의) → ③ `.\scripts\onoff.ps1 on` (스케줄이 최신 리비전을 쓰게)
→ ④ `.\scripts\status.ps1` 에서 `[스케줄] ENABLED · cron(0 0 * * ? *) Asia/Seoul` 확인
→ ⑤ 필요하면 `.\scripts\run-rds.ps1 -Date <날짜>` 로 지난 날짜 채우기

## 완료 확인

- [x] `ruff check . && ruff format --check .` (review-simulator) — 2026-10-23 Claude 확인
- [x] `pytest` 66개 통과 (`test_rds_orders.py` 배송완료 기준 테스트 포함) — 2026-10-23 Claude 확인
- [x] `sh -n deploy/container/entrypoint.sh`, KST 어제 계산 확인 (00:36Z → 2026-10-22) — 2026-10-23 Claude 확인
- [x] `terraform fmt -check`, `terraform validate` (ecs-review-simulator) — 2026-10-23 Claude 확인
- [x] `terraform plan` 이 스케줄 값만 바꿈, apply 후 plan 변경 없음
- [x] `status.ps1` 이 `cron(0 0 * * ? *) Asia/Seoul` 로 표시
- [x] 배포 후 첫 예약 실행 로그에 `RDS 주문 항목 N건 읽음 (배송완료 …, 상태 DELIVERED)`
- [x] 저장소에 DB 주소·계정·비밀번호·버킷 이름 추가 없음 (`git grep`)

## README 갱신

- `review-simulator/README.md`, `review-simulator/CLAUDE.md`, `review-simulator/CHANGELOG.md`(0.3.2), `review-simulator/deploy/README.md`
- `infra/modules/ecs-review-simulator/README.md` (`schedule_timezone`)
- `docs/BRANCHES.md` 대장 한 줄

## 작업 결과 (머지 전에 작성한다)

- **한 줄 요약:** 리뷰 시뮬레이터가 배송완료된 주문 항목에만, 배송완료 후 0~7일에 리뷰를 쓰고, 매일 KST 0시에 KST 기준 어제치를 만든다.
- **무엇을 만들었나:** 위 "만드는 것" 1·2.
- **왜 그렇게 했나:** 받기 전 리뷰가 생기지 않게 하려고 대상과 기준 시각을 배송완료로 맞췄다. RDS 시각이 KST 벽시계 값이라 UTC 로 하루를 자르면 9시간씩 밀리므로 실행 시각과 "어제"를 KST 로 맞췄다.
- **입력과 출력:** 입력 RDS orders(DELIVERED)·order_items·payments(SUCCESS)·product_variant·product_design·members.age_band(읽기 전용), 출력 S3 `bronze/reviews/year=/month=/day=` (변경 없음).
- **확인한 결과:** "완료 확인" 참고. 코드 쪽 검사는 통과, 배포 쪽 항목은 배포 후 작성자가 채운다.
- **알려진 한계·남은 일:**
  - 같은 날짜를 다시 돌리면 대상(DELIVERED)과 기준 시각이 0.3.1 과 달라서 그 날짜에 걸리는 주문 항목이 바뀐다.
  - 배송완료 뒤 환불(REFUNDED)된 주문은 그 뒤 실행부터 빠지고, 이미 쓴 날짜 파티션의 리뷰는 남는다.
  - 리뷰가 0건인 날짜는 파일을 쓰지 않아서, 예전 가짜 주문 리뷰만 있는 bronze 날짜 폴더는 다시 돌려도 지워지지 않는다. 사람이 S3 에서 정리한다.
  - Bronze 폴더 이름은 팀 규칙상 UTC 지만, RDS 주문에서 만든 리뷰는 사실상 KST 날짜다(주문 시뮬레이터 시각 저장 방식을 따름).
