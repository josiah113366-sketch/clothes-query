# 작업 지시서: pipelines/gold-b-payment-update

> 상태: 진행 중 · 브랜치: `pipelines/gold-b-payment-update` (최신 `main` #92 위의 머지 정리 커밋 `8ca6a10`에서, `pipelines/gold-b-image`와 같은 출발점) · 다음 작업: 보류 사유를 보여줄 뷰 결정 (사용자), 그 뒤 구현

## 목표

RDS에서 결제가 수정되면(`__op = u`) Gold B가 수정된 최신 상태를 반영한다. 원장 ① `payment_events`에는 변경 전후 이벤트를 모두 남기고, 정리 뷰 `payment_attempts`는 최신 상태를 보여준다. 최신 이벤트가 잘못됐거나 순서를 믿을 수 없는 결제는 보류한다. 원장은 바꾸지 않고 뷰가 읽을 때 판단하므로, 재처리나 새 이벤트가 들어오면 저절로 맞춰진다.

## 먼저 읽을 것

- 팀 합의 방향 (2026-10-23, 사용자 전달): 결제 `u` 처리, 원장에 변경 이력 보존, 최신 상태 뷰, 정상 수정은 충돌 아님, 재처리 검증 항목
- `pipelines/silver/transactions.py`, `pipelines/silver/common.py`: Silver의 CDC 규칙 (`_check_cdc`, `_version`, `collect_latest`)
- `connectors/README.md` 토픽 키 표 (`payments` 키 = `payment_id`, 파티션 3), `connectors/bronze-s3-sink-v2.yaml`
- `docs/contracts/README.md` 「같은 변경 시각 충돌」(미정), 「Bronze → Silver 원본 추적 입력 초안」
- `pipelines/gold_b/jobs/reprocess.py` `_rebuilt`: 재처리는 바꾸는 시간 폴더 안에서 다시 읽은 위치의 줄만 바꾸고, ④는 다른 규칙 버전의 줄을 남긴다

## 사용자 결정 (2026-10-23)

1. 결제 `u`도 처리한다 (팀 합의).
2. ④ `malformed_events`에 `record_key`를 더해 오류 이벤트를 결제와 연결한다.
3. `raw_sample`은 결제·주문 ID와 시각만 풀고, 회원 정보는 계속 가린다.
4. 같은 결제 이벤트의 순서는 Kafka offset으로 정한다. `payments` 키가 `payment_id`라 같은 결제는 같은 파티션에 들어간다. `source_ts_ms`는 보조 기준이다.
5. 판단은 두 단계로 나눈다. 1단계는 같은 Kafka 위치의 검사 결과 확정(검사 이력), 2단계는 같은 결제의 이벤트 순서(`kafka_offset`)다.

## 확정 규칙

### 1단계: Kafka 위치마다 검사 결과 확정

- offset은 파티션마다 0부터 따로 늘어나서, 다른 파티션에 같은 offset이 있다. 그래서 메시지는 offset만이 아니라 항상 (토픽, 파티션, offset)으로 구분한다. ①은 `payments` 토픽만 담고, ④는 `topic`으로 거른다.
- 한 Kafka 위치(파티션, offset)의 검사 결과는 ① 줄(통과) 또는 ④ 줄(오류)로 남는다. 재처리에서 규칙 버전이 바뀌면 옛 오류 줄이 이력으로 남는다. 또 ①은 `completed_at`, ④는 Kafka 시각으로 시간 폴더를 나눠서, 재처리가 한쪽 폴더만 다시 쓸 수 있다. 그래서 한 위치에 통과와 오류가 함께 있을 수 있다.
- 위치마다 가장 늦게 쌓인 검사 결과(`loaded_at`이 가장 큰 것)를 채택한다. 재처리에 성공하면 과거 오류는 해소되고, 실패하면 오류가 유지된다.
- `loaded_at`은 이 단계(같은 메시지를 여러 번 검사한 결과의 순서)에만 쓴다. 서로 다른 결제 이벤트의 순서에는 쓰지 않는다.
- 한 번의 검사는 ①이나 ④ 중 하나만 만든다. 서로 다른 검사의 `loaded_at`이 같으면 오류를 채택한다 (보수적).
- 검사 결과를 추적할 수 있게 ①에도 `rule_version`을 남긴다 (④에는 이미 있음).

### 2단계: 같은 결제의 이벤트 순서

1. 같은 `payment_id`의 이벤트(1단계 결과)가 두 파티션 이상에 있으면 순서를 정하지 않고 보류한다 (`MULTI_PARTITION`). 토픽 파티션 수를 바꾸면 생길 수 있다.
2. 같은 파티션이면 `kafka_offset` 순으로 놓는다. 마지막 이벤트는 offset이 가장 큰 것이다. 다른 파티션의 offset끼리는 비교하지 않는다 (1번에서 이미 보류됨).
3. 마지막 이벤트의 `source_ts_ms`가 앞선 이벤트들의 최댓값보다 작으면 보류한다 (`ORDER_ANOMALY`). 값이 같은 것은 정상이며, 시각이 같다는 이유만으로 충돌로 보지 않는다.
4. 마지막 이벤트가 오류면 보류한다 (`INVALID_LATEST`).
5. 마지막 이벤트가 정상이면 그 값을 `payment_attempts`에 보여준다. 앞선 이벤트의 오류는 상관없다.
6. 보류는 원장을 바꾸지 않고 뷰가 읽을 때만 뺀다. 재처리로 통과하거나 뒤에 새 정상 이벤트가 오면 저절로 다시 보인다.

이렇게 하면 정상 c → u, 잘못된 최신 UPDATE, 재처리 뒤 복구, 그 뒤 새 정상 이벤트 도착을 서로 모순 없이 처리한다.

### 원장 칸

- ① `payment_events`: `cdc_op`(c·r·u), `source_ts_ms`(`__source_ts_ms`), `rule_version`을 더한다. 이벤트마다 한 줄이고 덮어쓰지 않는다.
- ④ `malformed_events`: `record_key`, `source_ts_ms`를 더한다. 오류 이벤트도 순서 이상을 확인할 수 있게 `__source_ts_ms`를 남긴다 (없거나 0 이상의 정수가 아니면 NULL).
- `record_key`: 결제 `payment_id`, 주문 `order_id`, 주문상품 `order_item_id`, 클릭 `event_id` (Silver 키와 같음). 회원은 비운다 (회원 정보를 남기지 않음, Silver와 다른 점).
- 결제 이벤트로 보는 것: ① 줄과, `record_key`가 있는 `payments` 토픽의 ④ 줄. 메시지를 읽지 못해 키를 모르는 오류(`PARSE_ERROR`)는 결제와 연결하지 못한다 (한계, Silver도 키 없는 오류로는 키를 보류하지 못함).

### 그 밖의 기본값

- 결제의 `__source_ts_ms`가 없거나 0 이상의 정수가 아니면 ④ `INVALID_VALUE` (Silver `_check_cdc`와 같음).
- `raw_sample`에서 풀 값: `payment_id`, `order_id`, `order_item_id`, 시각 칸(`requested_at`, `completed_at`, `ordered_at`, `updated_at`, `event_time`, `__source_ts_ms`). 계속 가릴 값: 회원 ID·세션 ID, 회원 토픽의 모든 값, 상품 번호(`article_id`), 클릭 `event_id`.
- Glue: 표 정의가 바뀌므로 머지 뒤 Glue의 `gold_b.payment_events`, `gold_b.malformed_events`에 칸을 더한다 (`ALTER TABLE … ADD COLUMNS`. 아직 데이터가 없으면 다시 만들어도 됨).

### 남은 결정 (사용자 확인 필요)

- **보류 사유를 보여줄 뷰:** 지금 `payment_conflicts`는 "같은 결제 ID에 내용(지문)이 다름"을 충돌로 보여준다. 새 규칙에서는 내용이 다른 것이 정상 수정이라 이 뜻을 그대로 쓸 수 없다. 제안: 이름은 그대로 두고 "보류된 결제와 사유(`hold_reason`: `MULTI_PARTITION`, `ORDER_ANOMALY`, `INVALID_LATEST`)"를 보여주게 바꾼다. 지금 이 뷰를 읽는 코드는 없고, Glue 권한은 `gold_b` 표 전체에 걸려 있다.

## 만드는 것

- `pipelines/gold_b/format_check.py`(결제 `u`, 변경 시각 검사, `record_key`·`source_ts_ms`, `raw_sample` 규칙), `pipelines/gold_b/ledger.py`(칸 추가)
- DDL `payment_events.sql`, `malformed_events.sql`, 뷰 `payment_attempts.sql`, `payment_conflicts.sql`와 설계 문서의 같은 SQL
- 샘플과 기대값, 시험
- 설계 문서(①④ 표, 처리 규칙, 2단계 CDC 표시, `raw_sample` 규칙, 팀원 확인 표), README, `docs/BRANCHES.md` 한 줄
- 뷰는 로컬 Trino 484(이미 받아 둔 이미지)에 샘플 원장을 넣어 확인한다

## 만들지 않는 것

- Silver의 결제 `u` 처리와 같은 순서 규칙 적용 (현지 님. Bronze v2에 `kafka_offset`이 들어가 같은 규칙을 쓸 수 있음)
- Glue 표 변경 실행 (머지 뒤, 권한 있는 사람)
- 판정 잡 변경 (주현 님. 뷰 이름과 `payment_attempts` 칸은 그대로라 판정 SQL은 바꾸지 않아도 됨)

## 확인할 것

- 정상 c → u: 원장에 두 이력이 남고, 뷰에는 수정된 최신 값만 보인다
- 정상 UPDATE가 보류나 충돌로 분류되지 않는다 (같은 `source_ts_ms`도 정상)
- 잘못된 최신 UPDATE: ④에 오류로 남고(`record_key`, `source_ts_ms` 포함) 그 결제는 보류된다 (`INVALID_LATEST`)
- 재처리 뒤 복구: 같은 위치에 옛 오류와 새 통과가 함께 있으면 통과를 채택해 다시 보인다. 재처리가 실패하면 보류가 유지된다
- 그 뒤 새 정상 이벤트가 오면 재처리 없이 다시 보인다
- 순서 이상: 마지막 이벤트의 `source_ts_ms`가 앞선 최댓값보다 작으면 보류된다 (`ORDER_ANOMALY`)
- 같은 결제가 두 파티션에 있으면 보류된다 (`MULTI_PARTITION`)
- 같은 Kafka 이벤트를 재처리해도 중복 집계나 잘못된 최신 상태 선택이 없다
- 수정으로 `completed_at`이 바뀌어도 옛 시간 폴더의 줄은 이력으로 남고 최신 값이 빠지지 않는다

## 작업 순서

1. 계획 제시와 작업 지시서·브랜치 대장 커밋 (2026-10-23)
2. 확정 규칙 반영 (2026-10-23, 사용자 확정)
3. 남은 결정 뒤 형식 검사기·원장 도구·DDL 커밋
4. 뷰 SQL과 설계 문서 커밋
5. 샘플·시험 커밋, 로컬 Trino로 뷰 확인
6. "완료 확인" 실행과 작업 결과 기록

## 완료 확인

- [ ] `python -m pytest -q pipelines/gold_b/tests` 통과
- [ ] 위 「확인할 것」 (시험 또는 로컬 Trino)
- [ ] 뷰 SQL 파일이 설계 문서와 같은지 (`test_views.py`)

## 작업 결과 (머지 전에 작성한다)
