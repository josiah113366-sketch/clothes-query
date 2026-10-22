# 작업 지시서: pipelines/gold-b-views

> 상태: 완료 · 브랜치: `pipelines/gold-b-views` (최신 `main` `783fa84` 병합) · main 대상 PR 제출 · 남은 일: Athena 권한이 생기면 뷰 생성과 샘플 확인

## 목표

설계 문서에 있는 정리 뷰 3개(`payment_conflicts`, `payment_attempts`, `malformed_messages`)의 SQL을 `pipelines/gold_b/views/`에 파일로 남긴다 (3단계). 판정·조사 쿼리가 조회할 때마다 원장 전체를 읽지 않도록 `malformed_messages`가 시간 폴더(`dt`, `hour`)를 내보내게 한다. Athena에서 만들고 샘플로 확인하는 것은 권한이 생긴 뒤에 한다.

## 먼저 읽을 것

- `docs/design/gold-b/README.md` 「탐지가 읽는 것」(뷰 SQL과 컬럼), 「처리 규칙」(중복 제거, 실패 원인 분류), 3단계 체크리스트
- `pipelines/gold_b/ddl/payment_events.sql`, `malformed_events.sql`
- 판정·조사 쪽 쿼리: `agent/detect/job.py`, `agent/tools/ledger_tools.py`

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- #36이 머지 전이라 `pipelines/gold-b` 위에서 갈라졌다. #36이 병합 커밋으로 들어가서(2026-10-22), 커밋을 옮기지 않고 최신 `main`을 이 브랜치에 병합했다. PR에는 이 브랜치의 커밋만 보인다.
- 커밋 메시지에 Claude 공동 작성자 줄을 넣지 않는다.
- 머지된 #36·#63의 정리(브랜치 대장 "머지됨", 작업 지시서 "상태: 완료", 설계 문서 진행 표시)를 이 PR에 같이 넣는다.

## 만드는 것

- `pipelines/gold_b/views/payment_conflicts.sql`, `payment_attempts.sql`, `malformed_messages.sql`: 설계 문서의 SQL을 그대로 옮김 (맨 위에 설명 주석 두 줄)
- `malformed_messages`의 시간 폴더 칸(`dt`, `hour`): 설계 문서의 결정 표, 뷰 SQL, 조회 예시, 팀원 확인 표(주현 님)
- `pipelines/gold_b/views/README.md`: 뷰 설명, 조회할 때(폴더 조건), Athena에서 만드는 순서, 처음 만들 때 확인할 것
- `pipelines/gold_b/tests/test_views.py`: 파일과 설계 문서의 SQL이 같은지, `malformed_messages`가 `dt`·`hour`를 내보내고 묶음 기준에 넣는지
- `pipelines/gold_b/README.md`, 설계 문서 3단계 체크, `docs/BRANCHES.md` 한 줄
- #36·#63 정리: `docs/BRANCHES.md`, `docs/tasks/gold-b-pipelines.md`, `docs/tasks/pipelines-format-rules-gold-b.md`, 설계 문서 1·2단계 체크와 팀원 확인 표(현지 님 항목)

## 만들지 않는 것

- Athena에서 뷰 생성, 샘플 결과 확인 (Athena 권한, 재영 님)
- 탐지가 묶어 세는 SQL과 그 쿼리의 폴더 조건 (탐지 규칙, 주현 님)
- `payment_attempts`·`payment_conflicts`의 시간 폴더 칸 (예전에 쌓인 같은 결제와도 비교해서 어차피 원장 전체를 읽는다)

## 완료 확인

- [x] `python -m pytest -q pipelines/gold_b/tests` 통과 (27개)
- [x] 최신 `main` 병합 뒤 `python -m pytest -q pipelines` 통과 (94개)
- [x] 뷰 파일 3개가 설계 문서의 SQL과 같은지
- [x] 로컬 Trino 484(Docker)에서 뷰 생성과 샘플 결과 확인
- [x] 로컬 Trino 484에서 `malformed_messages`의 `dt`·`hour` 조건이 원장을 읽는 단계로 내려가는지
- [ ] Athena에서 뷰 생성 → **대기** (권한)

## 작업 결과 (머지 전에 작성한다)

