# 작업 지시서: pipelines/gold-b

> 상태: 진행 중 · 브랜치: `pipelines/gold-b` · 다음 작업: 2단계 정제·형식 검사 (브랜치는 1단계 머지 때 정함)

## 목표

Gold B 1단계: 원장 4개와 재처리 기록 1개의 테이블 정의(Athena DDL)와, 이후 단계에서 쓸 샘플 메시지를 만든다. 적재 잡·형식 검사 코드·뷰·수집기는 만들지 않는다.

## 먼저 읽을 것

- `docs/design/gold-b/README.md` (설계, 「확정한 결정」「저장」「2026-10-21 반영」)
- `docs/contracts/README.md`, `docs/contracts/format_rules.yaml` (공통 계약, 결제 충돌)
- `connectors/cdc-source.yaml`, `connectors/bronze-s3-sink.yaml` (실제 메시지 모양, 토픽 이름)
- `db/schema/004_orders.sql` (결제 컬럼)

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- 브랜치는 `pipelines/gold-b`, 코드는 `pipelines/gold_b/`, 커밋은 `pipelines(gold-b): …` (Silver와 같은 방식, `BRANCHES.md`의 `gold-b/` 접두어 대신).
- 설계 문서와 작업 지시서도 같은 브랜치에 넣는다.

## 시작 전 확인 (Claude가 한다)

- 브랜치가 최신 `main`(a72a3c5, PR #26 머지 후)과 같은지
- 로컬 PySpark·Java (DDL 실행 확인용)

## 만드는 것

### 1. 설계 문서
- `docs/design/gold-b/README.md`

### 2. 테이블 정의 (`pipelines/gold_b/ddl/`)
- `database.sql`, `payment_events.sql`, `topic_messages.sql`, `bronze_lag_snapshots.sql`, `malformed_events.sql`, `reprocess_events.sql`
- 원장 4개는 `dt`/`hour`(UTC) 시간 폴더 + 파티션 프로젝션. `reprocess_events`는 폴더 없음.

### 3. 샘플 메시지 (`pipelines/gold_b/tests/samples/`)
- 설계 1단계 목록 + 결제 내용 충돌 한 쌍. 메시지마다 기대 결과(어느 원장에 쌓이나, 어떤 오류가 나나)를 같이 적는다.
- 개인정보 값은 넣지 않는다 (회원 PII 오류 샘플은 값 대신 `<redacted>`).

### 4. 확인 코드
- `pipelines/gold_b/tests/test_ddl.py`: DDL 컬럼이 설계 표와 같은지, 로컬 Spark에서 DDL이 실행되고 빈 조회·샘플 Parquet 조회가 되는지, 샘플 파일 형식이 맞는지

## 만들지 않는 것

- 형식 검사 코드·규칙표 수정 → 2단계
- 뷰 SQL 파일 → 3단계 (SQL은 설계 문서에 있음)
- 적재 잡, 수집기, 파일 합치기, 재처리 → 4~7단계
- Athena·Glue 실제 생성 → 권한·관리 방식(재영 님) 확인 후

## 작업 순서

1. 시작 전 확인을 하고, 계획을 먼저 제시해 사용자 확인을 받는다 (2026-10-21 완료)
2. 설계 문서·작업 지시서·브랜치 대장 커밋
3. 샘플 메시지 커밋
4. DDL과 확인 코드 커밋
5. "완료 확인"을 실행하고 결과 보고

## 완료 확인

- [ ] `python -m pytest -q pipelines/gold_b/tests` 통과
- [ ] 로컬 Spark에서 DDL 6개 실행, 빈 테이블 조회 0건
- [ ] 샘플 기대 결과를 원장 모양으로 만든 Parquet을 시간 폴더에 두고 조회되는지
- [ ] DDL과 샘플에 비밀값·계정 ID·개인정보 값이 없는지 (`git grep`)
- [ ] Athena에서 생성·빈 조회 (권한 준비 전이면 "대기"로 보고)

## README 갱신

- `pipelines/gold_b/README.md` 새로 만듦
- `pipelines/README.md`는 Silver 담당 파일이라 고치지 않는다 (Gold B 줄 추가는 머지 때 협의)

## 작업 결과 (머지 전에 작성한다)

- **한 줄 요약:**
- **무엇을 만들었나:**
- **왜 그렇게 했나:**
- **입력과 출력:**
- **확인한 결과:**
- **알려진 한계·남은 일:**
