# pipelines/gold_b/jobs

Gold B 잡을 둔다. 지금은 **재처리 잡**(`reprocess.py`, 7단계 필수 ②), **적재 잡**(`streaming_ingest.py`, 4단계), **파일 합치기**(`compact.py`, 6단계)가 있다.

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
| `GOLD_B_RULES_PATH` | 형식 규칙표 경로 (생략하면 저장소의 `docs/contracts/format_rules.yaml`) |

### 적재 잡 부르는 방법

```bash
python -m pipelines.gold_b.jobs.streaming_ingest                    # 저장소 루트에서, 설정은 config/gold_b.yaml
python -m pipelines.gold_b.jobs.streaming_ingest --config <설정 파일>
```

- 형식 검사기(`pipelines/gold_b/format_check.py`, 공통 규칙의 `gold_b`)를 끼워 스트리밍을 시작하고 멈출 때까지 기다린다. 재처리 잡과 같은 검사기라 같은 메시지는 같은 원장 줄이 된다.
- 설정 파일·환경변수·형식 규칙표가 잘못됐으면 Spark를 띄우기 전에 1로 끝난다. 스트리밍 중 실패는 오류로 끝나고, 다시 띄우면 체크포인트에서 이어 읽는다.
- 로그에는 묶음 번호와 메시지·파일 수만 남긴다 (주소·메시지 내용은 남기지 않음).
- Spark 연결(`build_query`)은 Docker의 Spark 4.1.3으로 로컬 Kafka를 읽어 확인했다 (같은 체크포인트로 다시 켜도 빠지거나 두 번 쌓이지 않음). 형식 검사기를 끼운 Spark 실행은 아직 못 했다 (Gold B 이미지는 팀 기본 Spark 이미지가 ECR에 올라온 뒤 빌드).

### 적재 잡 배포에 필요한 것 (재영 님께)

- 늘 켜 두는 Spark 스트리밍 잡 하나. 같은 체크포인트로 두 개를 동시에 띄우지 않는다.
- 이미지: Gold B 이미지 `pipelines/gold_b/Dockerfile` (팀 기본 Spark 이미지 digest에서 출발, 빌드 방법은 [pipelines/gold_b/README.md](../README.md) 「이미지」). Driver와 Executor가 같은 이미지 digest를 쓴다.
- 제출: `spark-submit local:///opt/gold_b/pipelines/gold_b/jobs/streaming_ingest.py` (인자 없음, 설정은 이미지 안 `config/gold_b.yaml`). `PYTHONPATH=/opt/gold_b`는 이미지에 들어 있다.
- 늘 켜 둔다. 멈추면 다시 띄운다 (같은 체크포인트로 이어 읽어 빠지거나 두 번 쌓이지 않음). 같은 체크포인트로 두 개를 동시에 띄우지 않는다.
- 자원(제안): Driver 1개가 묶음(최대 20,000건)을 파이썬으로 처리하므로 1 CPU·2GiB, Executor 1개는 Kafka만 읽어 1 CPU·1GiB.
- S3 권한: `gold_b/topic_messages/`·`gold_b/payment_events/`·`gold_b/malformed_events/` 읽기·쓰기 (같은 이름 덮어쓰기 포함), 체크포인트 위치 읽기·쓰기·지우기. 체크포인트 위치 제안: `s3a://clothes-query-datalake/gold_b/_checkpoints/streaming_ingest/` (원장 표 위치와 겹치지 않음, 재영 님과 정함).
- Kafka: Strimzi `KafkaUser`(예: `gold-b-ingest`, TLS)에 6개 토픽 `Read`·`Describe`. 이 잡의 namespace를 Kafka 클라이언트 리스너에 허용한다. Spark는 파티션을 직접 지정해서 읽고 Kafka에 처리 위치를 커밋하지 않아 소비자 그룹 권한은 필요 없을 것으로 본다 (실제 접속 때 확인. 그룹 권한 오류가 나면 고정 그룹 이름을 쓰도록 바꾼다). 사용자 인증서 Secret(CA·인증서·키)을 붙이고 `KAFKA_SSL_*` 환경변수로 경로를 준다.
- 환경변수는 위 표 (`KAFKA_SECURITY_PROTOCOL=SSL`).

