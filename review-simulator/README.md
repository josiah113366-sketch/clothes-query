# review-simulator

가상 쇼핑몰 상품 리뷰를 Amazon Bedrock(`google.gemma-3-12b-it`, Converse API)으로 만들어
Kafka 토픽(`reviews.raw`, 정답은 `reviews.truth`)으로 보내는 시뮬레이터다.
합성 리뷰, AI Hub 리뷰, 직접 쓴 리뷰를 **말투 예시**로 쓴다. 지금은 로컬(Windows + Docker Kafka)에서 돌리고,
같은 이미지를 나중에 ECS Fargate 에 올린다.

**무엇을 쓸지(상품·별점·속성·감성)는 코드가 정하고, 문장만 LLM 이 쓴다.** 그래서 모든 리뷰에 정답 라벨이 붙는다.
쓴 문장은 검수 모델이 명세를 보지 않고 다시 라벨링해서 명세와 비교한다(검수 루프). 속성이 빠졌거나 감성이 다르면
한 번 다시 만들고, 그래도 다르면 버린다. 명세에 없는 속성을 덧붙인 경우는 버리지 않고 정답 라벨에 추가한다.

```
.local/seeds.jsonl ─┐
(말투 예시)          │
상품 목록 ───────────┼─▶ 리뷰 명세 ─▶ Bedrock(gemma) 생성 ─▶ 검수 ─▶ 리뷰 이벤트 ─▶ Kafka reviews.raw
data/incidents.json ┘   (= 정답 라벨)  (문장만 씀)          (재생성/버림)  정답 이벤트 ─▶ Kafka reviews.truth
(이상 상황)
```

## 의존하는 것

- Python 3.12, Docker (로컬 Kafka + kafka-ui. 레이크 저장만 쓰면 Docker 없이 돈다)
- Amazon Bedrock API 키 (`.env` 의 `AWS_BEARER_TOKEN_BEDROCK`, 도쿄 리전). `--llm fake` 는 키 없이 돈다
- 말투 예시 원본: 같은 PC 의 `review-analysis` 폴더 (합성 리뷰, AI Hub 데이터). 저장소에는 없다

## 코드 구조

| 경로 | 설명 |
|---|---|
| `src/rsim/cli.py` | `rsim` 명령 (run, orders-fake, inject, seeds, bench, scorecard, verify-eval, version) |
| `src/rsim/common/config.py` | 모든 설정(환경변수)과 설명 |
| `src/rsim/common/rng.py` | 시드 고정 난수, 시드 기반 UUID |
| `src/rsim/review/taxonomy.py` | 속성 11개(라벨 가이드 v3)·감성·말투 목록, AI Hub 속성 매핑 |
| `src/rsim/review/scenario.py` | 리뷰 명세, 별점·속성 분포, 이상 상황 주입, 가상 시계 |
| `src/rsim/review/seeds.py`, `catalog.py` | 말투 예시 뽑기, 상품 목록 |
| `src/rsim/review/generator.py` | 생성 프롬프트(`PROMPT_VERSION`), 검수 루프, 가짜 생성기 |
| `src/rsim/review/examples.py` | 생성 프롬프트 예시 세트(`data/examples/ex-vN.md`) 읽기 |
| `src/rsim/review/verifier.py` | 검수 프롬프트(`VERIFIER_PROMPT_VERSION`), 명세 비교, 정답 라벨 합치기 |
| `src/rsim/review/bedrock.py` | Bedrock Converse 호출 (표준 라이브러리, SDK 없음) |
| `src/rsim/review/orders.py` | 주문 기반 리뷰: 주문 읽기, 결제(RDS 는 배송완료) 후 0~7일 텀, 날짜별로 고르기, 가짜 주문 만들기 |
| `src/rsim/review/options.py` | 구매 옵션(사이즈·색상)과 포토 리뷰 여부 |
| `src/rsim/review/sinks.py`, `run.py` | Kafka / 콘솔 / 파일 전송, 실행 흐름 |
| `src/rsim/bench/` | 소량 실행으로 비용·검수 결과 확인, 예시 세트 점검표, 검수 모델 정확도 측정 |
| `src/rsim/seeds_prep.py` | 말투 예시 파일 `.local/seeds.jsonl` 만들기 |
| `data/incidents.example.json` | 이상 상황 예시 (`data/incidents.json` 으로 복사하면 적용) |
| `data/examples/` | 생성 프롬프트 예시 세트 ex-v0, ex-v1 ... (형식은 그 폴더 README) |
| `data/handwritten/` | 직접 쓴 리뷰 CSV 형식 설명 (CSV 자체는 `.local/handwritten/`) |
| `docs/prompt-sample.md` | 실제로 보내는 생성·검수 프롬프트 예시 |
| `docs/review-columns.md` | 리뷰·정답 이벤트 컬럼 설명 |
| `docs/examples-scorecard.md` | 예시 세트 버전별 성능 점검표 |
| `.local/` | 시드, 실행 결과, 벤치 결과. **커밋하지 않는다** (AI Hub 원문·생성 리뷰 원문) |
| `deploy/` | ECS 배포·운영 스크립트 (secret, deploy, onoff, switch, status, run_incident, run_inject, check_access). 사용법은 [deploy/README.md](deploy/README.md) |
| `deploy/container/entrypoint.sh` | ECS 태스크 진입점. 인자 없으면 가짜 주문 → 하루치 리뷰, 인자 있으면 `rsim <인자>` |
| `CHANGELOG.md` | 버전별 바뀐 내용 (패치노트) |

