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

- Python 3.12, Docker (로컬 Kafka + kafka-ui, 로컬 Postgres 는 `simulator/docker-compose.yml`)
- Amazon Bedrock API 키 (`.env` 의 `AWS_BEARER_TOKEN_BEDROCK`, 도쿄 리전). `--llm fake` 는 키 없이 돈다
- 말투 예시 원본: 같은 PC 의 `review-analysis` 폴더 (합성 리뷰, AI Hub 데이터). 저장소에는 없다

## 코드 구조

| 경로 | 설명 |
|---|---|
| `src/rsim/cli.py` | `rsim` 명령 (run, seeds, bench, verify-eval, version) |
| `src/rsim/common/config.py` | 모든 설정(환경변수)과 설명 |
| `src/rsim/common/rng.py` | 시드 고정 난수, 시드 기반 UUID |
| `src/rsim/review/taxonomy.py` | 속성 11개(라벨 가이드 v3)·감성·말투 목록, AI Hub 속성 매핑 |
| `src/rsim/review/scenario.py` | 리뷰 명세, 별점·속성 분포, 이상 상황 주입, 가상 시계 |
| `src/rsim/review/seeds.py`, `catalog.py` | 말투 예시 뽑기, 상품 목록 |
| `src/rsim/review/generator.py` | 생성 프롬프트(`PROMPT_VERSION`), 검수 루프, 가짜 생성기 |
| `src/rsim/review/verifier.py` | 검수 프롬프트(`VERIFIER_PROMPT_VERSION`), 명세 비교, 정답 라벨 합치기 |
| `src/rsim/review/bedrock.py` | Bedrock Converse 호출 (표준 라이브러리, SDK 없음) |
| `src/rsim/review/orders.py` | 주문 기반 리뷰: 주문 읽기, 결제 후 1~14일 텀, 가짜 주문 만들기 |
| `src/rsim/review/sinks.py`, `run.py` | Kafka / 콘솔 / 파일 전송, 실행 흐름 |
| `src/rsim/bench/` | 소량 실행으로 비용·검수 결과 확인, 검수 모델 정확도 측정 |
| `src/rsim/seeds_prep.py` | 말투 예시 파일 `.local/seeds.jsonl` 만들기 |
| `data/incidents.example.json` | 이상 상황 예시 (`data/incidents.json` 으로 복사하면 적용) |
| `data/handwritten/` | 직접 쓴 리뷰 CSV 형식 설명 (CSV 자체는 `.local/handwritten/`) |
| `docs/prompt-sample.md` | 실제로 보내는 생성·검수 프롬프트 예시 |
| `docs/review-columns.md` | 리뷰·정답 이벤트 컬럼 설명 |
| `.local/` | 시드, 실행 결과, 벤치 결과. **커밋하지 않는다** (AI Hub 원문·생성 리뷰 원문) |

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

# 테스트 (Bedrock·Kafka 없이 돈다)
ruff check . && ruff format --check .
pytest
```

## 주문 기반 실행 (결제 후 1~14일 뒤 리뷰)

확정한 구상(2026-10-14): 결제 시뮬레이터가 RDS 에 쌓은 결제를 읽고, 결제 후 1~14일이 지난 주문에 리뷰를 단다.
리뷰는 RDS `reviews` 테이블에 쓰고 RDS → CDC → Kafka → S3 로 흘린다. **지금은 RDS 가 없어서 로컬 기준으로 돈다.**

- 주문은 로컬 파일 `.local/orders.jsonl` 에서 읽는다(`ORDERS_PATH`). 결제 시뮬레이터가 생기기 전에는 `rsim orders-fake` 로 만든다.
- 주문마다 리뷰를 쓸지(`REVIEW_RATE`)와 며칠 뒤에 쓸지(`REVIEW_DELAY_MIN_DAYS`~`REVIEW_DELAY_MAX_DAYS`)는
  **order_id 로만** 정해진다. RANDOM_SEED 가 바뀌어도 같은 주문의 리뷰 날짜는 같다.
- `rsim run --source orders` 는 `결제 시각 + 텀 ≤ --now` 이고 아직 리뷰가 없는 주문만 만든다. 리뷰 시각(`created_at`)은 그 주문의 리뷰 시각이다.
- 리뷰는 **로컬 Postgres 의 `reviews` 테이블**에 넣는다(`--sink postgres`, 2026-10-14 lemin 결정). 회원 시뮬레이터와 같은 DB 다.
  정답 라벨은 DB 에 넣지 않고 `.local/out/reviews_truth.jsonl` 에 쓴다. 나중에 `DATABASE_URL` 만 RDS 로 바꾼다.
- "아직 리뷰가 없는지"는 `reviews` 테이블의 `order_id` 로 판단한다(같은 주문은 UNIQUE 라 두 번 들어가지 않는다).
  `--sink jsonl` 은 리뷰 파일의 `order_id` 로 같은 판단을 한다. stdout·kafka 는 보낸 기록을 몰라서 차례가 된 주문을 매번 전부 보낸다.
- 리뷰 생성이 실패한 주문은 리뷰가 없으므로 다음 실행에서 다시 골라진다.

```powershell
# 로컬 Postgres 띄우기 (simulator 폴더의 compose. 빈 볼륨으로 처음 띄울 때 db\schema\*.sql 이 자동 적용된다)
cd ..\simulator; docker compose up -d; cd ..\review-simulator
# 이미 볼륨이 있어서 reviews 테이블이 없으면 한 번만 직접 적용
Get-Content ..\db\schema\003_review.sql | docker compose -f ..\simulator\docker-compose.yml exec -T postgres psql -U sim -d clothes

