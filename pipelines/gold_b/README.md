# pipelines/gold_b

Gold B(관제용)는 Kafka 메시지를 1분마다 **원장**에 한 줄씩 쌓고, 탐지·에이전트는 Athena에서 원장과 **정리 뷰**를 읽는다. 설계 전체는 [docs/design/gold-b/README.md](../../docs/design/gold-b/README.md), 작업 기록은 [docs/tasks/gold-b-pipelines.md](../../docs/tasks/gold-b-pipelines.md).

## 지금 있는 것

| 경로 | 내용 |
|---|---|
| `ddl/database.sql` | Glue 데이터베이스 `gold_b` |
| `ddl/payment_events.sql` | ① 결제 시도 원장 (`completed_at` 시간 폴더). 결제 내용 지문(`payment_content_hash`, `fingerprint_version`) 포함 |
| `ddl/topic_messages.sql` | ② 메시지 원장, 6개 토픽 전부 (`kafka_timestamp` 시간 폴더) |
| `ddl/bronze_lag_snapshots.sql` | ③ Bronze 지연 측정 (`collected_at` 시간 폴더) |
| `ddl/malformed_events.sql` | ④ 형식 오류, 오류 하나 = 한 줄 (`kafka_timestamp` 시간 폴더) |
| `ddl/reprocess_events.sql` | ⑤ 재처리 단계 기록 (시간 폴더 없음) |
| `tests/samples/` | 형식 검사·뷰·적재 잡 확인용 샘플 메시지와 기대 결과 ([설명](tests/samples/README.md)) |
| `tests/test_ddl.py` | DDL이 설계 표와 같은지, 샘플이 규칙에 맞는지, 샘플 원장을 시간 폴더 Parquet으로 쓰고 읽을 수 있는지 |
| `views/` | 정리 뷰 SQL 3개 (`payment_conflicts`, `payment_attempts`, `malformed_messages`), Athena에서 만드는 순서 ([설명](views/README.md)) |
| `tests/test_views.py` | 뷰 SQL 파일이 설계 문서의 SQL과 같은지 |
| `collector/` | Bronze 지연 수집기: ③ `bronze_lag_snapshots`를 1분마다 쌓음 ([설명](collector/README.md)) |
| `tests/test_lag_collector.py` | 수집기 계산·상태·파일 쓰기 (가짜 Kafka·Connect) |
| `requirements.txt` | Gold B 실행 패키지 (`confluent-kafka`, `pyarrow`, `boto3`) |

정리 뷰 SQL은 설계 문서가 원본이고 `views/`는 Athena에서 실행할 복사본이다. Athena에서 만드는 것은 권한이 생긴 뒤에 한다.

## 저장 위치와 시간 폴더

```
s3://clothes-query-datalake/gold_b/<표>/dt=YYYY-MM-DD/hour=HH/*.parquet   (원장 4개, UTC)
s3://clothes-query-datalake/gold_b/reprocess_events/*.parquet
```

- 원장 4개는 Athena **파티션 프로젝션**을 쓴다. 새 시간 폴더를 `MSCK REPAIR`나 `ALTER TABLE ADD PARTITION` 없이 바로 읽는다. 범위는 `2026-09-01`부터 오늘(UTC)까지다.
- 조회할 때 `WHERE dt = '2026-10-21' AND hour = '06'`처럼 폴더 조건을 같이 주면 그 폴더만 읽는다.
- 시각 컬럼은 모두 UTC `TIMESTAMP`다. Parquet에 시각을 어떤 형식(마이크로초 / Spark 기본 INT96)으로 쓸지는 4단계 적재 잡에서 Athena로 읽어 보고 정한다. 1단계 테스트는 마이크로초로 쓴다.

## 실행

로컬 확인 (Athena 접속 없음):

```bash
python -m pytest -q pipelines/gold_b/tests
```

필요한 패키지는 `requirements.txt`와 `pytest`다. Gold B 가상환경(`pipelines/gold_b/.venv`)을 만드는 방법은 [collector/README.md](collector/README.md)의 「실행」에 있다.

Athena에 만들기 (권한 준비 후): `ddl/database.sql` → 나머지 5개 순서로 Athena 쿼리 편집기에서 하나씩 실행한다. 파일 맨 위의 `--` 설명 줄과 끝의 `;`는 Athena API로 실행할 때 문제가 될 수 있으니, 콘솔이 아닌 스크립트로 돌릴 때는 빼고 보낸다.

## 의존하는 것

- 입력 토픽과 메시지 모양: `connectors/cdc-source.yaml` (봉투가 풀린 평평한 CDC JSON, `__op`), 시뮬레이터의 `clickstream`
- 결제 컬럼: `db/schema/004_orders.sql`
- 형식 검사 규칙표: `docs/contracts/format_rules.yaml` (2단계에서 연결)
- 결제 내용 지문: `pipelines/payment_fingerprint.py` (2단계, Silver와 같은 함수. 규칙은 현지 님과 정함)
