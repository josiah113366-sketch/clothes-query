# deploy/ — ECS 배포·운영 스크립트 (v0.2.0, 2026-10-18)

리뷰 시뮬레이터를 ECS Fargate 에서 돌리기 위한 스크립트다. 모두 `review-simulator/` 폴더에서 PowerShell 로 실행한다.
AWS 리소스는 `infra/stacks/ecs-review-simulator`(Terraform)가 만들고, 스크립트는 그 스택이 남긴 SSM 파라미터
`/clothes-query/dev/ecs-review-simulator/config` 만 읽는다. 그래서 저장소에 계정 ID·버킷 이름을 적지 않는다.

```
deploy.py ──▶ ECR 이미지 + 태스크 정의(새 리비전) ◀── switch.py (REVIEW_RATE 만 바꿈)
                         │
   onoff.py on/off ──▶ 예약 실행(매일 00:00 KST, 처음엔 꺼짐)
   onoff.py once / run_incident.py / run_inject.py ──▶ 한 번 실행
                         │
                         ▼
   ECS 태스크: entrypoint.sh → rsim orders-fake → rsim run --source orders --sink lake → S3 bronze/reviews/
                         │
   status.py, CloudWatch 대시보드 ◀── 로그·종료 기록
```

## 스크립트

| 스크립트 | 하는 일 |
|---|---|
| `check_access.py` | 내 AWS 계정에 필요한 권한이 있는지 읽기 전용으로 확인 (IAM 정책 시뮬레이터) |
| `secret.py` | Bedrock API 키를 Secrets Manager 에 넣기·바꾸기 (`--from-env`, `--check`). `--orders-db` 면 RDS 접속 주소. 값은 출력하지 않음 |
| `deploy.py` | 이미지 빌드 → ECR push(태그 `<버전>-<커밋>`) → 태스크 정의 새 리비전 등록 |
| `onoff.py` | `on` 예약 실행 켜기 / `off` 끄기 + 돌고 있는 태스크 멈춤 / `once` 지금 한 번 |
| `switch.py` | 실행 모드 = 리뷰 작성 비율. `low` 0.1 · `normal` 0.5 · `high` 1.0 · `--rate 0.3`. 주문 입력 `--orders rds` / `--orders fake` |
| `status.py` | 스케줄·실행 설정·돌고 있는 태스크·최근 실행(리뷰 수, 토큰, 추정 비용)·S3 마지막 날짜. `--cost` 실제 청구액 |
| `run_incident.py` | 특정 상품·카테고리의 긍정·부정 리뷰 비율을 올려 하루치 실행 (이미 있는 incidents 기능) |
| `run_rds.py` | RDS 주문으로 실제 리뷰(Bedrock) 한 번: secret 확인 → 주문 입력 rds 로 맞춤 → 실행 (비용 확인 후 시작, `--yes`) |
| `run_inject.py` | 직접 쓴 리뷰 파일을 검사 → S3 업로드 → `rsim inject` 한 번 실행 |
| `container/entrypoint.sh` | 이미지 안의 진입점. 인자 없으면 하루치(`ORDERS_SOURCE` fake / rds), 인자 있으면 `rsim <인자>` |

공통 옵션 `--region`(기본 `AWS_REGION` 또는 ap-northeast-1). 각 스크립트 `-h` 에 예시가 있다.

## 처음 한 번 (순서대로)

1. **권한 확인**: `aws login`(또는 `aws configure sso`) 후 `python deploy/check_access.py`. '거부' 항목은 재영님께 요청한다.
2. **Terraform** (`infra/stacks/ecs-review-simulator/README.md`): 비공개 파일 두 개를 만들고 plan 을 확인한 뒤 apply 한다.
   예약 실행은 꺼진 상태로 만들어진다.
3. **Bedrock API 키**: `python deploy/secret.py --from-env` (`.env` 의 `AWS_BEARER_TOKEN_BEDROCK`). `--check` 로 확인.
4. **이미지 배포**: Docker Desktop 을 켜고 `python deploy/deploy.py`. `.local/seeds.jsonl` 이 이미지에 들어간다.
   커밋 안 한 변경이 있으면 태그에 `-dirty<시각>` 이 붙는다.
5. **시험 실행**: `python deploy/onoff.py once --fake` (Bedrock 호출 없음) → `python deploy/status.py` 로
   종료 코드 0, 리뷰 수, S3 마지막 날짜를 본다. 다음에 `python deploy/onoff.py once` 로 Bedrock 실행(하루 약 100건, 약 $0.02).
6. **계속 실행**(보류 중): 정해지면 `python deploy/onoff.py on`. 끌 때는 `off`.

## 실행 옵션

```powershell
# 특정 상품: 그날 W-0003 리뷰의 60% 에 품질 불만(별점도 1~3점)
python deploy/run_incident.py --product-id W-0003 --aspect 품질·내구성 --sentiment 부정 --share 0.6 --date 2026-10-17
# 카테고리 전체, 긍정 쪽으로
python deploy/run_incident.py --category 패션슈즈 --aspect 색상·디자인 --sentiment 긍정 --share 0.5
# 직접 쓴 리뷰 (형식: data/manual_reviews.example.csv)
python deploy/run_inject.py --file .local/manual/size_spike_1008.csv
```
- `run_incident.py` 는 그날 파티션(`part-00000.jsonl`)을 덮어쓴다. 원래대로 돌리려면 같은 날짜로 `onoff.py once --date …`.
  `--dry-run` 은 JSON 만 보여 주고, `--fake` 는 Bedrock 없이 돈다. 상품 ID 는 `.local/seeds.jsonl` 이 있으면 미리 확인한다.