# 가짜 주문 14일치 (하루 평균 1000건, Bedrock 호출 없음)
rsim orders-fake --start 2026-10-01T00:00:00+09:00 --days 14 --per-day 1000

# 10월 8일 0시 기준으로 차례가 된 주문에 리뷰 (가짜 문장, 0원) → reviews 테이블
rsim run --source orders --llm fake --sink postgres --now 2026-10-08T00:00:00+09:00

# 하루 뒤 기준으로 다시 돌리면 그 사이 차례가 된 주문만 추가된다
rsim run --source orders --llm fake --sink postgres --now 2026-10-09T00:00:00+09:00

# 확인
docker compose -f ..\simulator\docker-compose.yml exec postgres psql -U sim -d clothes -c "select count(*) from reviews"
```

Postgres 통합 테스트는 `TEST_DATABASE_URL` 이 있을 때만 돈다(`tests/test_postgres_sink.py`, 임시 스키마를 만들고 지운다).

## 자주 바꿀 곳

| 바꾸고 싶은 것 | 위치 |
|---|---|
| 모델, 검수 모델 | `.env` 의 `BEDROCK_MODEL_ID`, `VERIFIER_MODEL_ID` |
| 호출당 리뷰 수, 재생성 횟수 | `.env` 의 `BATCH_SIZE`, `ASPECT_RETRIES` |
| 별점 분포, 별점별 감성 확률, 리뷰 길이 | `src/rsim/review/scenario.py` 상단 상수 |
| 속성 등장 빈도, 말투 종류 | `src/rsim/review/taxonomy.py` 의 `ASPECT_WEIGHTS`, `STYLES` |
| 어느 출처 말투를 더 따를지 | `src/rsim/review/seeds.py` 의 `SOURCE_WEIGHTS` |
| 생성 프롬프트 | `src/rsim/review/generator.py` 의 `SYSTEM_PROMPT` (바꾸면 `PROMPT_VERSION` 올리기) |
| 검수 기준 | `src/rsim/review/verifier.py` 의 `VERIFIER_SYSTEM_PROMPT`, `BLOCKING_KINDS` |
| 불만 급증 상황 | `data/incidents.json` (형식은 `data/incidents.example.json`) |
| 주문 중 리뷰 비율, 결제 후 리뷰까지 기간 | `.env` 의 `REVIEW_RATE`, `REVIEW_DELAY_MIN_DAYS`, `REVIEW_DELAY_MAX_DAYS` |

## Kafka 메시지 (토픽 2개)

리뷰와 정답을 **다른 토픽**으로 보낸다. 운영 파이프라인은 실제처럼 라벨 없는 리뷰만 보고,
학습·채점은 정답 토픽을 따로 소비한다. 두 토픽은 `review_id` 로 이어 붙인다. 컬럼 설명은 `docs/review-columns.md`.

- `reviews.raw` (키 `product_id`, 스키마 `review.v1`): 실제 쇼핑몰 리뷰와 같은 모양. 정답 라벨 없음
- `reviews.truth` (키 `review_id`, 스키마 `review_truth.v1`): 본문 + 정답 라벨(`aspects`, 각 원소의 `source` 가
  `spec` 또는 `verifier`) + `spec_aspects` + `incident_id` + 생성 조건. `KAFKA_TRUTH_TOPIC=none` 이면 보내지 않는다
- `--sink jsonl` 이면 `reviews.jsonl` / `reviews_truth.jsonl` 두 파일로 저장한다
- `--sink postgres` 이면 리뷰는 `reviews` 테이블(`db/schema/003_review.sql`, `created_at`→`written_at`, `text`→`body`), 정답은 `reviews_truth.jsonl`

product_id, product_name, category, member_id, age_group 은 임시 값이다. 나중에 order·member 테이블에서 가져온다.
주문 모드(`--source orders`)에서는 `order_id`, `member_id`, `product_id` 가 주문 파일 값이고, 무작위 모드에서는 `order_id` 가 null 이다.

## 데이터 주의

- `review-analysis/private/` (실제 후기를 받아 적은 평가셋)은 Bedrock 으로 보내면 안 된다.
  `rsim seeds` 는 경로에 `private` 가 있으면 멈춘다.
- `.local/` 과 `.env` 는 커밋하지 않는다. 시드에는 AI Hub 원문(재배포 금지)이 들어 있다.
- Docker 이미지에는 `.local/seeds.jsonl` 이 들어간다. 이미지는 비공개 레지스트리(ECR)에만 올린다.

## 컨테이너로 실행 (ECS 이전 확인)

```powershell
docker compose --profile sim up --build simulator
```
컨테이너 안에서는 `kafka:29092` 로 접속하고, Bedrock 은 `.env` 의 API 키로 부른다.
ECS 에서는 API 키를 Secrets Manager 등으로 넣고(태스크 역할만 쓰려면 SigV4 서명 작업이 따로 필요),
`KAFKA_BOOTSTRAP` 을 실제 브로커 주소로 바꾼다.
