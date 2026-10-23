# 작업 지시서: pipelines/gold-b-payment-update

> 상태: 진행 중 · 브랜치: `pipelines/gold-b-payment-update` (최신 `main` #92 위의 머지 정리 커밋 `8ca6a10`에서, `pipelines/gold-b-image`와 같은 출발점) · 다음 작업: 개발 계획 확인 (사용자), 현지 님께 Silver 제안 전달

## 목표

RDS에서 결제가 수정되면(`__op = u`) Gold B가 수정된 최신 상태를 반영한다. 원장 ① `payment_events`에는 변경 전후 이벤트를 모두 남기고, 정리 뷰 `payment_attempts`는 최신 상태를 보여준다. 최신 이벤트가 잘못됐거나 순서를 믿을 수 없는 결제는 보류한다. 원장은 바꾸지 않고 뷰가 읽을 때 판단하므로, 재처리나 새 이벤트가 들어오면 저절로 맞춰진다.

## 먼저 읽을 것

- 팀 합의 방향 (2026-10-23, 사용자 전달): 결제 `u` 처리, 원장에 변경 이력 보존, 최신 상태 뷰, 정상 수정은 충돌 아님, 재처리 검증 항목
- `pipelines/silver/transactions.py`, `pipelines/silver/common.py`: Silver의 CDC 규칙 (`_check_cdc`, `_version`, `collect_latest`, `integer`)
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
- ④ `malformed_events`: `record_key`, `source_ts_ms`를 더한다. 오류 이벤트도 순서 이상을 확인할 수 있게 `__source_ts_ms`를 남긴다 (값이 없거나 0 이상의 정수가 아니면 NULL).
- `record_key`: 결제 `payment_id`, 주문 `order_id`, 주문상품 `order_item_id`, 클릭 `event_id` (Silver 키와 같음). 회원은 비운다 (회원 정보를 남기지 않음, Silver와 다른 점).
- 결제 이벤트로 보는 것: ① 줄과, `record_key`가 있는 `payments` 토픽의 ④ 줄. 메시지를 읽지 못해 키를 모르는 오류(`PARSE_ERROR`)는 결제와 연결하지 못한다 (한계, Silver도 키 없는 오류로는 키를 보류하지 못함).

### 그 밖의 기본값

- 결제의 `__source_ts_ms` 검사: 없으면 `MISSING_FIELD`, 정수가 아니면 `TYPE_MISMATCH`, 0보다 작으면 `INVALID_VALUE` (Silver 거래 검사 `integer(…, 0)`와 같은 코드).
- `raw_sample`에서 풀 값: `payment_id`, `order_id`, `order_item_id`, 시각 칸(`requested_at`, `completed_at`, `ordered_at`, `updated_at`, `event_time`, `__source_ts_ms`). 계속 가릴 값: 회원 ID·세션 ID, 회원 토픽의 모든 값, 상품 번호(`article_id`), 클릭 `event_id`.
- Glue: 표 정의가 바뀌므로 머지 뒤 Glue의 `gold_b.payment_events`, `gold_b.malformed_events`에 칸을 더한다.

## 개발 계획

단계마다 작은 커밋으로 나눈다. 1·2단계가 원장 줄을 바꾸고, 3·4단계가 그 줄을 읽는 뷰를 만든다.

| 단계 | 바꾸는 파일 | 내용 | 확인 |
|---|---|---|---|
| 1. 원장 칸 | `ledger.py`(`TABLE_COLUMNS`, `PAYMENT_FIELDS`, `ERROR_FIELDS`, `message_rows`), `ddl/payment_events.sql`, `ddl/malformed_events.sql`, 설계 문서 ①④ 표 | ①에 `cdc_op`·`source_ts_ms`·`rule_version`, ④에 `record_key`·`source_ts_ms`. 칸은 맨 뒤에 붙인다 | `test_ddl.py`: DDL·원장 스키마·설계 표가 같은지 |
| 2. 형식 검사기 | `format_check.py`, 샘플 기대값 | `PAYMENT_OPS`에 `u`, 결제 `__source_ts_ms` 검사, 결제 줄에 `cdc_op`·`source_ts_ms`, 오류 줄에 `record_key`·`source_ts_ms`, `raw_sample` 풀 값 | `test_format_check.py`: 정상 `u`, 잘못된 `u`, `__source_ts_ms` 오류 세 가지, `record_key`, `raw_sample` |
| 3. 정리 뷰 | 새 기반 뷰 `views/payment_states.sql`, `payment_attempts.sql`, `payment_conflicts.sql`, 설계 문서의 같은 SQL, `views/README.md` | `payment_states`: 결제마다 마지막 이벤트와 보류 사유(1·2단계 규칙). `payment_attempts`: 보류 없는 결제의 마지막 이벤트 (칸은 지금과 같음). `payment_conflicts`: 보류된 결제와 `hold_reason` | `test_views.py`: SQL 파일이 설계 문서와 같은지 |
| 4. 시나리오 확인 | 샘플 메시지와 뷰 기대 결과, 로컬 Trino 484 | 정상 c→u, 같은 `source_ts_ms`의 c→u, 잘못된 최신 u, 그 뒤 새 정상 u, 재처리 복구(같은 위치에 옛 오류+새 통과), 순서 이상, 두 파티션, `completed_at` 시간 폴더가 바뀌는 u | 로컬 Trino에 DDL·뷰를 만들고 샘플 원장을 넣어 기대 결과와 비교 (이미 받아 둔 이미지) |
| 5. 재처리 | `test_reprocess.py` | 규칙 버전이 바뀐 재처리에서 옛 오류와 새 통과가 같은 위치에 남는지, 같은 버전 재처리는 옛 오류를 지우는지, ①·④가 다른 시간 폴더인 메시지에서 한쪽만 재처리될 때, 같은 이벤트를 두 번 재처리해도 원장이 같은지 | `pytest` |
| 6. 문서 | 설계 문서(처리 규칙, 2단계 CDC 표시, `raw_sample` 규칙, 팀원 확인 표), README, 샘플 README, 이 지시서 | 두 단계 규칙, Glue `ALTER TABLE` 문, 뷰 만드는 순서 | `git diff --check`, 전체 시험 |

### 근거

- **결제 `u`를 받는 이유:** RDS에서 결제를 고쳐도 Gold B가 처음 값만 보면 탐지가 틀린 값으로 판정한다. 원장에는 이벤트마다 한 줄씩 남겨 이력을 지키고, 뷰가 최신 상태를 보여준다 (팀 합의).
- **순서를 offset으로 정하는 이유:**
  - `payments` 메시지 키는 `payment_id`다(`connectors/README.md`). Kafka producer는 키 해시로 파티션을 정해서 같은 결제는 늘 같은 파티션에 들어간다. 우리 Connect 설정에는 파티션을 따로 고르는 설정이 없다.
  - 한 파티션 안의 offset은 쓴 순서이고, Debezium은 DB 변경 기록 순서대로 보낸다. 그래서 같은 결제 안에서 offset 순서가 DB에서 실제로 바뀐 순서다.
  - `__source_ts_ms`는 밀리초 단위 커밋 시각이라, 같은 밀리초나 한 트랜잭션 안의 여러 변경이 같은 값을 가질 수 있다. 시각 기준이면 정상 수정도 충돌로 보류하게 된다.
  - 재처리해도 offset은 바뀌지 않는다. `loaded_at`은 재처리 때 바뀐다.
  - Debezium이 재시작 뒤 같은 변경을 다시 보내도 재시작 지점부터 순서대로 보내서 마지막 offset이 여전히 최신이다.
  - 팀 계약서의 「같은 변경 시각 충돌: CDC 변경 순서와 원본 위치를 확인한 뒤 해결 기준 결정」(미정)을 이 규칙으로 정할 수 있다.
- **두 단계로 나누는 이유:** Gold B 원장은 검사 결과가 쌓이는 구조다. 재처리는 시간 폴더 단위로 바꾸고 ④의 다른 규칙 버전 줄은 남기며, ①과 ④의 시간 폴더 기준이 다르다. 그래서 같은 메시지에 통과와 오류가 함께 있을 수 있어, 이벤트 순서를 보기 전에 메시지마다 가장 늦은 검사 결과를 먼저 정해야 한다.
- **마지막 이벤트가 잘못됐을 때만 보류하는 이유:** 현재 상태는 마지막 변경이 정한다. 앞선 오류가 뒤의 정상 이벤트로 덮였으면 현재 상태에는 영향이 없다. 보류는 뷰에서만 해서 재처리나 새 이벤트가 오면 저절로 풀린다.
- **`ORDER_ANOMALY`, `MULTI_PARTITION`을 두는 이유:** offset 순서를 믿을 전제(한 파티션, DB 시각과 맞는 순서)가 깨지면 추측하지 않고 보류해서 드러낸다. 같은 시각은 한 트랜잭션에서 정상적으로 생기므로 이상으로 보지 않는다.
- **④에 `record_key`와 `source_ts_ms`를 남기는 이유:** `raw_sample`은 메시지의 첫 오류 줄에만 있고 잘려 있어 결제와 연결하기 어렵다. 오류 줄마다 키와 변경 시각이 있어야 잘못된 최신 이벤트와 순서 이상을 판단할 수 있다.
- **①에 `rule_version`을 남기는 이유:** 같은 메시지를 여러 규칙 버전으로 검사한 이력을 ①과 ④ 양쪽에서 추적할 수 있다.
- **원장은 그대로 두고 뷰에서 판단하는 이유:** 원장을 고치면 이력이 사라지고 재처리 순서에 따라 결과가 달라진다. 뷰는 읽을 때마다 같은 규칙으로 다시 계산한다.
- **기반 뷰 `payment_states`를 두는 이유:** `payment_attempts`와 보류 목록이 같은 판단을 따로 계산하면 서로 어긋날 수 있다. 한 뷰에서 판단하고 두 뷰가 나눠 읽는다 (지금도 `payment_attempts`가 `payment_conflicts`를 읽는다).
- **뷰 이름 `payment_conflicts`를 유지하는 이유 (제안):** 이 뷰를 읽는 코드가 아직 없고 Glue 권한은 `gold_b` 표 전체에 걸려 있다. 설계 문서에서 이 이름을 쓰는 자리가 많아 바꿀 곳이 가장 적다. 뜻은 "내용이 다른 결제"에서 "보류된 결제와 사유"로 바뀐다 (Silver의 격리 기록과 같은 역할).

### 남은 결정 (사용자 확인)

- 보류 목록 뷰 이름: `payment_conflicts` 유지 + `hold_reason` 칸 (제안) 또는 새 이름
- 새 기반 뷰 `payment_states` 추가 (설계에 없던 뷰라 확인 필요)

### 영향과 머지 뒤 할 일

- 판정 잡(주현 님): `payment_attempts` 칸은 그대로라 SQL을 바꾸지 않아도 된다. 뜻은 "처음 쌓인 줄"에서 "보류되지 않은 결제의 마지막 변경"으로 바뀌어 R1·R5가 수정된 값으로 판정한다.
- 대시보드(민혁 님): `payment_conflicts`를 쓸 계획이면 새 칸(`hold_reason`)을 알린다.
- Glue: `ALTER TABLE gold_b.payment_events ADD COLUMNS (cdc_op string, source_ts_ms bigint, rule_version string)`, `ALTER TABLE gold_b.malformed_events ADD COLUMNS (record_key string, source_ts_ms bigint)`. 아직 데이터가 없으면 표를 다시 만들어도 된다.
- Athena 뷰는 `payment_states` → `payment_conflicts` → `payment_attempts` 순서로 만든다.
- 운영 이미지는 이 변경이 머지된 main으로 빌드한다 (데이터가 쌓이기 전에 칸을 맞춤).

## Silver와 맞출 것 (현지 님께 보낼 제안)

같은 결제의 현재 상태가 Silver와 Gold B에서 같게 나오도록 아래를 현지 님께 제안한다. Silver는 매번 Bronze를 다시 읽어 계산하므로 1단계(검사 이력)는 필요 없고, 2단계 규칙만 맞추면 된다.

1. 결제도 `__op`의 `r`·`c`·`u`를 받는다 (지금 Silver는 결제 `u`를 `UNSUPPORTED_CDC`로 격리).
2. 같은 `payment_id`의 순서는 Bronze v2의 `kafka_partition`·`kafka_offset`으로 정하고, 같은 파티션에서 offset이 가장 큰 이벤트를 현재 상태로 쓴다. 두 파티션 이상이면 보류한다.
3. `__source_ts_ms`는 보조 기준이다. 마지막 이벤트의 값이 앞선 이벤트들의 최댓값보다 작으면 보류하고, 같은 값은 정상으로 본다 (지금의 "같은 원천 시각·다른 내용 → `CONTENT_CONFLICT`"는 offset이 있으면 필요 없다).
4. 오류 보류는 마지막 이벤트가 오류일 때만 한다 (지금 Silver는 같은 키에 오류가 하나라도 있으면 `DEPENDENCY_BLOCKED`).
5. Kafka 위치가 없는 옛 Bronze 줄(`bronze/`)은 지금 규칙(`__source_ts_ms` 순, 같은 시각·다른 내용이면 보류)을 유지한다.
6. 팀 계약서(`docs/contracts/README.md`)의 「같은 변경 시각 충돌」 미정 칸을 이 규칙으로 함께 고친다 (어느 PR에서 할지 정함).

## 만들지 않는 것

- Silver의 결제 `u` 처리와 같은 순서 규칙 적용 (현지 님)
- Glue 표 변경과 Athena 뷰 생성 실행 (머지 뒤, 권한 있는 사람)
- 판정 잡 변경 (주현 님)

## 확인할 것

- 정상 c → u: 원장에 두 이력이 남고, 뷰에는 수정된 최신 값만 보인다
- 정상 UPDATE가 보류로 분류되지 않는다 (같은 `source_ts_ms`도 정상)
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
3. 개발 계획과 근거, Silver 제안 작성 (2026-10-23)
4. 계획 확인 뒤 「개발 계획」 1~6단계
5. "완료 확인" 실행과 작업 결과 기록

## 완료 확인

- [ ] `python -m pytest -q pipelines/gold_b/tests` 통과
- [ ] 위 「확인할 것」 (시험 또는 로컬 Trino)
- [ ] 뷰 SQL 파일이 설계 문서와 같은지 (`test_views.py`)

## 작업 결과 (머지 전에 작성한다)