- `run_inject.py` 는 `part-manual-<파일 이름>.jsonl` 로 따로 써서 매일 실행분을 지우지 않는다. 같은 이름으로 다시 넣으면 덮어쓴다.
- 입력 파일은 `s3://<버킷>/sim-input/review-simulator/{incidents,manual}/` 에 올라간다(태스크가 읽을 수 있는 유일한 입력 경로).

## RDS 주문 읽기 (`ORDERS_SOURCE=rds`, v0.3.0, 2026-10-21)

가짜 주문 대신 RDS orders 테이블(업무 API 가 저장한 주문)을 읽어 하루치 리뷰를 만든다. 실행 방식(하루 1번)은 같다.
처음 배포 상태는 `fake` 이고, 아래 순서를 마친 뒤 `rds` 로 바꾼다.

1. **Terraform apply** (`infra/stacks/ecs-review-simulator`): RDS 접속 주소 secret(빈 값)과 5432 나가는 규칙이 추가된다.
   `terraform output security_group_id` 로 태스크 보안 그룹 ID 를 확인한다.
2. **RDS 쪽 허용** (RDS 스택 담당): `infra/stacks/rds` 의 비공개 tfvars `database_clients` 에
   `review_simulator = "<위 보안 그룹 ID>"` 를 넣고 apply. RDS 보안 그룹에 5432 들어오는 규칙이 생긴다.
3. **읽기 전용 DB 계정** (DB 관리자가 한 번, master 계정으로 접속해서). 비밀번호는 직접 정해 저장소에 남기지 않는다.
   ```sql
   CREATE ROLE review_sim_ro LOGIN PASSWORD '<비밀번호>';
   GRANT CONNECT ON DATABASE postgres TO review_sim_ro;  -- 테이블은 postgres DB 에 있다(2026-10-21 lemin 확인)
   GRANT USAGE ON SCHEMA public TO review_sim_ro;
   -- 리뷰 시뮬레이터가 읽는 테이블만 (회원은 member_id·age_band 만 쓰지만 테이블 단위 권한이라 SELECT 를 준다)
   GRANT SELECT ON orders, order_items, payments, product_variant, product_design, members TO review_sim_ro;
   ```
4. **접속 주소 저장**: `python deploy/secret.py --orders-db` → `postgresql://review_sim_ro:<비밀번호>@<RDS 주소>:5432/postgres?sslmode=require` 입력 (DB 이름은 postgres).
   localhost(port-forward) 주소는 ECS 에서 못 쓰므로 거절된다. `--orders-db --check` 로 확인.
5. **이미지 배포**: `python deploy/deploy.py` (0.3.0 이미지에 `--source rds` 와 psycopg 가 들어 있다).
6. **전환**: `python deploy/switch.py --orders rds` (secret 이 비어 있으면 거절). 되돌리기는 `--orders fake`.
7. **시험 실행**: `python deploy/onoff.py once --fake`(가짜 문장, 0원) → `status.py`/로그에서 `RDS 주문 항목 N건 읽음` 줄과 리뷰 수를 본다.
8. **실제 생성**: `python deploy/run_rds.py`(PowerShell `.\scripts\run-rds.ps1`). 접속 secret 이 비었거나 배포 전이면 알려 주고 멈춘다(RDS 쪽 허용·DB 계정은 확인하지 못하므로 로그에서 접속 오류를 본다).
   6번(전환)을 건너뛰어도 이 스크립트가 rds 로 맞춘다. Bedrock 비용 안내 후 y 를 눌러야 시작한다.
   RDS 에 그날 리뷰 시각인 주문이 없으면 리뷰 0건으로 정상 종료한다(결제 후 0~7일이라 결제 당일 주문부터 리뷰가 나온다).

## 관제 (상태·비용)

- `python deploy/status.py`: 한 화면 요약. 최근 실행의 추정 비용 = 토큰 수 x 단가(`src/rsim/bench/prices.json`).
- CloudWatch 대시보드 `clothes-query-dev-ecs-review-simulator`: 실행별 리뷰 수·토큰·추정 비용, 실패한 실행/ERROR 줄 수,
  태스크 종료 기록(종료 코드·이유), 최근 ERROR/WARNING 로그.
- 선택: Terraform 비공개 입력에 `alarm_email`(실패 알림), `budget_email`(월 예산 알림, 기본 $10)을 넣으면 만들어진다.
  예산은 태그 `Component=ecs-review-simulator` 비용(Fargate, ECR, 로그, Secret)만 보며, 결제 콘솔에서 이 태그를
  비용 할당 태그로 한 번 활성화해야 한다. Bedrock(API 키 호출)은 태그가 안 붙어 대시보드 추정치와 `status.py --cost` 로 본다.
- 예상 비용(하루 1,000건): Bedrock 약 $6/월, Fargate 약 $0.5/월, 로그·ECR 몇 센트.

## 로컬과 다른 점

리뷰를 만드는 코드와 명령은 같다. 다른 점은 아래뿐이다.
- 주문: 기본(`ORDERS_SOURCE=fake`)은 태스크마다 가짜 주문을 다시 만든다(고정 시작일·시드라 매번 같은 주문).
  `rds` 로 바꾸면 RDS orders 테이블을 읽는다(위 "RDS 주문 읽기"). 로컬은 `.env` 의 `ORDERS_DATABASE_URL`(port-forward 주소 가능).
- 정답 라벨(`reviews_truth`)은 S3 에 쓰지 않는다(차후 개선, 2026-10-18 lemin).
- Kafka 로는 보내지 않는다(`--sink lake`).
