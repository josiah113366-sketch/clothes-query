# pipelines/gold_b

Gold B(관제용)는 Kafka 메시지를 1분마다 **원장**에 한 줄씩 쌓고, 탐지·에이전트는 Athena에서 원장과 **정리 뷰**를 읽는다. 설계 전체는 [docs/design/gold-b/README.md](../../docs/design/gold-b/README.md), 작업 기록은 [docs/tasks/gold-b-pipelines.md](../../docs/tasks/gold-b-pipelines.md).

## 지금 있는 것

| 경로 | 내용 |
|---|---|
| `ddl/database.sql` | Glue 데이터베이스 `gold_b` |
| `ddl/payment_events.sql` | ① 결제 이벤트 원장 (`completed_at` 시간 폴더). 결제 내용 지문(`payment_content_hash`, `fingerprint_version`) 포함. 결제 수정(`u`)도 쌓고 변경 종류·원본 변경 시각·규칙 버전을 남김 (2026-10-23) |
| `ddl/topic_messages.sql` | ② 메시지 원장, 6개 토픽 전부 (`kafka_timestamp` 시간 폴더) |
| `ddl/bronze_lag_snapshots.sql` | ③ Bronze 지연 측정 (`collected_at` 시간 폴더) |
| `ddl/malformed_events.sql` | ④ 형식 오류, 오류 하나 = 한 줄 (`kafka_timestamp` 시간 폴더) |
| `ddl/reprocess_events.sql` | ⑤ 재처리 단계 기록 (시간 폴더 없음) |
| `tests/samples/` | 형식 검사·뷰·적재 잡 확인용 샘플 메시지와 기대 결과 ([설명](tests/samples/README.md)) |
| `tests/test_ddl.py` | DDL이 설계 표와 같은지, 샘플이 규칙에 맞는지, 샘플 원장을 시간 폴더 Parquet으로 쓰고 읽을 수 있는지 |
| `views/` | 정리 뷰 SQL 4개 (`payment_states`, `payment_conflicts`, `payment_attempts`, `malformed_messages`), Athena에서 만드는 순서와 표 칸 추가 ([설명](views/README.md)) |
| `tests/test_views.py` | 뷰 SQL 파일이 설계 문서의 SQL과 같은지 |
| `tests/test_payment_states.py` | 결제 정리 뷰: 샘플을 실제 형식 검사기로 원장에 넣고 뷰 SQL을 SQLite로 돌려 결제마다 마지막 이벤트·보류 사유가 기대 결과와 같은지, 재처리 뒤 결제 상태 (복구, 보류 유지, 늦게 온 수정을 Kafka 시각 폴더만으로 복구, 대상이 아닌 메시지는 그대로, 중간에 멈춰도 결과 유지) |
| `collector/` | Bronze 지연 수집기: ③ `bronze_lag_snapshots`를 1분마다 쌓음 ([설명](collector/README.md)) |
| `tests/test_lag_collector.py` | 수집기 계산·상태·파일 쓰기 (가짜 Kafka·Connect) |
| `ledger.py` | 원장 공통 도구: 표별 Parquet 스키마(DDL과 같음), 시간 폴더, 메시지 하나의 원장 줄, 파일 저장소(로컬·S3) |
| `format_check.py` | 형식 검사기: 메시지 하나를 공통 형식 규칙(`gold_b`)으로 검사해 ① 결제 줄(지문 포함)과 ④ 오류 목록을 만듦. 적재 잡·재처리 잡이 같이 씀 |
| `tests/test_format_check.py` | 샘플 전부의 기대 결과, 결제 줄과 지문, `raw_sample` 마스킹, 읽을 수 없는 값 |
| `jobs/reprocess.py` | 재처리 잡: 승인된 시간대에 Kafka에 들어온 메시지를 다시 검사해 그 메시지들의 옛 결과(①②④)만 새 결과로 바꿈. 범위 밖 결제 시각 폴더도 고침. poller와 실행 입구 ([설명](jobs/README.md)) |
| `tests/test_reprocess.py` | 재처리 교체·재실행·남기는 줄·시작 전 거부·중간 실패, poller, 실행 입구 (가짜 Kafka, 샘플 메시지) |
| `jobs/compact.py` | 파일 합치기: 끝난 하루의 시간 폴더마다 작은 파일을 하나로 (줄은 그대로) ([설명](jobs/README.md)) |
| `tests/test_compact.py` | 합친 뒤 줄이 그대로인지, 안 끝난 날 거부, 중간에 멈춘 뒤 다시 돌리기 |
| `requirements.txt` | Gold B 실행 패키지 (`confluent-kafka`, `pyarrow`, `boto3`, `PyYAML`). Spark는 실행 환경이 준다 |
| `jobs/streaming_ingest.py` | 적재 잡: Kafka를 Spark로 1분마다 읽어 형식 검사기로 원장 ①②④에 쌓음. 실행 입구 ([설명](jobs/README.md)) |
| `config/gold_b.yaml` | 적재 잡 설정: 토픽 목록, 주기, 처음 읽기 시작할 곳, 묶음 크기 (주소·버킷 이름은 환경변수) |
| `tests/test_ingest.py` | 묶음 하나가 시간 폴더로 가는지, 같은 묶음을 다시 써도 두 번 쌓이지 않는지, 설정, 형식 검사기 연결, 실행 입구 |
| `Dockerfile` | Gold B 이미지: 적재 잡·재처리 잡·파일 합치기·Bronze 지연 수집기를 한 이미지로. 팀 기본 Spark 이미지에서 출발 (아래 「이미지」) |
| `Dockerfile.dockerignore` | 이미지에 넣는 파일 목록 (잡이 쓰는 코드·설정·형식 규칙표만) |
| `tests/test_image.py` | 이미지에 넣는 파일이 잡 4개가 부르는 모듈을 모두 담고 시험·문서·로컬 파일은 빼는지, Dockerfile의 약속 (빌드 없이) |
| `tests/test_dags.py` | Airflow DAG(`infra/platform/airflow/dags/gold_b.py`): 재처리·파일 합치기의 주기·재시도·꺼진 채로 생성, Pod 명령·환경변수·Kafka 인증서, 같은 pool, 실행 설정 확인 (가짜 Airflow 모듈) |

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

