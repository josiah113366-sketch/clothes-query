# pipelines/gold_b/jobs

Gold B 잡을 둔다. 지금은 **재처리 잡**(`reprocess.py`, 7단계 필수 ②)과 **적재 잡**(`streaming_ingest.py`, 4단계)이 있다. 파일 합치기(6단계)는 나중에 여기에 만든다.

## 적재 잡 (`streaming_ingest.py`)

Kafka 토픽(`config/gold_b.yaml`)을 Spark Structured Streaming으로 1분마다 읽어 원장 ①②④에 쌓는다. ③은 수집기가 쌓는다.

- 묶음 하나(`write_batch`): 메시지마다 형식 검사를 하고 원장 줄을 만든다 (재처리 잡과 같은 `ledger.message_rows`). ②에는 모든 메시지, ①에는 형식을 통과한 결제, ④에는 오류마다 한 줄. 줄을 이벤트 시각의 시간 폴더로 나눠 (표, 시간 폴더)마다 파일 하나로 쓰고, `loaded_at`은 그 묶음을 쓴 시각이다.
- 파일 이름은 그 파일에 든 메시지 위치로 정한다 (`part-ingest-<16자리>.parquet`). Spark가 끝내지 못한 묶음을 다시 처리하면 덮어써서 두 번 쌓이지 않는다.
- 어디까지 읽었는지는 Spark 체크포인트가 기억한다. 체크포인트가 없으면 Kafka에 남은 가장 오래된 메시지부터 읽는다. 묶음 하나는 최대 20,000건.
- 보관 기간보다 오래 멈춰 메시지가 지워졌으면 멈추지 않고 남은 것부터 읽는다. 빠진 구간은 `topic_messages` 오프셋 빈틈으로 보이고 Bronze 재처리로 채운다.

| 환경변수 | 뜻 |
|---|---|
| `GOLD_B_LEDGER_ROOT` | 원장 저장 위치 (`s3://<버킷>/gold_b` 또는 로컬 폴더) |
| `GOLD_B_CHECKPOINT` | Spark 체크포인트 위치 (S3면 `s3a://…`) |
| `KAFKA_BOOTSTRAP`, `KAFKA_SECURITY_PROTOCOL` | Kafka 주소, `PLAINTEXT` 또는 `SSL` (시뮬레이터·수집기와 같은 이름) |
| `KAFKA_SSL_CA_FILE`, `KAFKA_SSL_CERT_FILE`, `KAFKA_SSL_KEY_FILE` | SSL일 때 PEM 파일 (클라이언트 인증서는 둘 다) |

**형식 검사(2단계)가 없어서 아직 실행하지 않는다.** Spark 연결(`build_query`)은 Docker의 Spark 4.1.3으로 로컬 Kafka를 읽어 확인했다 (같은 체크포인트로 다시 켜도 빠지거나 두 번 쌓이지 않음). 단위 시험은 `write_batch`만 본다. Spark 런타임(이미지, `spark-sql-kafka` jar, S3 체크포인트용 `hadoop-aws`)과 배포는 재영 님과 정한다. 부를 때는 Spark 세션을 만든 뒤 `build_query(spark, settings=Settings.from_env(os.environ), config=load_config(), checker=…, store=open_store(…))`.

확인: `python -m pytest -q pipelines/gold_b/tests/test_ingest.py` (설정 파일 시험은 `PyYAML`이 있어야 돈다).

## 재처리 잡이 하는 일

규칙이나 코드를 고친 뒤 사람이 승인하면, 그 시간대의 원장 ①`payment_events` ②`topic_messages` ④`malformed_events`를 Kafka에서 다시 읽어 **1시간 폴더 단위로 교체**한다. ③`bronze_lag_snapshots`는 그 시점에만 잴 수 있는 값이라 건드리지 않는다. 설계는 [docs/design/gold-b/README.md](../../../docs/design/gold-b/README.md) 「재실행·재처리 설계와 검증」이다.

1. 승인 범위를 UTC 1시간 폴더로 넓힌다. 끝은 포함하지 않는다 (14:40~16:20 → 14·15·16시).
2. 시작 전에 확인하고, 걸리면 `FAILED`로 끝낸다 (다시 돌려도 소용없어서 재시도하지 않음).
   - 형식 검사 함수의 규칙 버전이 승인된 `rule_version`과 다름
   - 아직 안 끝난 폴더가 있음 (폴더 끝 + 10분이 지나지 않음)
   - Kafka 보관 기간(72시간) 밖 → 원본 없음. Bronze에서 다시 읽기는 아직 없다
