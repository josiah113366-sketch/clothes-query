# pipelines/gold_b/jobs

Gold B 잡을 둔다. 지금은 **재처리 잡**(`reprocess.py`, 7단계 필수 ②)과 **파일 합치기**(`compact.py`, 6단계)가 있다. 적재 잡(4단계)은 나중에 여기에 만든다.

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

## 파일 합치기 (`compact.py`)

적재 잡과 수집기가 1분마다 파일을 하나씩 만들어서 한 시간 폴더에 60개 넘게 쌓인다. 하루 1회, 끝난 UTC 하루의 시간 폴더마다 파일을 하나로 합친다.

1. 그 날 끝 + 10분이 안 지났으면 거부한다.
2. 원장 4개 × 24개 시간 폴더마다, 파일이 2개 이상이면 합친다. `reprocess_events`는 합치지 않는다.
3. **줄은 하나도 빼거나 고치지 않는다** (`loaded_at` 포함). `topic_messages`의 같은 위치 두 줄도 탐지가 보는 신뢰성 신호라서 그대로 둔다.
4. 합친 파일(`part-compact-…`)을 먼저 쓰고 줄 수를 확인한 뒤 원래 파일을 지운다. 합친 파일에는 원래 파일 이름 목록을 적어 둔다. 지우다가 멈춘 뒤 다시 돌리면, 남은 원래 파일은 다시 합치지 않고 지운다 (줄이 두 번 들어가지 않음).
5. 적재 잡이 그 사이 새로 쓴 파일은 목록에 없어서 지워지지 않고, 다음에 합친다.

**재처리 잡과 같은 폴더를 동시에 건드리면 안 된다.** DAG(재영 님과 만듦)에서 둘을 한 번에 하나씩 돌린다.

```python
from datetime import date
from pipelines.gold_b.jobs.compact import run
from pipelines.gold_b.ledger import open_store

run(date(2026, 10, 21), store=open_store(…))   # s3://<버킷>/gold_b 또는 로컬 폴더. DAG는 어제(UTC)를 넘긴다
```

S3 권한은 원장 4개 폴더 읽기·쓰기·지우기다. 확인은 `python -m pytest -q pipelines/gold_b/tests/test_compact.py`.