## 실행 방법 (Windows PowerShell, `review-simulator/` 폴더에서)

```powershell
# 1) 가상환경 + 패키지
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"

# 2) 설정 파일
copy .env.example .env        # AWS_BEARER_TOKEN_BEDROCK(API 키) 채우기

# 3) 말투 예시 만들기 (기본: ..\..\review-analysis, .local\handwritten\*.csv)
rsim seeds

# 4) Kafka + kafka-ui
docker compose up -d

# 5) Bedrock 없이 Kafka 까지 흐름 확인 (비용 0원)
rsim run --llm fake --sink kafka --count 20
#    → http://localhost:8081 (kafka-ui) 에서 reviews.raw 토픽 확인

# 6) Bedrock 으로 소량 생성 (비용 발생)
rsim run --sink stdout --count 5
rsim bench --yes --n 100 --max-calls 20     # 100건 비용·검수 결과 + 채점 시트 (.local\bench\)
rsim bench --yes --n 100 --examples ex-v1   # 예시 세트만 바꿔 비교 (같은 --seed 면 같은 명세)
rsim scorecard                              # bench 실행들을 점검표로 출력 (docs\examples-scorecard.md 에 붙이기)

# 테스트 (Bedrock·Kafka 없이 돈다)
ruff check . && ruff format --check .
pytest
```

## 주문 기반 실행 (결제 후 0~7일 뒤 리뷰 → S3 날짜별 경로, RDS 주문은 배송완료 후 0~7일)

2026-10-14 결정(lemin): 결제 정보를 읽어 결제 후 1~14일 뒤에 리뷰를 달고(2026-10-21 에 0~7일로 바꿈, 결제 당일 포함), **리뷰는 S3 에 날짜(dt)별로 바로 쓴다.**
RDS 에는 넣지 않는다. 상품·회원·결제 정보가 모두 S3 에 있으니 조인은 레이크(Athena 등)에서 한다.
주문은 로컬 파일(`--source orders`, 가짜 주문) 또는 **RDS orders 테이블**(`--source rds`, 2026-10-21) 에서 읽는다. 레이크는 기본이 로컬 폴더(`.local/lake`)이고, `LAKE_ROOT` 에 `s3://` 경로를 주면 S3 에 쓴다.

- 주문은 `.local/orders.jsonl` 에서 읽는다(`ORDERS_PATH`). 결제 데이터가 생기기 전에는 `rsim orders-fake` 로 만든다.
- 주문마다 리뷰를 쓸지(`REVIEW_RATE`), 며칠 뒤에 쓸지(`REVIEW_DELAY_MIN_DAYS`~`REVIEW_DELAY_MAX_DAYS`), review_id, 구매 옵션은
  **order_id 로만** 정해진다. RANDOM_SEED 가 바뀌어도 같은 주문이면 같은 값이다.