## 이미지

잡 4개(적재 잡, 재처리 잡, 파일 합치기, Bronze 지연 수집기)를 이미지 하나로 돌린다 (`Dockerfile`). 팀 기본 Spark 이미지(`infra/platform/spark/image`: Spark 4.2.0, Python 3.10.12, Kafka 연결·S3A jar)에서 출발해 Gold B 코드와 패키지(`requirements.txt`)를 더한다. 공통 모듈과 형식 규칙표가 Gold B 폴더 밖에 있어서 저장소 루트에서 빌드한다.

```bash
docker build -f pipelines/gold_b/Dockerfile --build-arg SPARK_IMAGE=<팀 기본 이미지>@sha256:<digest> --build-arg CODE_REF=<머지된 main 커밋> -t <Gold B 이미지>:<태그> .
```

- `SPARK_IMAGE`에는 기본값이 없다. 공식 `apache/spark`에는 Kafka 연결 jar가 없어서 적재 잡이 돌지 않으므로, 빌드할 때 Kafka 연결·S3A jar가 없으면 멈춘다.
- `CODE_REF`는 머지된 main 커밋이다 (이미지 안 `GOLD_B_CODE_REF`). 빌드할 때 잡 4개를 import해서 넣을 파일이 빠지지 않았는지 확인한다.
- 이미지 안 코드 위치는 `/opt/gold_b`(`PYTHONPATH`), 실행 사용자는 185, 진입점은 기본 이미지의 Spark 진입점 그대로다.
- 넣는 파일: 공통 모듈 `pipelines/*.py`(시험 파일 제외), Gold B 코드·설정 `config/gold_b.yaml`·`requirements.txt`, `docs/contracts/format_rules.yaml`. 시험·문서·Athena SQL·로컬 가상환경·캐시는 넣지 않는다 (`Dockerfile.dockerignore`).

| 잡 | 실행 명령 |
|---|---|
| 적재 잡 (상시) | `spark-submit local:///opt/gold_b/pipelines/gold_b/jobs/streaming_ingest.py` |
| 재처리 잡 (Airflow `gold_b_reprocess`, 5분마다) | `python3 -m pipelines.gold_b.jobs.reprocess` |
| 파일 합치기 (Airflow `gold_b_compact`, 매일 00:30 UTC) | `python3 -m pipelines.gold_b.jobs.compact` |
| Bronze 지연 수집기 (상시 또는 1분마다) | `python3 -m pipelines.gold_b.collector.bronze_lag_collector --interval 60` 또는 `--once` |

환경변수와 배포에 필요한 것은 [jobs/README.md](jobs/README.md), [collector/README.md](collector/README.md)에 있다. Airflow DAG는 `infra/platform/airflow/dags/gold_b.py`이고 실행 설정은 [DAG 설명](../../infra/platform/airflow/dags/README.md)에 있다. 이미지를 ECR에 올리고 배포하는 것은 재영 님과 한다. 팀 기본 이미지가 ECR에 올라오기 전에는 실제 빌드를 하지 않는다.

## 의존하는 것

- 입력 토픽과 메시지 모양: `connectors/cdc-source.yaml` (봉투가 풀린 평평한 CDC JSON, `__op`), 시뮬레이터의 `clickstream`
- 결제 컬럼: `db/schema/004_orders.sql`
- 형식 검사 규칙표: `docs/contracts/format_rules.yaml` (형식 검사기 `format_check.py`가 `gold_b` 규칙으로 읽음)
- 결제 내용 지문: `pipelines/payment_fingerprint.py` (형식 검사기가 결제 줄에 붙임. Silver와 같은 함수)
