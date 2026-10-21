# pipelines/gold_b/views

탐지·에이전트가 읽는 **정리 뷰** SQL이다. 뷰는 데이터를 따로 저장하지 않고, 조회할 때마다 원장을 정리해서 보여 준다. 각 뷰의 설계와 컬럼 설명은 [docs/design/gold-b/README.md](../../../docs/design/gold-b/README.md) 「탐지가 읽는 것」에 있다.

| 파일 | 한 줄 = | 읽는 것 |
|---|---|---|
| `payment_conflicts.sql` | 내용이 충돌한 결제 하나. 같은 `payment_id`인데 지문이 다름 (같은 지문 버전끼리만 비교, 예전에 쌓인 줄과도 비교) | `payment_events` |
| `payment_attempts.sql` | 결제 시도 한 건. 충돌 결제는 모든 줄을 빼고, 같은 결제는 가장 먼저 쌓인 줄 하나, 실패 원인 분류(`PG`/`CUSTOMER`/`UNKNOWN`) | `payment_events`, `payment_conflicts` |
| `malformed_messages.sql` | 깨진 메시지 하나 (규칙 버전별). 오류 개수와 필드·사유 쌍 전부 | `malformed_events` |

**설계 문서가 원본이다.** 뷰를 고칠 때는 설계 문서의 SQL과 이 파일을 같이 고친다. `tests/test_views.py`가 둘이 같은지 확인한다.

## 만드는 순서 (Athena)

1. `ddl/database.sql`, 원장 테이블 (`ddl/*.sql`)
2. `payment_conflicts.sql`
3. `payment_attempts.sql` (`payment_conflicts`를 읽어서 그 뒤에 만든다)
4. `malformed_messages.sql`

같은 이름으로 다시 실행하면 뷰가 바뀐다 (`CREATE OR REPLACE VIEW`). 탐지·에이전트 쪽은 고칠 것이 없다.

## 처음 만들 때 확인할 것 (Athena 권한이 생긴 뒤)

로컬 Trino 484(Docker, Athena 엔진 3과 같은 계열)에서는 아래를 모두 확인했다 (2026-10-22, `docs/tasks/gold-b-views.md`). Athena에서 한 번 더 본다.

- 문법: `ARRAY_AGG(CAST(ROW(...) AS ROW(...)))`, `filter(ARRAY[...], x -> ...)`가 Athena에서 도는지
- 샘플(`tests/samples/`)로 만든 원장에서:
  - 같은 결제 중복(`success_pg_a`, `duplicate_of_success_pg_a`)이 `payment_attempts`에 1건
  - 충돌 두 쌍이 `payment_attempts`에서 빠지고 `payment_conflicts`에 1줄씩. 금액만 다른 쌍은 `conflict_fields`가 `[payment_content_hash]`
  - 오류 3개짜리 메시지(`multiple_errors`)가 `malformed_messages`에 1줄, `error_count` 3

## 의존하는 것

- Glue 데이터베이스 `gold_b`와 원장 테이블 (`ddl/`)
- Athena 실행 권한 (재영 님과 정함)