- `rsim run --source orders --date D` 는 리뷰 시각이 **D 하루(UTC)** 안에 떨어지는 주문만 만든다. `--date` 를 빼면 어제(KST 달력)다(2026-10-23 에 UTC → KST).
- `--sink lake` 는 `<LAKE_ROOT>/reviews/year=YYYY/month=MM/day=DD/part-00000.jsonl`(리뷰)과 `reviews_truth/year=.../`(정답)에 쓰고,
  **그 날짜 파티션을 통째로 덮어쓴다.** 그래서 "이미 리뷰가 있는 주문"을 조회할 필요 없이, 같은 날짜를 다시 돌려도 주문당 리뷰는 하나다.
- dt 는 데이터 시각의 날짜다(팀 규칙: Bronze 는 UTC, Silver 부터 KST). 다만 주문 시뮬레이터가 KST 벽시계 시각을 UTC 처럼 RDS 에 넣기 때문에
  RDS 주문에서 만든 리뷰의 날짜 D 는 사실상 KST 날짜 D 다. 그래서 하루 배치는 **KST 0시**에 전날(KST 달력)을 돌린다(2026-10-23 lemin).
- 생성이 실패해서 버린 리뷰는 그 파티션에서 빠진다. 다시 채우려면 그 날짜를 다시 돌린다(그날 리뷰 문장은 새로 만들어진다).
- 결제 데이터를 읽을 때는 D-7 ~ D-1 결제만 보면 된다(`orders.due_orders` 설명 참고). `--source rds` 는 이 범위만 RDS 에서 읽는다.

```powershell
# 가짜 주문 14일치 (하루 평균 1000건, Bedrock 호출 없음)
rsim orders-fake --start 2026-10-01T00:00:00+09:00 --days 14 --per-day 1000

# 10월 8일(UTC)에 리뷰 시각이 있는 주문에 리뷰 (가짜 문장, 0원)
#   → .local\lake\reviews\year=2026\month=10\day=08\part-00000.jsonl, .local\lake\reviews_truth\year=2026\...
rsim run --source orders --llm fake --sink lake --date 2026-10-08

# 다음 날
rsim run --source orders --llm fake --sink lake --date 2026-10-09
```

### RDS orders 테이블에서 읽기 (`--source rds`, 0.3.0)

업무 API 가 RDS 에 저장한 주문을 읽어 리뷰를 단다(2026-10-21 lemin 결정). `.env` 에 `ORDERS_DATABASE_URL` 을 넣는다(읽기 권한만 있으면 됨).

- 대상: **배송완료(DELIVERED)** 이고 결제(payments) SUCCESS 가 있는 주문(0.3.2, 2026-10-23 lemin. 0.3.0~0.3.1 은 PAID·SHIPPED·DELIVERED).
- 리뷰 시각: **배송완료 시각(orders.updated_at) + 0~7일**. 결제 시각(성공 결제의 completed_at)은 리뷰의 purchased_at 으로만 쓴다.
  `--source orders`(JSONL 가짜 주문)는 배송 정보가 없어 예전처럼 결제 시각 + 0~7일이다.
- **주문 항목(order_items) 하나에 리뷰 하나.** 작성 여부·텀·review_id 는 order_item_id 로 정한다(같은 항목이면 언제 돌려도 같은 값).
- 프롬프트: 상품명(prod_name)과 product_info(상품 종류·색상·무늬, product_design·product_variant), 작성자 연령대(members.age_band).
  리뷰 컬럼은 그대로이고 order_id·member_id·product_id 가 RDS 값이라 레이크에서 거래 데이터와 바로 조인된다.
- 개인정보 컬럼(이름·이메일·전화)은 읽지 않는다. 연결은 읽기 전용으로 연다.

```powershell
# 10월 21일(UTC)에 리뷰 시각이 있는 RDS 주문 항목에 리뷰 (가짜 문장, 0원)
rsim run --source rds --llm fake --sink stdout --date 2026-10-21
```

### 팀 S3 버킷에 쓰기

`.env` 에 레이크 경로를 넣으면 같은 명령이 S3 에 쓴다(버킷 이름은 공개 저장소에 넣지 않고 `.env` 에만 둔다).

```
LAKE_ROOT=s3://<버킷이름>/bronze_v2          # → s3://<버킷이름>/bronze_v2/reviews/year=YYYY/month=MM/day=DD/part-00000.jsonl
LAKE_TRUTH_ROOT=.local/lake               # 정답은 운영 레이크(bronze_v2)에 섞지 않는다. S3 에 두려면 bronze_v2 밖의 경로
```