3. `reprocess_events`에 `STARTED`를 쓴다.
4. 폴더마다 차례로:
   - 폴더 앞뒤로 10분씩 더 Kafka에서 읽는다 (시각으로 위치를 찾음). 결제는 결제 시각보다 늦게 Kafka에 들어올 수 있어서다.
   - 메시지마다 형식 검사를 하고 원장 줄을 만든 뒤, 이벤트 시각(결제 `completed_at`, 나머지 `kafka_timestamp`)이 그 폴더인 줄만 고른다.
   - 원장 3개를 교체한다. **이번에 다시 읽은 메시지의 줄만** 새 줄로 바뀐다. 다시 읽지 못한 메시지(10분보다 늦게 온 결제, 대상이 아닌 토픽, 그 사이 지워진 메시지)의 옛 줄과 `malformed_events`의 다른 `rule_version` 줄은 그대로 남는다.
   - 새 파일을 먼저 쓰고 옛 파일을 지운다. 중간에 멈추면 잠깐 같은 줄이 두 번 있을 수 있지만(뷰가 거름) 줄이 사라지지는 않는다. 다시 돌리면 정리된다.
   - 원장 3개가 다 끝나면 `LEDGER_REPLACED`를 쓴다. 판정 잡이 이 줄을 보고 그 폴더를 재판정한다.
5. 도중에 실패하면 `FAILED`를 쓰고 예외를 다시 올린다. 끝난 폴더의 `LEDGER_REPLACED`는 남는다.

같은 입력과 같은 규칙으로 다시 돌리면 원장이 같다 (`loaded_at`만 다름).

## `reprocess_events`에 쓰는 줄

`actor`는 `reprocess_job`, `reason`은 비운다. `rule_version`, `attempt`, `parent_request_id`는 요청 값을 그대로 쓴다.

| `step` | `window_start` ~ `window_end` | `source` | `detail` (JSON) |
|---|---|---|---|
| `STARTED` | 승인 범위 | `KAFKA` | 교체할 폴더 목록, 여유 시간(분) |
| `LEDGER_REPLACED` | 교체한 시간 폴더 (예: 15:00 ~ 16:00) | `KAFKA` | 읽은 메시지 수, 표별 새 줄 수·남긴 옛 줄 수, Kafka에 없는 토픽 |
| `FAILED` | 시작 전이면 승인 범위, 도중이면 남은 폴더 범위 | 시작 전이면 비움, 도중이면 `KAFKA` | 실패 이유, 재시도해도 되는지(`retryable`), 끝낸 폴더 수 |

실패 이유에는 이 잡이 만든 문장만 쓰고, Kafka·S3 오류는 종류만 쓴다 (오류 문장에 주소·버킷 이름이 들어 있을 수 있음).

## 부르는 방법

형식 검사(2단계)가 아직 없어서 **지금은 단독으로 실행하지 않는다.** 명령줄 진입점과 Airflow DAG는 형식 검사가 생긴 뒤 만든다. 그때 DAG는 아래처럼 부르고, `ReprocessError`의 `retryable`이 `False`면 재시도 없이 멈추게 한다. 한 번에 하나씩 돌리기와 재시도 2번은 DAG가 맡는다.

```python
from pipelines.gold_b.jobs.reprocess import KafkaReader, Request, run
from pipelines.gold_b.ledger import open_store

result = run(
    Request(request_id="rq-…", window_start=…, window_end=…, rule_version="…", attempt=try_number),
    source=KafkaReader({"bootstrap.servers": …}),   # 수집기와 같은 KAFKA_* 환경변수로 만든다
    store=open_store(…),                            # s3://<버킷>/gold_b 또는 로컬 폴더
    checker=…,                                      # 형식 검사 함수 (rule_version 속성 + 메시지 하나 → 판정)
)
result.replaced   # 실제로 교체한 시간 폴더 [시작, 끝) 목록
```

`checker`는 메시지 하나를 받아 결제 원장의 업무 칼럼(오류 없는 결제만)과 오류 목록만 돌려준다 (`ledger.Judgement`). Kafka 위치·`loaded_at`·`rule_version`은 잡이 붙인다 (`ledger.message_rows`). 적재 잡도 같은 함수를 쓴다.

## 의존하는 것

- 패키지: `confluent-kafka`, `pyarrow`, `boto3` (`pipelines/gold_b/requirements.txt`). Spark는 쓰지 않는다 (한 시간 폴더는 수천 줄).
- Kafka: 대상 토픽 읽기 (임시 그룹으로 `assign`만, 커밋 없음)
- S3: `gold_b/payment_events/`, `gold_b/topic_messages/`, `gold_b/malformed_events/` 읽기·쓰기·지우기, `gold_b/reprocess_events/` 쓰기

## 확인

```bash
python -m pytest -q pipelines/gold_b/tests/test_reprocess.py
```

가짜 Kafka와 샘플 메시지(`tests/samples/`)로 교체 결과, 두 번 돌린 결과, 남기는 줄, 시작 전 거부, 중간 실패와 다시 돌리기를 확인한다.
