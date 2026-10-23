# 작업 지시서: pipelines/gold-b-payment-update

> 상태: 진행 중 · 브랜치: `pipelines/gold-b-payment-update` (최신 `main` #92 위의 머지 정리 커밋 `8ca6a10`에서, `pipelines/gold-b-image`와 같은 출발점) · 다음 작업: 계획 확인 (사용자)

## 목표

RDS에서 결제가 수정되면(`__op = u`) Gold B가 Silver와 같은 규칙으로 수정된 최신 상태를 반영한다. 원장 ① `payment_events`에는 변경 전후 이벤트를 모두 남기고, 정리 뷰 `payment_attempts`는 최신 상태를, `payment_conflicts`는 진짜 충돌만 보여준다. 형식 오류가 있는 결제는 Silver처럼 보류한다.

## 먼저 읽을 것

- 팀 합의 방향 (2026-10-23, 사용자 전달): 결제 `u` 처리, 원장에 변경 이력 보존, 최신 상태 뷰, 정상 수정은 충돌 아님, 재처리 검증 항목
- `pipelines/silver/transactions.py`, `pipelines/silver/common.py`: Silver의 CDC 규칙 (`_check_cdc`, `_version`, `collect_latest`)
- `docs/design/gold-b/README.md`: ①④ 표, 「처리 규칙」 중복 제거, 정리 뷰 SQL, 2단계 CDC 표시

## 사용자 결정 (2026-10-23)

1. 결제 `u`도 처리한다 (팀 합의).
2. ④ `malformed_events`에 `record_key`를 더해, 형식 오류가 있는 결제는 Silver처럼 보류한다.
3. `raw_sample`은 결제·주문 ID와 시각만 풀고, 회원 정보는 계속 가린다.

## 정한 기본값 (설계에 없는 세부. 2026-10-23 제안, 사용자 확인 전)

1. **원장 ① 칸:** `cdc_op`(c·r·u), `source_ts_ms`(DB에서 바뀐 시각, `__source_ts_ms`)를 더한다. Silver 결과의 칸 이름과 같다. 이벤트마다 한 줄이고 덮어쓰지 않는다.
2. **변경 시각 검사:** 결제의 `__source_ts_ms`가 없거나 0 이상의 정수가 아니면 ④ `INVALID_VALUE` (Silver `_check_cdc`와 같음).
3. **최신 상태 (`payment_attempts`):** 같은 `payment_id` 중 `source_ts_ms`가 가장 큰 줄. 같으면 Kafka 위치(파티션, offset)가 뒤인 줄. 재처리 때 바뀌는 `loaded_at`은 쓰지 않는다.
4. **충돌 (`payment_conflicts`):** 같은 `payment_id`, 같은 `source_ts_ms`인데 지문이 다르면 충돌 (Silver 「동일 키·원천 시각에 서로 다른 내용」). 변경 시각이 다른 c→u는 정상 수정이다.
5. **보류:** 결제 메시지 중 형식 오류로 ①에 들어가지 못한 것이 있으면(④에 `record_key = payment_id`가 있고 같은 Kafka 위치에 ① 줄이 없음) 그 `payment_id`는 `payment_attempts`에서 뺀다. 규칙을 고쳐 재처리해서 그 메시지가 ①에 들어가면 보류가 풀린다. 키를 알 수 없는 오류(`PARSE_ERROR`)는 결제와 연결하지 않는다 (Silver도 키 없는 오류로는 키를 보류하지 못함).
6. **`record_key`:** 결제 `payment_id`, 주문 `order_id`, 주문상품 `order_item_id`, 클릭 `event_id` (Silver 키와 같음). 회원은 비운다 (회원 정보를 남기지 않음. Silver와 다른 점).
7. **`raw_sample`에서 풀 값:** `payment_id`, `order_id`, `order_item_id`, 시각 칸(`requested_at`, `completed_at`, `ordered_at`, `updated_at`, `event_time`, `__source_ts_ms`). 계속 가릴 값: 회원 ID·세션 ID, 회원 토픽의 모든 값, 상품 번호(`article_id`), 클릭 `event_id`.
8. **Glue 표:** 표 정의가 바뀌므로 머지 뒤 Glue의 `gold_b.payment_events`, `gold_b.malformed_events`에 칸을 더한다 (`ALTER TABLE … ADD COLUMNS`. 아직 데이터가 없으면 다시 만들어도 됨).

## 만드는 것

- `pipelines/gold_b/format_check.py`(결제 `u`, 변경 시각 검사, `record_key`, `raw_sample` 규칙), `pipelines/gold_b/ledger.py`(칸 추가)
- DDL `payment_events.sql`, `malformed_events.sql`, 뷰 `payment_attempts.sql`, `payment_conflicts.sql`와 설계 문서의 같은 SQL
- 샘플과 기대값(c→u, 잘못된 u, 같은 변경 시각 충돌, 시간 폴더가 바뀌는 u), 시험
- 설계 문서(①④ 표, 처리 규칙, 2단계 CDC 표시, `raw_sample` 규칙, 팀원 확인 표), README, `docs/BRANCHES.md` 한 줄
- 뷰는 로컬 Trino 484(이미 받아 둔 이미지)에 샘플 원장을 넣어 확인한다

## 만들지 않는 것

- Silver의 결제 `u` 처리 (현지 님)
- Glue 표 변경 실행 (머지 뒤, 권한 있는 사람)
- 판정 잡 변경 (주현 님. 뷰 이름과 칸은 그대로라 판정 SQL은 바꾸지 않아도 됨)

## 확인할 것 (팀 합의 항목)

- c → u를 받으면 원장에 두 이력이 남는가
- 뷰에는 수정된 최신 값만 보이는가
- 정상 UPDATE가 `payment_conflicts`로 잘못 분류되지 않는가
- 잘못된 UPDATE는 ④ 형식 오류로 남고, 그 결제는 보류되는가
- 같은 Kafka 이벤트를 재처리해도 중복 집계나 잘못된 최신 상태 선택이 없는가
- 수정으로 `completed_at`이 바뀌어도 옛 시간 폴더의 줄은 이력으로 남고 최신 값이 빠지지 않는가

## 작업 순서

1. 계획 제시와 작업 지시서·브랜치 대장 커밋 (2026-10-23)
2. 계획 확인 뒤 형식 검사기·원장 도구·DDL 커밋
3. 뷰 SQL과 설계 문서 커밋
4. 샘플·시험 커밋, 로컬 Trino로 뷰 확인
5. "완료 확인" 실행과 작업 결과 기록

## 완료 확인

- [ ] `python -m pytest -q pipelines/gold_b/tests` 통과
- [ ] 위 「확인할 것」 6가지 (시험 또는 로컬 Trino)
- [ ] 뷰 SQL 파일이 설계 문서와 같은지 (`test_views.py`)

## 작업 결과 (머지 전에 작성한다)