- AWS 자격 증명은 boto3 기본 방식(`aws configure sso`, 환경변수, ECS 태스크 역할)을 쓴다. Bedrock API 키와는 별개다.
- 필요한 권한: 그 접두사에 대한 `s3:PutObject`. 같은 날짜를 다시 돌리면 같은 키로 덮어쓴다.
- S3 저장 테스트는 가짜 S3(`moto`)로 돈다. 실제 AWS 를 부르지 않는다.

## 직접 작성한 리뷰 넣기 (`rsim inject`)

특정 문장·상황을 일부러 넣어 파이프라인(감성분석 → 이상탐지)을 시험할 때 쓴다. LLM 을 부르지 않는다(0원).
형식은 `data/manual_reviews.example.csv` 를 복사해서 `.local/manual/` 아래에 만든다(커밋 금지 폴더).

```powershell
rsim inject --file .local\manual\size_spike_1008.csv --dry-run   # 형식 검사만
rsim inject --file .local\manual\size_spike_1008.csv             # LAKE_ROOT 에 쓰기
#   → <LAKE_ROOT>/reviews/year=2026/month=10/day=08/part-manual-size_spike_1008.jsonl
```

- 필수 칸: `text`, `rating`(1~5), `product_id`. 나머지(review_id, member_id, 옵션 등)는 비우면 채운다.
- `created_at` 이 없으면 지금 시각, 시간대가 없으면 KST 로 본다. `aspects`(예: `사이즈·핏:부정|배송:긍정`)를 적으면 정답(`reviews_truth/`)에도 쓴다.
- 매일 도는 `part-00000.jsonl` 과 다른 파일이라 서로 지우지 않는다. 같은 입력 파일을 다시 넣으면 그 파일만 덮어쓴다.
- 구별: `review_id` 가 `M-` 로 시작하고 `source` 가 `manual`. 지울 때는 `part-manual-*` 파일을 지운다.
- 한 줄이라도 틀리면 아무것도 쓰지 않고 줄 번호별 오류를 보여 준다.
- **직접 지어낸 문장만 넣는다.** 실제 쇼핑몰 리뷰를 옮겨 적은 자료는 S3 에 올리지 않는다(경로에 `private` 가 있으면 거부).
- ECS 에서는 입력 파일을 S3 에 올리고 `rsim inject --file s3://<버킷>/sim-input/manual/xxx.csv` 로 RunTask 를 한 번 실행한다(같은 태스크 정의, 명령만 바꿈). 필요한 권한: 입력 키 `s3:GetObject`, 레이크 접두사 `s3:PutObject`.

## 자주 바꿀 곳

| 바꾸고 싶은 것 | 위치 |
|---|---|
| 모델, 검수 모델 | `.env` 의 `BEDROCK_MODEL_ID`, `VERIFIER_MODEL_ID` |
| 호출당 리뷰 수, 재생성 횟수 | `.env` 의 `BATCH_SIZE`, `ASPECT_RETRIES` |
| 별점 분포, 별점별 감성 확률, 리뷰 길이 | `src/rsim/review/scenario.py` 상단 상수 |
| 속성 등장 빈도, 말투 종류 | `src/rsim/review/taxonomy.py` 의 `ASPECT_WEIGHTS`, `STYLES` |
| 어느 출처 말투를 더 따를지 | `src/rsim/review/seeds.py` 의 `SOURCE_WEIGHTS` |
| 생성 프롬프트 규칙 | `src/rsim/review/generator.py` 의 `SYSTEM_TEMPLATE` (바꾸면 `PROMPT_VERSION` 올리기) |
| 생성 프롬프트 예시, 말투 예시 출처 | `data/examples/ex-vN.md` 새 버전 + `.env` 의 `EXAMPLES_VERSION` (`docs/examples-scorecard.md` 에 결과 기록) |
| 검수 기준 | `src/rsim/review/verifier.py` 의 `VERIFIER_SYSTEM_PROMPT`, `BLOCKING_KINDS` |
| 불만 급증 상황 | `data/incidents.json` (형식은 `data/incidents.example.json`) |
| 주문 중 리뷰 비율, 결제 후 리뷰까지 기간 | `.env` 의 `REVIEW_RATE`, `REVIEW_DELAY_MIN_DAYS`, `REVIEW_DELAY_MAX_DAYS` |
| 사이즈·색상 분포, 포토 리뷰 비율 | `src/rsim/review/options.py` 상단 상수 |
| 레이크 저장 위치 (로컬 또는 S3) | `.env` 의 `LAKE_ROOT`, `LAKE_TRUTH_ROOT` |
| 프롬프트에 넣는 상품 정보 칸, 원본 컬럼 이름 | `src/rsim/review/catalog.py` 의 `PRODUCT_INFO_FIELDS`, `COLUMN_ALIASES` |
| 영어 색상 → 옵션 색상 이름 | `src/rsim/review/options.py` 의 `COLOR_ALIASES` |

