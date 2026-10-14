# 작업 지시서: sim/review-baseline

> 상태: 커밋 완료, 사용자 확인 대기 (push·PR 전) · 브랜치: `sim/review-baseline` · 다음 작업: 미정 (Kafka 실전송 확인, order·member 테이블 연결)

## 목표

PC 에서 따로 개발하던 리뷰 시뮬레이터(`C:\workspace\e-commerce\review-simulator`, 생성 프롬프트 p5.6 · 검수 v2)를
이 저장소의 **`review-simulator/`** 폴더로 옮기고, `simulator/` 폴더와 같은 규격(pyproject, `src/` 레이아웃, typer CLI,
ruff, pytest, Docker, `.env.example`, `CLAUDE.md`, `README.md`)으로 맞춘다. 이 폴더가 리뷰 쪽 프로젝트 폴더가 된다.

만들지 않는 것: 리뷰 생성 규칙·프롬프트 변경, order·member 테이블 연결(아직 테이블 없음), ECS 배포.

## 먼저 읽을 것

- 루트 `CLAUDE.md`, `simulator/CLAUDE.md` (폴더 규격의 기준)
- `review-simulator/README.md`, `review-simulator/docs/prompt-sample.md`

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- 브랜치는 lemin 의 `sim/review-baseline` 을 쓴다(자기 커밋이 없어서 최신 `main` 으로 fast-forward 후 작업).
- 옮기기 전에 쓰지 않는 코드를 정리했다(2026-10-14 lemin 승인):
  Claude 전용 생성기(anthropic SDK)·AWS 프로필 경로, 생성 모델의 evidence(근거 문구) 출력과 자체 검사(→ 프롬프트 p5.6),
  벤치마크의 모델 목록·호출 확인·자동 선택 옵션, 중복된 Bedrock 호출 코드.
- 속성은 감성분석 라벨 가이드 v3 와 같은 11개(활용성·사용감 추가)다.
- 공개 저장소라 시드(`.local/seeds.jsonl`, AI Hub 원문)·생성 리뷰·벤치 결과·사람 채점 파일은 커밋하지 않는다.
  `docs/prompt-sample.md` 의 말투 예시 원문과 상품명도 자리표시로 바꿨다.

## 만든 것

### 1. 폴더 골격
`pyproject.toml`(패키지 `rsim`, 명령 `rsim`), `Dockerfile`, `.dockerignore`, `docker-compose.yml`(Kafka + kafka-ui,
시뮬레이터는 `sim` 프로필), `.env.example`(더미 값), `CLAUDE.md`, `README.md`, 루트 `.gitignore` 에 `review-simulator/.local/`.

### 2. 코드 이전
- `src/rsim/common/` 설정, 시드 고정 난수(`derive_seed`, `seeded_uuid`). `uuid.uuid4()` 대신 시드 기반 ID 를 쓴다
  (회원 ID 는 별도 난수열이라 같은 시드의 예전 명세 순서는 그대로다).
- `src/rsim/review/` 명세·생성·검수·전송, `src/rsim/bench/` 소량 실행·검수 정확도, `src/rsim/seeds_prep.py` 시드 만들기.
- argparse 를 typer 명령으로 바꿨다: `rsim run | seeds | bench | verify-eval | version`. 옵션 이름은 예전과 같다.
- 경로는 현재 작업 폴더(`review-simulator/`) 기준이다. 시드 기본 경로는 `.local/seeds.jsonl`,
  review-analysis 기본 경로는 `../../review-analysis`.

### 3. 테스트
속성 11개·매핑, 같은 시드 = 같은 명세, 검수 비교·정답 합치기, 프롬프트 파싱, 검수 루프(재생성·버림),
CLI(가짜 생성기 → jsonl, 재현성, 키 없을 때 멈춤, bench 는 `--yes` 없이 호출 안 함). Bedrock·Kafka 를 부르지 않는다.

### 4. 주문 기반 리뷰 (2026-10-14 lemin 요청, 로컬 기준)
확정한 구상: 결제 시뮬레이터의 결제를 RDS 에서 읽어 결제 후 1~14일 뒤 리뷰를 만들고, 리뷰는 RDS `reviews` 테이블에 쓴 뒤
RDS → CDC → Kafka → S3 로 흘린다(하루 약 1,000건). RDS·결제 테이블이 아직 없어서 이번에는 로컬 기준으로 만든다.
- `src/rsim/review/orders.py`: 주문 읽기(`JsonlOrderSource`, 나중에 RDS 용으로 교체), 주문별 리뷰 여부·텀(`ReviewTiming`,
  order_id 로만 결정), 차례가 된 주문 고르기(`due_orders`), 가짜 주문(`fake_orders`)
- `rsim orders-fake`: 가짜 주문 파일 `.local/orders.jsonl`
- `rsim run --source orders [--now 시각]`: 차례가 되었고 아직 리뷰가 없는 주문에만 리뷰. 리뷰·정답 이벤트에 `order_id` 추가
- 설정: `ORDERS_PATH`, `REVIEW_RATE`(기본 1.0, 주문 중 리뷰 비율), `REVIEW_DELAY_MIN_DAYS`/`MAX_DAYS`(1/14)
- 리뷰 저장처: 로컬 Postgres `reviews` 테이블(2026-10-14 lemin 결정). `db/schema/003_review.sql`, `rsim run --sink postgres`(`DATABASE_URL`).
  정답 라벨은 DB 에 넣지 않고 `.local/out/reviews_truth.jsonl` 에 쓴다. 이미 리뷰가 있는 주문은 테이블의 order_id(UNIQUE)로 거른다.
  Postgres 통합 테스트(`tests/test_postgres_sink.py`)는 `TEST_DATABASE_URL` 이 있을 때만 돈다.

## 완료 확인

- [x] `ruff check . && ruff format --check .`
- [x] `pytest`
- [x] `rsim run --llm fake --sink stdout --count 5` (비용 0원)
- [x] 가짜 Bedrock 응답으로 `rsim run`, `rsim bench --yes` 흐름 확인 (실제 호출 없음)
- [x] 스테이징에 키·계정 ID·리뷰 원문이 없는지 확인
- [ ] (사용자) Windows 에서 `pip install -e ".[dev]"`, `.env`·`.local/seeds.jsonl` 확인 후 `rsim bench --yes --n 100`
- [ ] (사용자) `docker compose up -d` 후 `rsim run --llm fake --sink kafka --count 20`
- [x] 주문 기반: `rsim orders-fake --start 2026-10-01T00:00:00+09:00 --days 14 --per-day 1000` 후 `rsim run --source orders --llm fake --sink jsonl|postgres --now ...` 를 날짜를 바꿔 반복해도 주문당 리뷰 1건 (Postgres 16 로 확인)
- [ ] (사용자) Windows 에서 `simulator` compose 로 Postgres 를 띄우고 `003_review.sql` 적용 후 `--sink postgres` 실행

## README 갱신

- 루트 `README.md`, 루트 `CLAUDE.md` 폴더 표, `review-simulator/README.md`
