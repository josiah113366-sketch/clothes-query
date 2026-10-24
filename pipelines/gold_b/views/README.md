# pipelines/gold_b/views

탐지·에이전트가 읽는 **정리 뷰** SQL이다. 뷰는 데이터를 따로 저장하지 않고, 조회할 때마다 원장을 정리해서 보여 준다. 각 뷰의 설계와 컬럼 설명은 [docs/design/gold-b/README.md](../../../docs/design/gold-b/README.md) 「탐지가 읽는 것」에 있다.

| 파일 | 한 줄 = | 읽는 것 |
|---|---|---|
| `payment_states.sql` | 결제 하나. 마지막 이벤트와 보류 사유(`hold_reason`). Kafka 위치마다 가장 늦은 검사 결과를 고른 뒤 같은 결제를 offset 순으로 본다 (2026-10-23) | `payment_events`, `malformed_events` |
| `payment_conflicts.sql` | 보류된 결제 하나와 사유 (`MULTI_PARTITION`, `ORDER_ANOMALY`, `INVALID_LATEST`). 이름은 그대로, 뜻은 2026-10-23에 바뀜 | `payment_states` |
| `payment_attempts.sql` | 결제 시도 한 건. 보류되지 않은 결제의 마지막 이벤트(수정되었으면 수정된 값), 실패 원인 분류(`PG`/`CUSTOMER`/`UNKNOWN`). 칸은 예전과 같음 | `payment_states` |
| `malformed_messages.sql` | 깨진 메시지 하나 (규칙 버전별). 오류 개수, 필드·사유 쌍 전부, 시간 폴더(`dt`, `hour`) | `malformed_events` |

**설계 문서가 원본이다.** 뷰를 고칠 때는 설계 문서의 SQL과 이 파일을 같이 고친다. `tests/test_views.py`가 둘이 같은지 확인한다.

## 조회할 때

- `malformed_messages`는 시간 폴더 조건(`dt`, `hour`)을 같이 주면 그 폴더의 ④ `malformed_events`만 읽는다. 조건이 없으면 조회할 때마다 ④ 전체를 읽는다. 구간이 두 시간에 걸치면 두 폴더를 모두 준다 (예시는 설계 문서 `malformed_messages` 절).
- `payment_states`(와 이것을 읽는 `payment_attempts`·`payment_conflicts`)는 예전에 쌓인 같은 결제의 이벤트와도 순서를 비교하므로 언제나 `payment_events` 전체와 `malformed_events`의 결제 오류를 읽는다.

## 만드는 순서 (Athena)

1. `ddl/database.sql`, 원장 테이블 (`ddl/*.sql`). 이미 만든 표에는 칸을 더한다 (아래 「표 정의가 바뀐 것」)
2. `payment_states.sql`
3. `payment_conflicts.sql`, `payment_attempts.sql` (둘 다 `payment_states`를 읽어서 그 뒤에 만든다)
4. `malformed_messages.sql`

### 표 정의가 바뀐 것 (2026-10-23, 결제 UPDATE 처리)

Glue에 원장 표를 이미 만들었으면 칸을 더한다. 칸은 맨 뒤에 붙였다. 아직 데이터가 없으면 표를 지우고 `ddl/`로 다시 만들어도 된다.

```sql
ALTER TABLE gold_b.payment_events ADD COLUMNS (cdc_op string, source_ts_ms bigint, rule_version string)
ALTER TABLE gold_b.malformed_events ADD COLUMNS (record_key string, source_ts_ms bigint)
```

같은 이름으로 다시 실행하면 뷰가 바뀐다 (`CREATE OR REPLACE VIEW`). 탐지·에이전트 쿼리는 그대로 돌고, 시간 폴더 조건을 더하면 덜 읽는다.

## 처음 만들 때 확인할 것 (Athena 권한이 생긴 뒤)

로컬 Trino 484(Docker, Athena 엔진 3과 같은 계열)에서는 아래를 모두 확인했다 (2026-10-22, `docs/tasks/gold-b-views.md`). Athena에서 한 번 더 본다.

- 문법: 창 함수의 `ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING`, `UNION ALL`의 NULL 칸(`payment_states`), `ARRAY_AGG(CAST(ROW(...) AS ROW(...)))`(`malformed_messages`)가 Athena에서 도는지
- 샘플(`tests/samples/`)로 만든 원장에서:
  - 결제마다 `payment_states`의 마지막 이벤트와 `hold_reason`이 `tests/samples/payment_states.json`과 같은지 (2026-10-23, 로컬 Trino 484로 확인. `docs/tasks/gold-b-payment-update.md`)
  - 오류 3개짜리 메시지(`multiple_errors`)가 `malformed_messages`에 1줄, `error_count` 3
- `malformed_messages`를 `dt`·`hour` 조건으로 조회하면 그 폴더만 읽는지 (Athena 실행 결과의 읽은 데이터 크기)

## 의존하는 것

- Glue 데이터베이스 `gold_b`와 원장 테이블 (`ddl/`)
- Athena 실행 권한 (재영 님과 정함)
