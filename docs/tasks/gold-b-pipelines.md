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

- [x] `python -m pytest -q pipelines/gold_b/tests` 통과 (22개)
- [ ] 로컬 Spark에서 DDL 6개 실행, 빈 테이블 조회 0건 → **이 PC에서 실행 불가** (아래 작업 결과)
- [x] 샘플 기대 결과를 원장 모양으로 만든 Parquet을 시간 폴더에 두고 조회되는지 (pyarrow로 대신 확인)
- [x] DDL과 샘플에 비밀값·계정 ID·개인정보 값이 없는지 (`git grep`)
- [ ] Athena에서 생성·빈 조회 → **대기** (Glue 관리 방식·권한, 재영 님)

## README 갱신

- `pipelines/gold_b/README.md` 새로 만듦
- `pipelines/README.md`는 Silver 담당 파일이라 고치지 않는다 (Gold B 줄 추가는 머지 때 협의)

## 작업 결과 (머지 전에 작성한다)

### 1단계 (2026-10-21)

- **한 줄 요약:** Gold B 설계 문서를 저장소에 옮기고, 원장 4개·재처리 기록의 Athena 테이블 정의와 샘플 메시지 29개를 만들었다.
- **무엇을 만들었나:**
  - `docs/design/gold-b/README.md`: 설계 (오늘 결정과 실제 커넥터 설정 반영, 「2026-10-21 반영」 절)
  - `pipelines/gold_b/ddl/`: `database.sql` + 테이블 5개. 원장은 Parquet, UTC `dt`/`hour` 시간 폴더, 파티션 프로젝션(`2026-09-01,NOW`, 시간 0~23 두 자리)
  - `pipelines/gold_b/tests/samples/`: 결제 16개, 나머지 5개 토픽 13개. 메시지마다 기대 결과(원장, 오류 필드·사유, 뷰 결과)
  - `pipelines/gold_b/tests/test_ddl.py`, `pipelines/gold_b/README.md`
- **왜 그렇게 했나:**
  - 충돌 결제: 첫 줄을 남기는 안 대신 Silver(PR #26)·공통 계약과 같이 모든 줄을 빼고 `payment_conflicts`로 보여 준다 (사용자 결정). 비교 컬럼은 Gold B 원장의 6개.
  - `kafka_partition`: 표끼리 이름을 맞추고, Athena DDL 예약어 `partition`을 피했다.
  - 기획의 `after.payment_id`는 실제 설정(`ExtractNewRecordState`로 봉투를 풂)과 달라서, 샘플은 평평한 메시지 + `__op` 모양으로 만들었다.
  - `reprocess_events`는 양이 적어 시간 폴더 없이 만들었다.
- **입력과 출력:**
  - 정한 것: 테이블 이름 `gold_b.*`, 컬럼 이름·타입, S3 경로 `s3://clothes-query-datalake/gold_b/<표>/dt=…/hour=…/`
  - 주현 님께 공유할 것: `reprocess_events` 12개 컬럼, `payment_conflicts`, `bronze_lag_snapshots.kafka_partition`
- **확인한 결과:**
  - `python -m pytest -q pipelines/gold_b/tests`: 22개 통과 (2.6초)
  - `python -m pytest -q pipelines`: Silver 포함 50개 통과
  - 샘플 원장을 시간 폴더 Parquet으로 쓰고 다시 읽기: 결제 8줄, 메시지 29줄, 오류 = 기대 오류 합, 한 메시지 최대 3줄. 컬럼 타입이 DDL과 같음
  - `git grep`으로 키·계정 ID·엔드포인트 없음 확인 (걸린 것은 가짜 UUID와 밀리초 시각)
  - 로컬 Spark(Hive DDL) 실행은 이 PC에서 안 됨: Java NIO 파이프가 Unix 도메인 소켓 연결에서 `Invalid argument`로 멈춘다. 샌드박스 밖, 짧은 임시 경로, `jdk.net.unixdomain.tmpdir` 지정 모두 같았다. 대신 DDL을 읽어 설계 표와 비교했고, Parquet 왕복은 pyarrow로 확인했다.
- **알려진 한계·남은 일:**
  - Athena에서 실제 생성·빈 조회는 하지 않았다. Glue DB를 Terraform으로 관리할지와 Athena 권한을 재영 님께 확인한 뒤 실행한다.
  - 샘플 중 사유를 정하지 않은 것: 회원 PII 컬럼 오류의 사유(`reason: null`), `op u` 결제를 오류로도 기록할지. 2단계에서 정한다.
  - `unit_price ≥ 5,900`(설계)과 공통 계약 초안 `minimum: 1`이 다르다. 결제 충돌 비교 컬럼도 현지 님과 맞춰야 한다.
  - `team-inputs.md`(인프라)의 재판정 연결 문장이 이 설계와 다르다. 재영 님께 공유해야 한다.
  - `pipelines/README.md`는 Silver 문서라 Gold B 줄을 넣지 않았다.