확인: `python -m pytest -q pipelines/gold_b/tests/test_ingest.py` (설정 파일·형식 검사기 시험은 `PyYAML`이 있어야 돈다).

## 재처리 잡이 하는 일

규칙이나 코드를 고친 뒤 사람이 승인하면, 그 시간대에 Kafka에 들어온 메시지(대상 메시지)를 다시 검사해 **그 메시지들의 옛 결과만 새 결과로 바꾼다** (메시지 단위, 2026-10-23). 평소에는 적재 잡이 원장에 계속 쌓고, 재처리는 기존 결과를 고치기만 한다. 고치는 원장은 ①`payment_events` ②`topic_messages` ④`malformed_events`이고, ③`bronze_lag_snapshots`는 그 시점에만 잴 수 있는 값이라 건드리지 않는다. 설계는 [docs/design/gold-b/README.md](../../../docs/design/gold-b/README.md) 「재실행·재처리 설계와 검증」이다.

1. 승인 범위를 UTC 1시간 폴더로 넓힌다. 끝은 포함하지 않는다 (14:40~16:20 → 14·15·16시).
2. 시작 전에 확인하고, 걸리면 `FAILED`로 끝낸다 (다시 돌려도 소용없어서 재시도하지 않음).
   - 형식 검사 함수의 규칙 버전이 승인된 `rule_version`과 다름
   - 아직 안 끝난 폴더가 있음 (폴더 끝 + 10분이 지나지 않음)
   - Kafka 보관 기간(7일, 2026-10-23 #86으로 72시간에서 늘어남) 밖 → 원본 없음. Bronze에서 다시 읽기는 아직 없다
3. `reprocess_events`에 `STARTED`를 쓴다.
4. 승인 폴더 시간대에 Kafka에 들어온 메시지를 한 번에 다시 읽는다 (시각으로 위치를 찾음). 앞뒤 여유 시간은 더 읽지 않는다.
5. 메시지마다 형식 검사를 하고 새 줄을 만든다. 옛 결과와 새 결과가 있는 시간 폴더는 메시지로 정한다: ②④는 Kafka 시각 폴더, ①은 결제 시각(`completed_at`) 폴더. 결제 시각 폴더는 승인 범위 밖일 수 있다 (예: 다음 날 들어온 결제 수정).
6. 승인 범위 밖 결제 시각 폴더는 결과가 바뀌는 결제가 있을 때만 고친다 (같은 통과 줄이 이미 있으면 건드리지 않음). 그 시간대도 재판정되므로 꼭 필요한 만큼만이다.
7. (가) 검사 결과(①·④)의 새 줄을 폴더마다 파일로 먼저 더한다. 이 뒤에 멈춰도 결과가 사라지지 않는다 (같은 위치에 옛·새 결과가 함께 있으면 뷰가 더 늦게 쌓인 새 결과를 고름). ②는 먼저 더하지 않는다 (유입량이 정리 전까지 늘어 보이지 않게).
8. (나) 시간 순서로 폴더마다 대상 메시지의 옛 줄을 지우고 파일 하나로 정리한 뒤 `LEDGER_REPLACED`를 쓴다.
   - 승인 범위 폴더는 원장 3개를 모두 정리한다. 범위 밖 폴더는 대상 메시지가 있는 원장만 정리하고, detail에 `outside_window`를 넣는다. 판정 잡이 이 줄을 보고 그 시간대를 재판정한다.
   - 지우는 옛 줄: 대상 메시지 위치의 ①·② 줄, ④는 이번 `rule_version` 줄만. 다른 `rule_version`의 ④ 줄과 대상이 아닌 메시지(다시 읽지 못한 메시지 포함)의 줄은 그대로 남는다.
   - 정리한 파일을 먼저 쓰고 옛 파일을 지운다. 그 사이 적재 잡이 새로 쓴 파일은 목록에 없어서 남는다.
9. 도중에 실패하면 `FAILED`를 쓰고 예외를 다시 올린다. 끝난 폴더의 `LEDGER_REPLACED`는 남는다. 다시 돌리면 정리된다.

같은 입력과 같은 규칙으로 다시 돌리면 원장이 같다 (`loaded_at`만 다름). 재처리는 승인 범위 밖 결제 시각 폴더도 고칠 수 있어서 **파일 합치기와 같은 시간에 돌리지 않는다** (DAG에서 하나씩).

## 다음에 돌릴 요청 고르기 (poller)

`next_request(read_events(store), now)`가 `reprocess_events`를 읽어 지금 돌릴 요청 하나를 고른다. Airflow DAG가 5분마다 부른다.

- `APPROVED` 줄의 `source`가 `KAFKA`·`BRONZE`인 요청만 맡는다. `SILVER`(Silver 재처리)는 승인 화면이 Silver DAG를 직접 부른다.
- 아직 시작하지 않은 요청은 승인 뒤 60분 안일 때만 고른다 (승인 화면의 승인 만료와 같은 값).
- 다시 고르는 경우: `FAILED`의 `retryable`이 참일 때, 마지막 `STARTED` 뒤 폴더가 다 끝나지 않은 채 멈췄을 때. 한 요청은 최대 3번(처음 1번 + 자동 재시도 2번)까지 돌린다.
- 한 번에 승인이 가장 이른 요청 하나만 고른다. 몇 번째 실행인지(`run_number`)는 `STARTED`의 `detail.run`에 남는다.
- 승인 화면·판정 잡은 Athena `INSERT`로 줄을 써서 파일 이름에 확장자가 없을 수 있다. 그래서 `read_events`는 숨김·임시 파일이 아니면 다 읽는다.

## `reprocess_events`에 쓰는 줄

`actor`는 `reprocess_job`, `reason`은 비운다. `rule_version`, `attempt`, `parent_request_id`는 요청 값을 그대로 쓴다.

| `step` | `window_start` ~ `window_end` | `source` | `detail` (JSON) |
|---|---|---|---|
| `STARTED` | 승인 범위 | `KAFKA` | 승인 폴더 목록, 몇 번째 실행인지(`run`) |
| `LEDGER_REPLACED` | 정리한 시간 폴더 (예: 15:00 ~ 16:00). 승인 범위 밖 결제 시각 폴더도 | `KAFKA` | 그 폴더의 대상 메시지 수(`messages`), 표별 새 줄 수·남긴 옛 줄 수, 범위 밖이면 `outside_window`, Kafka에 없는 토픽 |
| `FAILED` | 시작 전이면 승인 범위, 도중이면 남은 폴더 범위 | 시작 전이면 비움, 도중이면 `KAFKA` | 실패 이유, 재시도해도 되는지(`retryable`), 끝낸 폴더 수 |

실패 이유에는 이 잡이 만든 문장만 쓰고, Kafka·S3 오류는 종류만 쓴다 (오류 문장에 주소·버킷 이름이 들어 있을 수 있음).

## 부르는 방법

```bash
python -m pipelines.gold_b.jobs.reprocess              # 승인된 요청 하나를 골라 돌린다
python -m pipelines.gold_b.jobs.reprocess --dry-run    # 고른 요청만 알려 주고 돌리지 않는다
```

poller로 요청을 고르고, 형식 검사기(`pipelines/gold_b/format_check.py`)로 원장 줄을 다시 만든다. 할 일이 없거나 성공하면 0, 실패하면 1로 끝난다. 다시 돌릴지와 몇 번까지 돌릴지는 다음 번에 poller가 `reprocess_events`를 보고 정한다. 준비 단계(규칙표, Kafka 설정)에서 실패하면 요청을 실패로 남기지 않고 1로 끝난다 (다음 번에 다시 고름).

| 환경변수 | 뜻 |
|---|---|
| `GOLD_B_LEDGER_ROOT` | 원장 위치: `s3://<버킷>/gold_b` 또는 로컬 폴더 (필수) |
| `KAFKA_BOOTSTRAP` | Kafka 주소 (필수) |
| `KAFKA_SECURITY_PROTOCOL` | `PLAINTEXT`(기본) 또는 `SSL` |
| `KAFKA_SSL_CA_FILE`, `KAFKA_SSL_CERT_FILE`, `KAFKA_SSL_KEY_FILE` | mTLS 파일 경로 |
| `KAFKA_ADDRESS_FAMILY` | 로컬에서 IPv6로 먼저 붙는 문제가 있을 때만 `v4` |
| `GOLD_B_RULES_PATH` | 형식 규칙표 경로 (생략하면 저장소의 `docs/contracts/format_rules.yaml`) |

### Airflow DAG (재영 님께)

DAG는 `infra/platform/airflow/dags/gold_b.py`의 `gold_b_reprocess`다 (2026-10-24, 꺼진 채로 올라감). 실행 설정(`AIRFLOW_GOLD_B_RUNTIME`)과 켜기 전에 준비할 것은 [DAG 설명](../../../infra/platform/airflow/dags/README.md) 「Gold B 재처리·파일 합치기 DAG」에 있다.

- 5분마다(`*/5 * * * *`), `max_active_runs` 1, 밀린 실행을 몰아서 돌리지 않음(`catchup` 끔), 실행 상한 2시간
- 설정 확인 태스크 뒤에 위 명령을 Pod로 실행한다. 다시 돌린 횟수는 poller가 세므로 Airflow 재시도는 0이다 (두면 같은 실행이 바로 다시 돌고 그것도 횟수에 들어감).
- Kafka 인증서 Secret을 `/opt/kafka-tls`에 붙이고 `KAFKA_SECURITY_PROTOCOL=SSL`과 `KAFKA_SSL_*` 경로를 준다.
- 파일 합치기 DAG와 같은 pool에 넣어 같은 시간에 돌지 않는다.
- Pod 권한: S3 `gold_b/payment_events/`·`topic_messages/`·`malformed_events/` 읽기·쓰기·지우기, `gold_b/reprocess_events/` 읽기·쓰기. Kafka 6개 토픽 읽기 (임시 그룹 `gold-b-reprocess-*`, 커밋 없음)
- 이미지: Python 3.10 이상 (팀 기본 Spark 이미지의 3.10.12에서 돈다), `pipelines/gold_b/requirements.txt`, 저장소의 공통 모듈(`pipelines/*.py`. 지문·형식 규칙이 `timestamps.py`를 부른다), `pipelines/gold_b/`, `docs/contracts/format_rules.yaml`

코드에서 부를 때는 이렇게 한다.

```python
from pipelines.gold_b.jobs.reprocess import KafkaReader, next_request, read_events, run
from pipelines.gold_b.ledger import open_store

store = open_store(…)                               # s3://<버킷>/gold_b 또는 로컬 폴더
pending = next_request(read_events(store), now)     # 돌릴 요청이 없으면 None
if pending is not None:
    result = run(
        pending.request,
        source=KafkaReader({"bootstrap.servers": …}),   # 수집기와 같은 KAFKA_* 환경변수로 만든다
        store=store,
        checker=…,                                      # 형식 검사 함수 (rule_version 속성 + 메시지 하나 → 판정)
        run_number=pending.run_number,
    )
    result.replaced   # 실제로 교체한 시간 폴더 [시작, 끝) 목록
```

`checker`는 메시지 하나를 받아 결제 원장의 업무 칼럼(오류 없는 결제만)과 오류 목록만 돌려준다 (`ledger.Judgement`). Kafka 위치·`loaded_at`·`rule_version`은 잡이 붙인다 (`ledger.message_rows`). 적재 잡도 같은 함수를 쓴다.

## 의존하는 것

- 패키지: `confluent-kafka`, `pyarrow`, `boto3` (`pipelines/gold_b/requirements.txt`). Spark는 쓰지 않는다 (한 시간 폴더는 수천 줄).
- Kafka: 대상 토픽 읽기 (임시 그룹으로 `assign`만, 커밋 없음)
- S3: `gold_b/payment_events/`, `gold_b/topic_messages/`, `gold_b/malformed_events/` 읽기·쓰기·지우기, `gold_b/reprocess_events/` 읽기·쓰기

## 확인

```bash
python -m pytest -q pipelines/gold_b/tests/test_reprocess.py
```

가짜 Kafka와 샘플 메시지(`tests/samples/`)로 교체 결과, 두 번 돌린 결과, 남기는 줄, 시작 전 거부, 중간 실패와 다시 돌리기를 확인한다. poller는 승인 순서, `SILVER` 제외, 승인 만료, 거절, 끝남, 다시 돌리기(일시 실패, 중간에 멈춤), 최대 3번, 확장자 없는 Athena 파일 읽기를 확인한다.

## 파일 합치기 (`compact.py`)

적재 잡과 수집기가 1분마다 파일을 하나씩 만들어서 한 시간 폴더에 60개 넘게 쌓인다. 하루 1회, 끝난 UTC 하루의 시간 폴더마다 파일을 하나로 합친다.

1. 그 날 끝 + 10분이 안 지났으면 거부한다.
2. 원장 4개 × 24개 시간 폴더마다, 파일이 2개 이상이면 합친다. `reprocess_events`는 합치지 않는다.
3. **줄은 하나도 빼거나 고치지 않는다** (`loaded_at` 포함). `topic_messages`의 같은 위치 두 줄도 탐지가 보는 신뢰성 신호라서 그대로 둔다.
4. 합친 파일(`part-compact-…`)을 먼저 쓰고 줄 수를 확인한 뒤 원래 파일을 지운다. 합친 파일에는 원래 파일 이름 목록을 적어 둔다. 지우다가 멈춘 뒤 다시 돌리면, 남은 원래 파일은 다시 합치지 않고 지운다 (줄이 두 번 들어가지 않음).
5. 적재 잡이 그 사이 새로 쓴 파일은 목록에 없어서 지워지지 않고, 다음에 합친다.

**재처리 잡과 같은 시간에 돌리면 안 된다.** 재처리는 승인 범위 밖 결제 시각 폴더도 고칠 수 있어서, 폴더와 상관없이 DAG에서 둘을 한 번에 하나씩 돌린다.

```bash
python -m pipelines.gold_b.jobs.compact                    # 어제(UTC)를 합친다
python -m pipelines.gold_b.jobs.compact --day 2026-10-21   # 그 날(UTC)을 합친다
```

환경변수는 `GOLD_B_LEDGER_ROOT`(원장 위치: `s3://<버킷>/gold_b` 또는 로컬 폴더) 하나다. 성공하면 0, 실패하면 1로 끝난다. 그 날이 끝나고 10분이 지나지 않았으면 거부한다.

DAG (재영 님께): `infra/platform/airflow/dags/gold_b.py`의 `gold_b_compact` (2026-10-24, 꺼진 채로 올라감)
- 매일 UTC 00:30 (그 날 끝 + 10분 여유 뒤). 날짜를 주지 않아 어제(UTC)를 합친다. `max_active_runs` 1, `catchup` 끔, Airflow 재시도 2번(10분 간격, 다시 돌려도 결과가 같음)
- 재처리 DAG(`gold_b_reprocess`)와 같은 Airflow pool(실행 설정 `pool`, 슬롯 1개)에 넣어 두 작업이 겹치지 않게 한다. 지금 Airflow는 전체 동시 작업이 1개라 겹치지 않지만, 그 설정이 바뀌어도 막히게 한다.
- Pod 권한: S3 원장 4개 폴더(`payment_events`, `topic_messages`, `bronze_lag_snapshots`, `malformed_events`) 읽기·쓰기·지우기

코드에서 부를 때는 이렇게 한다.

```python
from datetime import date
from pipelines.gold_b.jobs.compact import run
from pipelines.gold_b.ledger import open_store

run(date(2026, 10, 21), store=open_store(…))   # s3://<버킷>/gold_b 또는 로컬 폴더. DAG는 어제(UTC)를 넘긴다
```

S3 권한은 원장 4개 폴더 읽기·쓰기·지우기다. 확인은 `python -m pytest -q pipelines/gold_b/tests/test_compact.py`.
