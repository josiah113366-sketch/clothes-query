# 작업 지시서: dashboard/gold-b-scenarios

> 상태: 검토 대기 · 브랜치: `dashboard/gold-b-scenarios` (최신 `main` `25feba2`) · 담당: 은서 (`dashboard/TODO.md` B10) · 다음 작업: PR (사용자), 배포 (main 자동 배포 #113), 결제 뷰 읽기 권한 (재영 님) (2026-10-25 사용자: "2번 필요한 대시보드 만들어줘")

## 목표

2026-10-25 Gold B 점검에서 대시보드로 판단할 수 없던 시나리오 2·3의 칸을 만든다.

- **시나리오 2 (S3 Sink 정지·폭주):** 파이프라인 상태 › 지연·점검 탭에 **토픽별 유입** 그래프. 지연이 커질 때 유입도 늘었는지(폭주), 그대로인지(S3 Sink 자체의 문제) 가른다 (판정 R3의 유입·지연 해석표).
- **시나리오 3 (데이터 오염, 성공 결제 중복):** 결제 관제에 **성공 결제가 2건 이상인 주문** 칸 (판정 R5).

만들지 않는 것: 이상탐지 화면 실데이터(B2, 주현 님), 신뢰성 점검(B3), 주문 총액 불일치(R6, Silver), 기존 화면의 "비면 더미" 규칙 변경.

## 먼저 읽을 것

- `docs/design/agent/anomaly-answer-key.md` 4절 (R3 유입·지연 해석표, R5), 7절 (사건)
- `docs/design/gold-b/scenario-checks.md` (`pipelines/gold-b-ops-fixes`의 시연 점검표)
- `dashboard/data.py` (`dataset`, `_REAL`, `_athena`, `_hour_partitions`), `dashboard/pages_data/payments.py`, `dashboard/pages_data/pipeline.py`

## 정한 기본값 (설계에 없는 세부, 2026-10-25 사용자 "필요한 대시보드 만들어줘")

1. **유입:** `gold_b.topic_messages`의 1분 × 토픽 메시지 수 (Kafka 시각, 최근 180분 = 지연 그래프와 같은 길이, 시간 폴더 조건). 적재 잡이 1분 묶음으로 쓰므로 지금 분과 직전 분은 덜 찼을 수 있어 뺀다.
2. 토픽마다 크기가 수십~수천 배 달라서(클릭 분당 약 2,000건, 결제 약 16건) 그래프는 **조회 구간 중앙값 대비 배수**(1 = 평소)로 한 장에 그리고, 최근 1분 실제 건수를 설명에 적는다.
3. **성공 결제 중복:** `gold_b.payment_attempts` 뷰에서 최근 6시간에 **적재된** 성공 결제의 주문 중 성공이 2건 이상인 주문 (판정 R5와 같은 방식. 중복 행의 결제 시각은 과거일 수 있어 적재 시각 기준). 최대 200줄.
4. 두 칸은 비어 있는 것이 정상(중복 0건)이거나 그 자체가 신호(유입 끊김)라 **"비면 더미" 규칙에서 뺀다:** `dataset`에 `allow_empty` 선택지를 두고(기본값은 지금 동작) 두 함수에만 쓴다. 조회가 실패하면 지금처럼 더미다.
5. 성공 결제 중복은 뷰를 읽어서, 대시보드 역할에 `payment_states`·`payment_attempts` 읽기 권한(F3)이 있어야 실데이터다. 없으면 조회 실패라 더미가 보이고 칸 아래에 "※ 이 칸은 더미 데이터입니다."가 나온다.
6. 더미: 유입은 45~30분 전 15분 동안 5배 폭주, 성공 결제 중복은 2주문.
7. 정리: #110 머지 표시 (브랜치 대장, `dashboard-gold-b-data` 작업 지시서, TODO B1).

## 작업 순서

1. 이 지시서, 브랜치 대장, #110 정리
2. `dataset`의 `allow_empty`, 조회 함수 2개(더미·실데이터)와 등록
3. 화면 2곳과 시험
4. 실제 Athena에서 SQL 확인
5. README·TODO와 작업 결과

## 완료 확인

- [x] `python test_gold_b_scenarios.py` 통과 (dashboard 폴더에서)
- [x] 기존 시험: `python test_gold_b_data.py`, `python test_approval_page.py`, `python -m pytest -q test_gold_a_io.py`
- [x] 실제 Athena에서 두 SQL이 돈다
- [x] `git diff --check`

## 작업 결과 (머지 전에 작성한다)

### 만든 것

- `dashboard/data.py`
  - `dataset(ttl, allow_empty=False)`: `allow_empty=True`면 실데이터가 비어도 더미로 바꾸지 않는다. 기본값은 지금 동작 그대로라 다른 화면은 바뀌지 않는다.
  - `get_topic_inflow(분)`: 더미(45~30분 전 5배 폭주)와 실데이터 `_real_topic_inflow` (`gold_b.topic_messages` 1분 × 토픽, 시간 폴더 조건, 덜 찬 지금 분·직전 분 제외).
  - `get_duplicate_success(시간)`: 더미(2주문)와 실데이터 `_real_duplicate_success` (`gold_b.payment_attempts`, 최근 적재된 성공 결제의 주문 중 성공 2건 이상, 판정 R5와 같은 방식, 최대 200줄).
  - 둘 다 workgroup 환경변수가 있을 때 `_REAL`에 등록하고 `allow_empty=True`다.
- 화면
  - 결제 관제: 「성공 결제가 2건 이상인 주문」 칸 (있으면 빨간 경고와 주문·결제 번호·PG·결제 시각·적재 시각 표, 없으면 "없습니다 (정상)"). 이 칸만 더미면 칸 아래에 "※ 이 칸은 더미 데이터입니다.". 맨 위 설명에 시나리오 3을 더했다.
  - 파이프라인 상태 › 지연·점검: 「토픽별 유입 (평소 대비)」 그래프 (토픽마다 조회 구간 중앙값 = 1, 점선 1) 와 최근 1분 건수. 비면 "적재 잡이 멈췄는지 확인" 경고. 탭 아래 더미 안내에 "유입"을 더했다.
- `dashboard/test_gold_b_scenarios.py` (28개): 등록, 두 SQL(표, 적재 시각 기준, 시간 폴더, 덜 찬 분 제외)·칸·형식, 빈 결과는 그대로(형식 오류는 지금처럼 더미), 조회 실패는 더미, 두 화면을 더미·실제 모양·빈 데이터로 연다 (`AppTest`).
- 문서: `dashboard/README.md` 배포 7번, `dashboard/TODO.md` B10(새 줄)·B1(완료), #110 머지 표시.

### 왜

- 시나리오 2에서 지연이 커졌을 때 폭주인지 S3 Sink 문제인지 가르려면 유입을 같이 봐야 하는데, 데이터 흐름 탭은 마지막 적재 시각과 오늘 건수만 보여 줬다.
- 시나리오 3(성공 결제 중복)은 형식이 맞는 데이터라 형식 오류 화면에 안 나오고, 결제 관제에도 보이는 곳이 없었다. 중복 행의 결제 시각은 과거일 수 있어 결제 시각 기준 "최근 6시간" 목록으로는 놓친다.
- "비면 더미" 규칙을 그대로 쓰면 중복 0건(정상)일 때 가짜 중복 주문이, 유입이 끊겼을 때 가짜 유입이 보여 판단을 틀리게 한다.

### 확인한 결과

- `python test_gold_b_scenarios.py` 28개, `python test_gold_b_data.py` 30개, `python test_approval_page.py` 28개, `python -m pytest -q test_gold_a_io.py` 19개 통과 (로컬 Python 3.12, streamlit 1.59.2. `streamlit_echarts`가 없는 PC라 그리기는 빈 함수로 대신).
- 코드를 일부러 틀리게 바꾼 9가지(두 함수의 `allow_empty`, 데코레이터 조건, 적재 시각 → 결제 시각, 덜 찬 분 조건, 유입 등록, 더미 안내의 "유입", 최근 1분 값, 빈 결과 안내)를 시험이 모두 잡았다.
- 실제 Athena (은서 님 AWS 자격, 대시보드 workgroup, SELECT만): 유입 900줄(180분 × 토픽 5개, 분당 중앙값 clickstream 2,051·order-items 54·orders 47·payments 16·members-events 15, 2초), 성공 결제 중복 0줄(최근 7일 적재분, 10초). 칸·형식이 맞다.

### 알아 둘 것

- 성공 결제 중복 칸은 대시보드 역할에 결제 뷰 읽기 권한이 생겨야 실데이터다 (지금은 `TABLE_NOT_FOUND`로 실패해 더미, F3).
- 형식 오류·재처리 이력도 평소 비어 있는 게 정상이라 `allow_empty=True`가 맞을 수 있다. 화면 주인(민혁 님)과 정한 뒤 한 줄씩 바꾸면 된다.

### 다음 할 일

- 사용자: push, PR (머지하면 main 자동 배포 #113으로 대시보드에 반영)
- 재영 님: 대시보드 역할에 뷰 `payment_states`·`payment_attempts`의 `glue:GetTable` (#115에 함께)
- 민혁 님: 형식 오류·재처리 이력의 "비면 더미" 규칙 정하기