## Kafka 메시지 (토픽 2개)

리뷰와 정답을 **다른 토픽**으로 보낸다. 운영 파이프라인은 실제처럼 라벨 없는 리뷰만 보고,
학습·채점은 정답 토픽을 따로 소비한다. 두 토픽은 `review_id` 로 이어 붙인다. 컬럼 설명은 `docs/review-columns.md`.

- `reviews.raw` (키 `product_id`, 스키마 `review.v2`): 실제 쇼핑몰 리뷰와 같은 모양. 정답 라벨 없음
- `reviews.truth` (키 `review_id`, 스키마 `review_truth.v2`): 본문 + 정답 라벨(`aspects`, 각 원소의 `source` 가
  `spec` 또는 `verifier`) + `spec_aspects` + `incident_id` + 생성 조건. `KAFKA_TRUTH_TOPIC=none` 이면 보내지 않는다
- `--sink jsonl` 이면 `reviews.jsonl` / `reviews_truth.jsonl` 두 파일로 저장한다
- `--sink lake` 이면 `<LAKE_ROOT>/reviews/year=YYYY/month=MM/day=DD/`, `<LAKE_ROOT>/reviews_truth/year=YYYY/month=MM/day=DD/` 에 날짜별로 저장한다(위 주문 기반 실행 참고)

product_id, product_name, category, member_id, age_group 은 임시 값이다. 나중에 order·member 테이블에서 가져온다.
주문 모드(`--source orders`·`rds`)에서는 `order_id`, `member_id`, `product_id` 가 주문 파일(또는 RDS) 값이고, 무작위 모드에서는 `order_id` 가 null 이다.

## 데이터 주의

- `review-analysis/private/` (실제 후기를 받아 적은 평가셋)은 Bedrock 으로 보내면 안 된다.
  `rsim seeds` 는 경로에 `private` 가 있으면 멈춘다.
- `.local/` 과 `.env` 는 커밋하지 않는다. 시드에는 AI Hub 원문(재배포 금지)이 들어 있다.
- Docker 이미지에는 `.local/seeds.jsonl` 이 들어간다. 이미지는 비공개 레지스트리(ECR)에만 올린다.

## 컨테이너로 실행 (로컬)

```powershell
docker compose --profile sim up --build simulator
```
컨테이너 안에서는 `kafka:29092` 로 접속하고, Bedrock 은 `.env` 의 API 키로 부른다.

## ECS 에서 실행 (2026-10-18, v0.2.0)

로컬과 같은 이미지·같은 `rsim` 명령을 ECS Fargate 에서 돌린다(기능 차이 없음). 하루치 실행은
`rsim orders-fake`(가짜 주문) → `rsim run --source orders --sink lake` 이고 결과는 팀 S3 `bronze_v2/reviews/` 날짜 파티션이다.
AWS 리소스는 `infra/stacks/ecs-review-simulator`(Terraform, 담당자가 apply), 배포·운영은 `deploy/*.py` 스크립트다.
예약 실행은 꺼진 상태로 만들어 두었다(2026-10-18 lemin: 계속 실행은 보류).

```powershell
python deploy/check_access.py        # 내 AWS 권한 확인 (읽기 전용)
python deploy/secret.py --from-env   # .env 의 Bedrock API 키를 Secrets Manager 에 넣기
python deploy/deploy.py              # 이미지 빌드 → ECR → 태스크 정의 등록
python deploy/onoff.py once --fake   # 한 번 실행 (비용 0원)
python deploy/status.py              # 상태·최근 실행·추정 비용
```
처음 설정 순서, 실행 옵션(특정 상품 긍정·부정 비율 올리기, 직접 쓴 리뷰 넣기), 관제는 [deploy/README.md](deploy/README.md).
PowerShell 에서는 같은 기능을 `scripts\*.ps1` 로 부를 수 있다([scripts/README.md](scripts/README.md)).