- **한 줄 요약:** 설계 문서의 정리 뷰 SQL 3개를 `pipelines/gold_b/views/`에 파일로 옮기고, 둘이 어긋나지 않는지 확인하는 시험을 더했다. `malformed_messages`가 시간 폴더(`dt`, `hour`)를 내보내게 해서 판정·조사 쿼리가 폴더 조건으로 그 폴더만 읽을 수 있게 했다. Athena에서 만드는 것은 아직이다.
- **무엇을 만들었나:** `views/payment_conflicts.sql`, `payment_attempts.sql`, `malformed_messages.sql`, `views/README.md`, `tests/test_views.py`, `pipelines/gold_b/README.md`, 설계 문서(3단계 체크, 시간 폴더 결정·조회 예시, 팀원 확인 표), `docs/BRANCHES.md`. 최신 `main` 병합과 #36·#63 정리.
- **왜 그렇게 했나:**
  - 설계 문서를 원본으로 두고 파일은 복사본으로 했다. 설계 문서의 SQL을 고치고 파일을 안 고치면(또는 반대) 시험이 실패한다. `payment_attempts`가 `payment_conflicts`를 읽어서 만드는 순서를 README에 적었다.
  - 판정 잡(`agent/detect/job.py`)과 조사 도구(`agent/tools/ledger_tools.py`)가 쓰는 뷰·칸을 대조해 보니 모두 있었다. 다만 쿼리에 시간 폴더 조건이 없고 뷰도 `dt`·`hour`를 내보내지 않아서, 5분마다 원장 전체를 읽는다.
  - 한 메시지의 오류 줄은 모두 같은 시간 폴더에 있어서, `dt`·`hour`를 묶음 기준에 넣어도 결과는 같고 폴더 조건은 원장까지 내려간다. `payment_attempts`·`payment_conflicts`는 예전에 쌓인 같은 결제와도 비교해야 해서 폴더 조건이 원장까지 내려갈 수 없으므로 그대로 둔다.
- **확인한 결과:**
  - `pipelines/gold_b/tests` 27개 통과 (테이블 정의 22 + 뷰 5). 최신 `main` 병합 뒤 `pipelines` 94개 통과. `git diff --check` 통과.
  - **로컬 Trino 확인 (2026-10-22, Docker `trinodb/trino:484`):** Athena 엔진 3은 Trino 기반이라 같은 문법으로 확인했다. 메모리 카탈로그에 원장 2개(DDL과 같은 컬럼, `TIMESTAMP`는 밀리초)를 만들고 샘플 31건의 기대 결과로 줄을 넣었다 (결제 10줄, 오류 17줄, `loaded_at`은 Kafka 시각 30초 뒤). 뷰 파일 3개를 순서대로 실행했고 오류 없이 만들어졌다 (`filter(ARRAY[...])`, `ARRAY_AGG(CAST(ROW(...)))`, SQL 안의 `--` 주석 포함).
    - `payment_conflicts`: 충돌 두 쌍이 1줄씩, `row_count` 2. `conflict_fields`는 상태가 다른 쌍이 `[status, failure_code]`, 금액만 다른 쌍이 `[payment_content_hash]`. `sources`에 원본 위치 두 개.
    - `payment_attempts`: 남는 결제와 실패 원인(`PG`/`CUSTOMER`/`UNKNOWN`)이 샘플 기대값과 같음. 같은 결제 중복은 먼저 쌓인 줄(06:01:32) 하나.
    - `malformed_messages`: 깨진 메시지마다 1줄, 오류 3개짜리는 `error_count` 3.
  - **시간 폴더 칸 확인 (2026-10-22, 같은 Trino 484):** 깨진 메시지 4개(오류 6줄, 규칙 버전 2개, 시간 폴더 2개)로 뷰를 다시 만들었다.
    - 메시지·규칙 버전마다 1줄이고 `dt`·`hour`가 함께 나왔다. 오류 3개짜리는 `error_count` 3.
    - `dt = '2026-10-21' AND hour IN ('06')` 조건으로 센 결과가 기대대로였다 (클릭 1, 결제 1).
    - 실행 계획에서 폴더 조건이 뷰의 묶음 아래, 원장을 읽는 단계로 내려갔다: `ScanFilter[table = memory:gold_b.malformed_events, filterPredicate = ((dt = varchar '2026-10-21') AND (hour = varchar '06'))]`. Athena에서는 이 조건으로 파티션 프로젝션의 그 폴더만 읽을 것으로 보고, 처음 만들 때 읽은 데이터 크기로 확인한다 (`views/README.md`).
  - 판정·조사 쪽 칸 대조: `payment_attempts`(`pg`, `status`, `failure_code`, `failure_cause`, `order_id`, `attempt_no`, `completed_at`, `loaded_at`), `malformed_messages`(`topic`, `kafka_timestamp`, `rule_version`, `loaded_at`)와 원장 표 칸이 모두 있다. 대시보드(`dashboard/data.py`, 아직 더미 데이터)는 `payment_attempts`에 `copies`를 기대하지만 뷰에는 없다 (설계 문서 팀원 확인 표, 민혁 님).
- **알려진 한계·남은 일:**
  - Athena에서 직접 만들어 보는 것은 권한이 생긴 뒤에 한다. Trino에서는 통과했지만 Athena는 뷰를 Glue에 저장하므로 한 번은 실제로 확인한다 (`views/README.md`의 확인 목록).
  - `payment_conflicts` SQL 안에 `--` 주석이 한 줄 있다. Trino에서는 문제없었고, Athena에서 문제가 되면 설계 문서와 파일에서 같이 뺀다.
  - 주현 님: 판정·조사 쿼리에 시간 폴더 조건 추가, 판정 설정 `format_rule_version`을 `0.2.0`으로 (지금 `0.1.0`이면 R4가 깨진 메시지를 0건으로 센다). 설계 문서 팀원 확인 표에 적었다.
  - 민혁 님: 대시보드의 `copies` 칸을 어떻게 할지.
