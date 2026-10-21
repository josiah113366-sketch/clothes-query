# 작업 지시서: pipelines/gold-b-views

> 상태: 진행 중 · 브랜치: `pipelines/gold-b-views` (`pipelines/gold-b` 위에서 갈라짐) · 다음 작업: Athena 권한이 생기면 뷰 생성과 샘플 확인

## 목표

설계 문서에 있는 정리 뷰 3개(`payment_conflicts`, `payment_attempts`, `malformed_messages`)의 SQL을 `pipelines/gold_b/views/`에 파일로 남긴다 (3단계). Athena에서 만들고 샘플로 확인하는 것은 권한이 생긴 뒤에 한다.

## 먼저 읽을 것

- `docs/design/gold-b/README.md` 「탐지가 읽는 것」(뷰 SQL과 컬럼), 「처리 규칙」(중복 제거, 실패 원인 분류), 3단계 체크리스트
- `pipelines/gold_b/ddl/payment_events.sql`, `malformed_events.sql`

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- #36이 머지 전이라 `pipelines/gold-b` 위에서 갈라졌다. push는 #36 머지 뒤 이 브랜치의 커밋만 `main` 위로 옮긴 다음에 한다.
- 커밋 메시지에 Claude 공동 작성자 줄을 넣지 않는다.

## 만드는 것

- `pipelines/gold_b/views/payment_conflicts.sql`, `payment_attempts.sql`, `malformed_messages.sql`: 설계 문서의 SQL을 그대로 옮김 (맨 위에 설명 주석 두 줄)
- `pipelines/gold_b/views/README.md`: 뷰 설명, Athena에서 만드는 순서, 처음 만들 때 확인할 것
- `pipelines/gold_b/tests/test_views.py`: 파일과 설계 문서의 SQL이 같은지
- `pipelines/gold_b/README.md`, 설계 문서 3단계 체크, `docs/BRANCHES.md` 한 줄

## 만들지 않는 것

- Athena에서 뷰 생성, 샘플 결과 확인 (Athena 권한, 재영 님)
- 탐지가 묶어 세는 SQL (탐지 규칙에서 정함)

## 완료 확인

- [x] `python -m pytest -q pipelines/gold_b/tests` 통과 (Gold B 가상환경, 26개)
- [x] 뷰 파일 3개가 설계 문서의 SQL과 같은지
- [x] 로컬 Trino 484(Docker)에서 뷰 생성과 샘플 결과 확인
- [ ] Athena에서 뷰 생성 → **대기** (권한)

## 작업 결과 (머지 전에 작성한다)

- **한 줄 요약:** 설계 문서의 정리 뷰 SQL 3개를 `pipelines/gold_b/views/`에 파일로 옮기고, 둘이 어긋나지 않는지 확인하는 시험을 더했다. Athena에서 만드는 것은 아직이다.
- **무엇을 만들었나:** `views/payment_conflicts.sql`, `payment_attempts.sql`, `malformed_messages.sql`, `views/README.md`(뷰 설명, 만드는 순서, 처음 만들 때 확인할 것), `tests/test_views.py`, `pipelines/gold_b/README.md`, 설계 문서 3단계 체크, `docs/BRANCHES.md` 한 줄
- **왜 그렇게 했나:** 설계 문서를 원본으로 두고 파일은 복사본으로 했다. 설계 문서의 SQL을 고치고 파일을 안 고치면(또는 반대) 시험이 실패한다. `payment_attempts`가 `payment_conflicts`를 읽어서 만드는 순서를 README에 적었다.
- **확인한 결과:**
  - Gold B 가상환경에서 `pipelines/gold_b/tests` 26개 통과 (테이블 정의 22 + 뷰 4). `git diff --check` 통과.
  - **로컬 Trino 확인 (2026-10-22, Docker `trinodb/trino:484`):** Athena 엔진 3은 Trino 기반이라 같은 문법으로 확인했다. 메모리 카탈로그에 원장 2개(DDL과 같은 컬럼, `TIMESTAMP`는 밀리초)를 만들고 샘플 31건의 기대 결과로 줄을 넣었다 (결제 10줄, 오류 17줄, `loaded_at`은 Kafka 시각 30초 뒤). 뷰 파일 3개를 순서대로 실행했고 오류 없이 만들어졌다 (`filter(ARRAY[...])`, `ARRAY_AGG(CAST(ROW(...)))`, SQL 안의 `--` 주석 포함).
    - `payment_conflicts`: 충돌 두 쌍이 1줄씩, `row_count` 2. `conflict_fields`는 상태가 다른 쌍이 `[status, failure_code]`, 금액만 다른 쌍이 `[payment_content_hash]`. `sources`에 원본 위치 두 개.
    - `payment_attempts`: 남는 결제와 실패 원인(`PG`/`CUSTOMER`/`UNKNOWN`)이 샘플 기대값과 같음. 같은 결제 중복은 먼저 쌓인 줄(06:01:32) 하나.
    - `malformed_messages`: 깨진 메시지마다 1줄, 오류 3개짜리는 `error_count` 3.
- **알려진 한계·남은 일:**
  - Athena에서 직접 만들어 보는 것은 권한이 생긴 뒤에 한다. Trino에서는 통과했지만 Athena는 뷰를 Glue에 저장하므로 한 번은 실제로 확인한다 (`views/README.md`의 확인 목록).
  - `payment_conflicts` SQL 안에 `--` 주석이 한 줄 있다. Trino에서는 문제없었고, Athena에서 문제가 되면 설계 문서와 파일에서 같이 뺀다.
  - push는 #36 머지 뒤 이 브랜치의 커밋만 `main` 위로 옮긴 다음에 한다.
