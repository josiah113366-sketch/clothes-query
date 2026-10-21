# Gold B 설계 (관제용 원장과 정리 뷰)

상태: **결정** (아래 「확정한 결정」). 「팀원과 확인할 것」에서 "필요"인 항목은 미정이다.
원본: 은서 작성 Gold B 기획 (2026-10-21 저장소로 옮김). 이 문서를 옮길 때 사용자와 정한 것과 저장소에서 확인한 것을 반영했다 (「2026-10-21 반영」).

## 개요

Gold B는 Kafka에서 필요한 것만 정제해 **1분마다 원장에 쌓고**, 결제 원장에는 중복 제거·충돌 분리·실패 원인 분류까지 해둔 **정리 뷰**(`gold_b.payment_attempts`)를 얹는다. 구간을 묶어 세고 이상인지 판단하는 일은 6단계(주현 님) 탐지 규칙이 한다.

| 필수 | 내용 | 왜 필수인가 |
| --- | --- | --- |
| ① Gold B 지표 표 | 원장 4개, 재처리 기록 1개, 탐지가 읽는 뷰 3개 (「저장」「탐지가 읽는 것」) | 탐지의 입구 |
| ② 잡 재실행 설계 | 같은 입력이면 원장이 같게, 중복 없이 다시 채우기 (「재실행·재처리 설계와 검증」) | 승인·재처리 시연에 필요 |
| ③ Gold B 재처리 검증 | 재적재 전후 뷰 비교 (「재실행·재처리 설계와 검증」) | 승인·재처리 시연에 필요 |

**왜 원장 + 뷰로 바꿨나**

처음에는 5분 구간을 미리 세서 확정된 구간만 기록하려 했다. 그런데 하루 900주문 규모에서는 결제가 뜸해 구간이 제때 닫히지 않고(하트비트 필요), 늦게 온 결제는 빠져서 재처리로 메워야 했다. 결제 한 건씩 그대로 쌓고 조회할 때 세면 이 문제가 대부분 사라지고, 이 규모에서는 조회 비용도 작다. 주현 님이 원장 기준으로 다시 돌린 결과도 더 좋았다 (가짜 데이터 30회 반복).

**설계 원칙**

- **한 건만 보고 알 수 있는 건 은서, 여러 건을 모아 평소와 비교해야 아는 건 주현 님.** Gold B는 메시지·결제·측정 한 건씩의 사실(형식이 맞나, 실패 원인은 무엇인가, 지금 얼마나 밀렸나)만 기록하고, 구간으로 묶어 세고 판정하는 일은 탐지가 한다.
- **시나리오의 질문에 꼭 필요한 것만 담는다.** 장애의 여파나 피해 규모는 에이전트가 조사할 때 직접 조회한다.
- **가져올 때는 저장할 수 있는 모양으로, 해석은 뷰에서.** 메시지 해석·CDC 표시(`__op`) 읽기·형식 검사는 쌓을 때 하고, 중복 제거·충돌 분리·실패 원인 분류는 뷰에서 한다. 분류 규칙이 바뀌어도 뷰만 고치면 과거까지 다시 분류된다.
- **원장에는 사실을 그대로.** 중복이나 깨진 메시지를 쌓을 때 지우지 않는다. 읽는 쪽이 뷰로 정리한다.
- **원본은 건드리지 않는다.** Kafka와 Bronze는 재처리에서 읽기만 한다. 고치는 대상은 데이터가 아니라 규칙과 코드다.

**확정한 결정**

| 항목 | 결정 |
| --- | --- |
| 적재 방식 | 원장 쌓기(1분마다) + 정리 뷰. 워터마크·구간 닫기·하트비트 없음 |
| 실행 | Gold B 적재 잡은 Spark Structured Streaming(1분 트리거, 체크포인트)으로 상시 실행한다. Bronze 지연 수집기는 별도의 작은 프로그램으로 1분마다 돈다 |
| 입력 | 평소 Kafka만 읽는다. 재처리는 Kafka 보관 기간(3일) 안이면 Kafka, 넘으면 Bronze |
| Bronze 적재 | S3 Sink 커넥터 (성철 님 확정). Bronze 지연은 수집기가 Kafka에 직접 물어서 잰다 |
| 구간 묶기·판정 | 주현 님 탐지 규칙에서 (몇 분 단위로 묶을지, 기준값). 탐지 주기는 **미정** (제안 5분) |
| 판정 가능 구간 | 건수 규칙은 바로 판정, 비율 규칙은 끝난 지 3분 지난 구간만 |
| 저장·조회 | S3 `clothes-query-datalake/gold_b/`, Athena로 조회 (테이블·뷰 정의는 Athena가 Glue 카탈로그 `gold_b`에 저장), 이름에 접두어 없음 |
| 정리 뷰 중복 제거 | 같은 `payment_id`이고 내용도 같으면 가장 먼저 쌓인 줄(`loaded_at`이 가장 이른 줄) 하나만 남긴다 |
| 정리 뷰 충돌 처리 | 같은 `payment_id`인데 내용이 다르면 **그 결제의 모든 줄을 `payment_attempts`에서 빼고** `payment_conflicts` 뷰로 보여 준다. Silver(PR #26)와 공통 계약(`docs/contracts/README.md` 「내용 충돌」)에 맞춘 것 (2026-10-21) |
| 결제 내용 지문 | 내용이 같은지는 **업무 필드 9개**(`order_id`, `attempt_no`, `method`, `pg`, `amount`, `status`, `failure_code`, `requested_at`, `completed_at`)를 정규화한 지문 `payment_content_hash`로 판단한다. 원장에는 지문과 `fingerprint_version` 두 칸만 더하고, `amount`·`method`·`requested_at`은 컬럼으로 두지 않고 지문에만 넣는다. Silver와 Gold B가 같은 함수(`pipelines/payment_fingerprint.py`)로 지문을 만든다. Kafka 위치와 적재 시각은 지문에 넣지 않는다 (현지 님 PR #36 리뷰, 2026-10-21) |
| 결제 필수 필드 | `order_id`, `attempt_no`도 원장에 넣고 형식 검사 필수로 본다 (원천 DDL에서 NOT NULL, 2026-10-21) |
| 컬럼 이름 | Kafka 파티션 번호는 모든 표에서 `kafka_partition` (2026-10-21) |
| 형식 검사 규칙표 | Git의 설정 파일(`format_rules.yaml`)을 Gold B와 Silver가 같이 읽는다 |
| 재처리 | 이벤트 시각 기준 1시간 폴더 단위로 원장 3개를 같이 교체한다. 같은 시간대는 한 번에 하나씩만 돌린다. 일시 실패는 자동 재시도 2번, 원본이 없는 구간은 바로 실패로 멈춘다 |
| 재판정 시작 | 재처리 DAG는 판정을 직접 부르지 않는다. 재처리 잡은 시간 폴더 교체가 끝날 때마다 `reprocess_events`에 `LEDGER_REPLACED`와 실제 교체 범위를 남기고, 주현 님 판정 잡이 정해진 주기마다 이 줄을 읽어 그 시간 폴더를 재판정한다 (#29에 구현, 인프라 문서와 같음). 확인 주기는 **미정** (제안 5분, 판정 주기와 같음) (2026-10-21 결정) |
| 판정 실행 | 주현 님 별도 잡. Gold B는 원장과 정리 뷰까지 |
| 코드 위치·브랜치 | `pipelines/gold_b/`, 브랜치 `pipelines/gold-b`, 커밋 `pipelines(gold-b): …` (Silver와 같은 방식, 2026-10-21) |
| 뺀 것 | 5분 집계 뷰, 주문 단위 지표, `ALL` 행, `is_final`, `retry_attempts` |

## 2026-10-21 반영

**사용자와 정한 것:** 위 결정 표의 "2026-10-21" 항목 (충돌 처리, 결제 내용 지문, 결제 필수 필드, `kafka_partition`, 코드 위치), `order-items`의 `unit_price ≥ 5,900`.

**저장소에서 확인한 실제 모양** (`connectors/cdc-source.yaml`, `connectors/bronze-s3-sink.yaml`, `review-simulator/README.md`). 기획 원문과 다른 곳은 아래 기준으로 고쳤다.

| 항목 | 기획 원문 | 실제 | 이 문서에서 |
| --- | --- | --- | --- |
| CDC 메시지 모양 | Debezium 봉투의 `after.payment_id` | `ExtractNewRecordState`로 봉투가 풀려 **컬럼이 맨 위에 평평하게** 오고 `__op`, `__source_ts_ms`, `__source_snapshot`이 붙는다. 삭제(`d`)는 토픽에 오지 않는다 | `after.` 대신 맨 위 필드, `op` 대신 `__op` |
| 회원 토픽 | `member-events` | `members-events` | `members-events` |
| 시각 값 | - | JSON 문자열 (CDC는 Debezium이 `timestamptz`를 UTC ISO 문자열로, 클릭은 시간대가 있는 ISO 문자열) | 형식 검사에서 시간대가 있는 ISO 문자열만 통과 |
| Bronze 파일 전환 주기 | 성철 님께 확인 | `rotate.schedule.interval.ms = 900000` (15분), `flush.size = 10000` | 정상 지연 기준선 후보는 15분. 성철 님 확인은 유지 |
| S3 Sink 커넥터 이름 | 성철 님께 확인 | `bronze-s3-sink` (Strimzi `KafkaConnector`, 네임스페이스 `kafka`). 소비자 그룹은 Connect 기본 규칙상 `connect-bronze-s3-sink`로 예상 | 수집기 단계에서 실제 그룹 이름 확인 |
| Bronze 대상 토픽 | 6개 | 5개 (`clickstream`, `members-events`, `orders`, `order-items`, `payments`). `reviews.raw`는 없음 | 아래 「입력」 참고 |
| Bronze의 Kafka 위치 | 성철 님께 확인 | 파일에는 메시지 값만 있다. 파일 이름에 파티션과 시작 offset만 있음 (`<토픽>+<파티션>+<시작offset>.json`) | 3일이 지난 구간을 Bronze로 재처리하는 방법은 7단계 전에 정함 |
| 오류 토픽(DLQ) | 성철 님께 확인 | S3 Sink에 `errors.tolerance`·DLQ 설정 없음 | 성철 님 확인 유지 |
| 리뷰 | `reviews.raw` 토픽 | 운영 흐름은 리뷰 시뮬레이터가 S3 `bronze/reviews/`에 바로 쓴다. `reviews.raw`는 실험용 토픽 | 대상 토픽 목록(설정값)에 넣되, 운영에서 비어 있을 수 있음. 민혁 님 확인 |
| 형식 규칙 파일 | `common/format_rules.yaml` | `docs/contracts/format_rules.yaml`과 읽는 코드 `pipelines/format_rules.py`가 PR #26으로 머지됨 (주문·주문상품·결제만, Silver가 읽음) | 2단계에서 이 파일을 같이 쓰는 방법을 현지 님과 정함 |
| 재판정 연결 | Airflow에서 재처리 → 재판정 이어 붙임 | `docs/design/infra/team-inputs.md`는 "재처리 DAG에서 판정 DAG를 직접 호출하지 않음, 5분 판정 작업이 `reprocess_events`를 읽음"으로 적혀 있음 | 판정 잡이 `reprocess_events`를 읽는 방식으로 통일 (인프라 문서·#29와 같음, 2026-10-21). 확인 주기는 미정 |

## 역할 경계와 전체 흐름

Gold B는 **한 건씩의 사실을 기록**하는 데까지다. 주현 님 탐지 잡이 원장과 뷰를 읽어서 묶어 세고 판정한다.

| 단계 | 담당 | 언제 | 하는 일 | 결과 |
| --- | --- | --- | --- | --- |
| 쌓기 | 은서 (Gold B 적재 잡, Spark Structured Streaming) | 1분마다, 상시 | Kafka 6개 토픽을 읽어 정제·형식 검사 후 원장에 추가 | `payment_events`, `topic_messages`, `malformed_events` |
| 지연 측정 | 은서 (Bronze 지연 수집기) | 1분마다, 상시 | Bronze 적재가 얼마나 밀렸는지 측정 | `bronze_lag_snapshots` |
| 정리 뷰 | 은서 | 처음에 한 번 정의 | 중복 제거·충돌 분리·실패 원인 분류, 깨진 메시지 단위 정리를 뷰로 정의 | `payment_attempts`, `payment_conflicts`, `malformed_messages` |
| 묶어 세기·판정 | 주현 (탐지 잡, 별도) | 정해진 주기마다 (미정, 제안 5분) | 원장·뷰를 구간으로 묶어 세고 기준과 비교 | `gold_b.anomaly` |
| 조사 | 주현 (에이전트) | 이상이 잡힐 때 | 원장·뷰를 증거로 원인을 추정하고 근거와 함께 리포트 | 원인 리포트 |
| 수정 | 원인에 따라 다름 (「원인별 고칠 사람」) | 리포트 뒤 | 규칙표·코드·시뮬레이터를 고침 | 새 규칙 버전 등 |
| 승인 | 주현 (승인 화면) | 고친 뒤 | 재처리 범위와 규칙 버전을 확인하고 승인 | `reprocess_events` |
| 재처리 교체 | 은서 (재처리 잡, Airflow가 실행) | 승인된 때만 | 원장의 해당 시간 폴더를 지우고 다시 채움 | 원장 교체, `reprocess_events` |
| 재판정 | 주현 (판정 잡) | `LEDGER_REPLACED`를 본 뒤 (다음 판정 주기) | 교체된 시간대를 다시 판정 | `anomaly`, `reprocess_events` |

1. Gold B 적재 잡이 1분마다 Kafka에서 새 메시지를 읽어 원장에 쌓는다. 세지 않고 한 줄씩 추가만 한다.
2. 수집기가 1분마다 Bronze 적재의 밀린 정도를 측정해 원장에 쌓는다.
3. 탐지 잡이 원장과 뷰를 조회해, 탐지 규칙에서 정한 구간(예: 5분)으로 묶어 센다.
4. 탐지가 이상을 `anomaly`에 기록하고, 에이전트가 원장과 뷰를 조회해 원인을 찾는다.
5. 사람이 원인을 고치고 승인하면, 재처리 잡이 원장을 다시 채우고 `reprocess_events`에 `LEDGER_REPLACED`를 남긴다. 판정 잡이 다음 주기에 그 줄을 보고 재판정한다.

- 계속 도는 것(적재 잡, 수집기)은 EKS에 상시로 띄우고, 가끔 도는 것(재처리, 파일 합치기)은 Airflow가 실행한다. 재판정은 주현 님 판정 잡이 하므로 Airflow로 잇지 않는다.
- **Bronze (성철 님):** Kafka → S3 적재 (S3 Sink). Gold B는 평소 Bronze 파일을 읽지 않는다.
- **Silver (현지 님과 공동):** CDC 표시 읽기와 형식 검사 규칙을 공통으로 쓴다.
- 판정이 별도 잡이라, 규칙에서 오류가 나도 Gold B 원장 쌓기는 멈추지 않는다.

## 시나리오별 질문

세 시나리오의 질문은 모두 **사람이 아니라 시스템**을 향한다. 그래서 Gold B는 고객·주문 단위가 아니라 PG별, 토픽별로 숫자를 나눈다.

| 시나리오 | 질문 | 그렇다고 말하려면 확인할 것 | 주로 읽는 것 |
| --- | --- | --- | --- |
| 1. PG 장애 | 특정 PG에 장애가 생겨 결제가 실패하고 있는가? | 실패가 늘었다 · 원인이 PG 쪽이다 · 한 PG에 몰렸다 | `payment_attempts` |
| 2. 트래픽 폭주 | 들어오는 데이터를 파이프라인이 제때 처리하지 못하고 밀리는가? | 처리가 늦어졌다 · 들어오는 양이 늘었다 · 데이터는 깨지지 않았다 | `bronze_lag_snapshots`, `topic_messages` |
| 3. 스키마 오염 | 들어오는 데이터의 형식이 깨졌는가? 어디서, 언제부터인가? | 형식 오류가 늘었다 · 한 토픽·한 사유로 몰렸다 · 특정 시점부터 시작됐다 · 들어오는 양은 그대로다 | `malformed_messages`, `malformed_events`, `topic_messages` |

- 시나리오 1에서 한 사람이 여러 번 실패했는지, 여러 사람이 실패했는지는 이 질문에 필요 없다. PG 원인 실패는 그때마다 PG가 실패했다는 기록이고, 고객 사정은 고객 원인 실패로 이미 걸러진다. 고객 피해 규모는 에이전트가 리포트를 쓸 때 센다.
- 시나리오 2에서 유입은 그대로인데 지연만 커졌다면 폭주가 아니라 Bronze 적재 자체의 문제다.
- 시나리오마다 주로 보는 표가 하나씩 있고, 나머지는 "다른 원인이 아니다"를 확인하는 보조용이다.

| 시나리오 | 주로 보는 것 | 다른 원인 지우려고 보는 것 |
| --- | --- | --- |
| 1. PG 장애 | `payment_attempts` | `payment_conflicts`, `malformed_messages`, `bronze_lag_snapshots` |
| 2. 트래픽 폭주 | `bronze_lag_snapshots` | `topic_messages`, `malformed_messages` |
| 3. 스키마 오염 | `malformed_messages`, `malformed_events` | `topic_messages`, `bronze_lag_snapshots` |

## 입력

Gold B는 평소 **Kafka만 읽는다.** Bronze(S3 파일)는 평소 읽지 않아서, Bronze가 밀리거나 멈춰도 관제는 계속 돈다.

**Kafka 데이터 토픽 6개** (대상 목록은 설정값)

| 토픽 | 보내는 쪽 | 시나리오 1 (메시지 내용) | 시나리오 2 (개수·시각) | 시나리오 3 (형식 검사) |
| --- | --- | --- | --- | --- |
| `payments` | Debezium (CDC) | `payment_id`, `order_id`, `attempt_no`, `pg`, `status`, `failure_code`, `completed_at` | 유입량 | 형식 검사 |
| `orders` | Debezium (CDC) |  | 유입량 | 형식 검사 |
| `order-items` | Debezium (CDC) |  | 유입량 | 형식 검사 |
| `members-events` | Debezium (CDC) |  | 유입량 | 형식 검사 |
| `clickstream` | 시뮬레이터 직접 (키 = `session_id`) |  | 유입량 | 형식 검사 (주입 대상 후보) |
| `reviews.raw` | 리뷰 시뮬레이터 (실험용, 운영에서는 비어 있을 수 있음) |  | 유입량 | 형식 검사 |

CDC 토픽 메시지는 봉투가 풀린 평평한 JSON이다. 예 (`payments`):

```json
{"payment_id": "…uuid…", "order_id": "…uuid…", "attempt_no": 1, "method": "CARD", "pg": "PG_A",
 "amount": 39000, "status": "FAILED", "failure_code": "PG_TIMEOUT",
 "requested_at": "2026-10-21T06:01:18Z", "completed_at": "2026-10-21T06:01:20Z",
 "__op": "c", "__source_ts_ms": 1792562480000, "__source_snapshot": "false"}
```

Kafka에서 메시지를 읽을 때 모든 메시지에 위치와 시각(`topic`, `partition`, `offset`, `timestamp`)이 같이 따라온다. 위치는 메시지 하나를 정확히 가리키는 주소(토픽 → 파티션 → 몇 번째 메시지)다. 이 값을 어느 표에 저장하는지는 표마다 다르다.

**Bronze 지연 정보 (시나리오 2)**

Bronze는 S3 Sink 커넥터로 쌓는다. S3 Sink는 상태 보고를 보내지 않으므로, **Bronze 지연 수집기**가 1분마다 Kafka 관리 API와 Kafka Connect REST에 직접 묻는다: 커넥터가 어디까지 처리했는지(소비자 그룹 오프셋), 마지막 메시지 위치, 커넥터 상태. S3 Sink는 파일을 쓴 뒤에 처리 위치를 기록하므로, 정상일 때도 파일 전환 주기(현재 15분)만큼은 밀려 보인다. 이 주기를 지연 기준선으로 쓴다. 이 방식은 주문 설계의 "consumer lag 수집기는 두지 않는다"는 결정과 달라지므로 팀에 공유한다.

## 저장: 원장 4개 + 재처리 기록 1개

원장은 **있었던 일을 한 줄씩 그대로 쌓는 장부**다. 세거나 고치지 않고 추가만 한다. S3 `gold_b/` 아래에 이벤트 시각(UTC) 기준 **시간 폴더**(`dt=YYYY-MM-DD/hour=HH`)로 Parquet 파일을 쌓고, Athena에서 테이블로 등록한다 (정의는 Glue 카탈로그 `gold_b`에 저장). 새 날짜·시간 폴더를 바로 읽을 수 있게 Athena 파티션 프로젝션을 설정한다. 1분마다 쌓아 작은 파일이 많이 생기므로 하루 1회 시간 폴더 안의 파일을 합친다 (Airflow).

```
s3://clothes-query-datalake/gold_b/
  payment_events/         ①  (결제는 completed_at 기준 시간 폴더)
  topic_messages/         ②  (kafka_timestamp 기준)
  bronze_lag_snapshots/   ③  (collected_at 기준)
  malformed_events/       ④  (kafka_timestamp 기준)
  reprocess_events/       ⑤  (재처리 기록, 시간 폴더 없음)
```

시간 폴더를 이벤트 시각으로 나누는 이유는 재처리 때 "15시대를 다시 채운다"가 그 폴더 하나를 바꾸는 일이 되게 하기 위해서다. 테이블 정의는 `pipelines/gold_b/ddl/`에 있다.

### ① `payment_events` - 결제 시도 한 건 = 한 줄

`payments` 토픽에서 형식 검사를 통과하고 `__op`가 `c`(새 결제) 또는 `r`(Debezium 시작 전부터 있던 결제, 예: 백필)인 메시지만. 같은 결제가 스냅샷으로 다시 와도 정리 뷰에서 `payment_id`로 걸러진다. 성공·고객 원인 실패·PG 원인 실패를 **모두** 쌓는다 (성공이 있어야 시도 수를, 고객 원인 실패가 있어야 비교 기준을 셀 수 있다).

| 컬럼 | 타입 | 가져오는 곳 | 의미 | 예시 |
| --- | --- | --- | --- | --- |
| `payment_id` | STRING | `payment_id` | 결제 시도 한 번의 고유 번호. 시도마다 새로 붙음. 중복 제거 기준 | `p-01` |
| `order_id` | STRING | `order_id` (필수) | 이 결제가 어느 주문에 대한 것인지. 재시도해도 같은 값. 에이전트가 최근 장애의 재시도·피해를 바로 볼 때 | `o-5` |
| `attempt_no` | INT | `attempt_no` (필수) | 그 주문에서 몇 번째 시도인지. 1이 첫 시도, 2 이상이 재시도 | `1` |
| `pg` | STRING | `pg` | 결제를 처리한 결제대행사. `PG_A`, `PG_B` 중 하나 | `PG_A` |
| `status` | STRING | `status` | 이 시도 한 번의 결과. `SUCCESS`, `FAILED` 중 하나 | `FAILED` |
| `failure_code` | STRING, NULL 허용 | `failure_code` | 실패했다면 그 이유. 성공이면 NULL | `PG_TIMEOUT` |
| `completed_at` | TIMESTAMP | `completed_at` | 결제 결과가 확정된 시각 (UTC). 탐지가 구간을 묶을 때 기준 | 15:01:20 |
| `payment_content_hash` | STRING | 업무 필드 9개로 계산 | 결제 내용 지문. 같은 `payment_id`인데 지문이 다르면 내용 충돌. `amount`·`method`·`requested_at`은 컬럼 없이 여기에만 들어간다 | `9f2c…` |
| `fingerprint_version` | STRING | 지문 함수 | 지문 규칙 버전. 버전이 같은 줄끼리만 지문을 비교한다 | (현지 님과 정함) |
| `kafka_partition` | INT | Kafka 위치 | 이 메시지가 `payments` 토픽의 몇 번 파티션에 있었는지 (추적용) | `0` |
| `kafka_offset` | BIGINT | Kafka 위치 | 그 파티션 안에서 몇 번째 메시지였는지 (추적용) | `17920` |
| `loaded_at` | TIMESTAMP | 원장에 쌓은 시각 | 그때 탐지가 본 숫자를 재현할 때 씀 | 15:02:00 |

실패 원인 분류(PG / 고객 / unknown), 중복 제거, 충돌 분리는 원장에 하지 않고 정리 뷰에서 한다.

지문은 형식 검사를 통과한 결제를 쌓을 때 계산한다. 지문 규칙(필드 순서, 시각·NULL·숫자 정규화, 직렬화, 해시 알고리즘)은 공통 모듈 `pipelines/payment_fingerprint.py`에서 현지 님과 정한다 (**미정**, 2단계).

### ② `topic_messages` - 메시지 하나 = 한 줄 (6개 토픽 전부)

메시지 내용은 담지 않고 "언제 어떤 토픽에 메시지가 왔나"만 담는다. 형식 검사 결과와 상관없이 모든 메시지를 쌓는다. 형식 오류 여부는 여기 두지 않고 ④에서만 본다 (규칙 버전이 바뀌어도 두 곳이 서로 다른 말을 하지 않게). 모든 메시지가 들어 있는 유일한 표라 신뢰성 점검(오프셋 빈틈, 중복)도 이 표로 한다.

| 컬럼 | 타입 | 가져오는 곳 | 예시 |
| --- | --- | --- | --- |
| `topic` | STRING | Kafka 정보 | `clickstream` |
| `kafka_partition`, `kafka_offset` | INT, BIGINT | Kafka 정보 | `2`, `18342` |
| `kafka_timestamp` | TIMESTAMP | Kafka 정보 | 15:03:11 |
| `loaded_at` | TIMESTAMP | 원장에 쌓은 시각 | 15:04:00 |

### ③ `bronze_lag_snapshots` - 1분 × 토픽 × 파티션 = 한 줄

| 컬럼 | 타입 | 가져오는 곳 | 예시 |
| --- | --- | --- | --- |
| `collected_at` | TIMESTAMP | 측정 시각 | 15:05:00 |
| `topic`, `kafka_partition` | STRING, INT | S3 Sink 소비자 그룹의 대상 | `payments`, `0` |
| `end_offset` | BIGINT | Kafka 관리 API: 마지막 메시지 위치 | `10500` |
| `committed_offset` | BIGINT | Kafka 관리 API: S3 Sink가 처리한 위치 | `10200` |
| `lag_msgs` | BIGINT | 위 둘의 차이 (밀린 메시지 수) | `300` |
| `lag_sec` | DOUBLE | 처리 안 된 가장 오래된 메시지의 Kafka 시각과 측정 시각의 차이 | `170` |
| `connector_state` | STRING | Kafka Connect REST | `RUNNING` |

수집기는 Gold B 적재 잡과 따로 돈다 (EKS에서 1분마다). 데이터가 없어도 돌아야 Bronze 멈춤을 잡을 수 있기 때문이다. 토픽별·파티션별로 쌓고, 전체 값이 필요하면 밀린 개수는 합, 밀린 시간은 최댓값으로 본다. 과거 측정값이라 재처리해도 다시 만들지 않는다.

### ④ `malformed_events` - 오류 하나 = 한 줄 (한 메시지에 오류가 여러 개면 여러 줄)

| 컬럼 | 타입 | 뜻 | 예시 |
| --- | --- | --- | --- |
| `topic` | STRING | 토픽 | `clickstream` |
| `kafka_partition`, `kafka_offset` | INT, BIGINT | Kafka 위치 (재처리 시작 위치) | `2`, `18342` |
| `kafka_timestamp` | TIMESTAMP | Kafka 기록 시각 (오염 시작 시점) | 15:03:11 |
| `field` | STRING | 문제가 난 필드 하나 | `session_id` |
| `reason` | STRING | **그 필드의** 오류 사유 | `MISSING_FIELD` |
| `raw_sample` | STRING, NULL 허용 | 마스킹한 원문 일부. 같은 메시지의 첫 줄에만 넣고 나머지는 NULL | `{"event_id":"e7c1…","sessionId":"***"…` |
| `rule_version` | STRING | 적용한 규칙표 버전 | `v1.0` |
| `loaded_at` | TIMESTAMP | 원장에 쌓은 시각 | 15:04:00 |

- **오류 하나당 한 행**이다. 한 메시지에 `session_id` 누락과 `article_id` 타입 오류가 함께 있으면 2행이다.
- 같은 Kafka 메시지에 대해 `(topic, kafka_partition, kafka_offset, rule_version, field)`가 같은 오류는 한 번만 적재한다.
- 규칙 버전 이력을 보존한다. 규칙이 바뀌면 새 `rule_version`의 결과를 추가하고 예전 판정도 남긴다.
- `raw_sample`은 최소화하고, **필드 이름은 남기고 값만 가린다.** 필드 이름이 남아야 에이전트가 이름이 바뀐 건지, 값이 빠진 건지 가릴 수 있다. 리뷰 본문·회원 관련 값은 마스킹하거나 뺀다. 조회 권한은 데이터 부서로 제한한다.
- 메시지 전체를 해석하지 못한 경우(`PARSE_ERROR`)는 `field`를 `__message__`로 쓴다.
- 오류마다 줄이 생기므로 `COUNT(*)`로 세면 깨진 메시지 수가 부풀어 보인다. 메시지 수는 아래 `malformed_messages` 뷰로 센다.

### ⑤ `reprocess_events` - 재처리 단계 하나 = 한 줄 (은서 + 주현 공동)

재처리가 누구 승인으로, 언제, 어느 시간대에, 어디까지 진행됐는지 남기는 기록이다. 줄을 고치지 않고 단계마다 새 줄을 쌓는다 (원장과 같은 "추가만" 방식). 현재 상태는 **마지막 줄의 `step`**으로 정한다. 표 정의는 은서가 원장 테이블과 함께 만들고, 최종 컬럼 목록을 주현 님께 공유한다. 양이 적어 시간 폴더로 나누지 않는다.

| `step` | 쓰는 사람 | 뜻 |
| --- | --- | --- |
| `REQUESTED` | 주현 (승인 화면) | 재처리 요청 (승인 범위) |
| `APPROVED` / `REJECTED` | 주현 (승인 화면) | 사람이 승인 또는 거절 |
| `STARTED` | 은서 (재처리 잡) | 교체 시작 |
| `LEDGER_REPLACED` | 은서 (재처리 잡) | 시간 폴더 하나 교체 끝 (**실제 교체 범위**) |
| `FAILED` | 은서 (재처리 잡) | 실패 (`detail`에 이유) |
| `REDETECTED` | 주현 (판정 잡) | 교체된 시간 폴더 재판정 끝 |
| `VERIFIED` | 주현 (판정 잡) | 해결 / 미해결 확인 |

| 컬럼 | 타입 | 뜻 | 채우는 사람 |
| --- | --- | --- | --- |
| `request_id` | STRING | 요청 번호 | 각 단계를 쓰는 사람 |
| `step` | STRING | 단계 (위 표) | 각 단계를 쓰는 사람 |
| `at` | TIMESTAMP | 이 단계를 기록한 시각 (UTC) | 각 단계를 쓰는 사람 |
| `actor` | STRING | 누가 (사람 이름 대신 역할·잡 이름) | 각 단계를 쓰는 사람 |
| `reason` | STRING | 왜 | 각 단계를 쓰는 사람 |
| `window_start`, `window_end` | TIMESTAMP | 이 줄이 가리키는 시간대. `REQUESTED`는 승인 범위, `LEDGER_REPLACED`는 실제 교체한 시간 폴더 | 각 단계를 쓰는 사람 |
| `rule_version` | STRING | 다시 계산에 쓴 형식 검사 규칙 버전 | 은서 (승인 때 주현 님도 함께 적으면 맞춰 보기 좋음) |
| `source` | STRING | 다시 읽은 곳 (`KAFKA` / `BRONZE`) | 은서 |
| `attempt` | INT | 몇 번째 시도 | 각 단계를 쓰는 사람 |
| `parent_request_id` | STRING | 이전 요청 (재시도 추적) | 각 단계를 쓰는 사람 |
| `detail` | STRING | 실패 이유, 교체한 폴더 목록 같은 짧은 설명 | 은서 |

- **시간 폴더 하나 교체가 끝날 때마다** `LEDGER_REPLACED`를 한 줄씩 쓴다. 14:40~16:20을 승인하면 14·15·16시 폴더마다 한 줄이다. 중간에 실패해도 끝난 폴더는 재판정할 수 있고, 남은 폴더는 `FAILED`로 남는다. `REDETECTED`도 폴더마다 한 줄씩 쓴다.
- `LEDGER_REPLACED`는 그 폴더의 교체가 **모두 끝난 뒤** 쓴다.
- 판정 잡이 이 표의 `LEDGER_REPLACED` 줄을 보고 재판정을 시작한다. 그래서 이 표는 누가 언제 어느 범위를 바꿨는지 남기는 기록이면서, 재판정을 시작시키는 신호다.
- 재처리는 항상 원장 3개를 같이 교체하므로 표 이름은 기록하지 않는다. 한 시간 폴더는 몇 초~1~2분이면 다시 채워진다.

## 탐지가 읽는 것

탐지는 Athena로 원장과 뷰를 읽는다. 구간으로 묶어 세는 일은 탐지 규칙이 정한다. 뷰는 데이터가 아니라 **원장을 읽을 때마다 정리해서 보여주는 SQL**이다. `CREATE VIEW`를 Athena에서 실행하면 Glue 카탈로그에 저장되고, 같은 SQL을 Git에도 파일로 남긴다 (`pipelines/gold_b/views/`, 3단계). 탐지·에이전트는 뷰 이름으로 조회만 하고, 정리 SQL은 Athena가 조회할 때마다 자동으로 실행한다.

### 정리 뷰 `payment_conflicts` - 내용이 충돌한 결제 하나 = 한 줄 (시나리오 1 보조)

같은 `payment_id`인데 결제 내용 지문(`payment_content_hash`)이 다른 결제를 모은다. 결제 내용은 수정하지 않는다는 데이터 계약을 어긴 것이라 원래 0건이어야 한다. Silver도 같은 지문 함수로 같은 경우를 `CONTENT_CONFLICT`로 격리한다.

```sql
CREATE OR REPLACE VIEW gold_b.payment_conflicts AS
WITH grouped AS (
  SELECT payment_id, fingerprint_version,
         COUNT(*)                         AS row_count,
         filter(ARRAY[
           IF(COUNT(DISTINCT order_id) > 1,                  'order_id'),
           IF(COUNT(DISTINCT attempt_no) > 1,                'attempt_no'),
           IF(COUNT(DISTINCT pg) > 1,                        'pg'),
           IF(COUNT(DISTINCT status) > 1,                    'status'),
           IF(COUNT(DISTINCT coalesce(failure_code, '')) > 1, 'failure_code'),
           IF(COUNT(DISTINCT completed_at) > 1,              'completed_at')
         ], x -> x IS NOT NULL)          AS stored_fields,
         ARRAY_AGG(DISTINCT pg)           AS pgs,
         MIN(completed_at)                AS first_completed_at,
         MIN(loaded_at)                   AS first_loaded_at,
         MAX(loaded_at)                   AS last_loaded_at,
         ARRAY_AGG(CAST(ROW(kafka_partition, kafka_offset)
                   AS ROW(kafka_partition INTEGER, kafka_offset BIGINT))) AS sources
  FROM gold_b.payment_events
  GROUP BY payment_id, fingerprint_version          -- 지문 버전이 같은 줄끼리만 비교
  HAVING COUNT(DISTINCT payment_content_hash) > 1
)
SELECT payment_id, fingerprint_version, row_count,
       IF(cardinality(stored_fields) = 0, ARRAY['payment_content_hash'], stored_fields) AS conflict_fields,
       pgs, first_completed_at, first_loaded_at, last_loaded_at, sources
FROM grouped;
```

| 컬럼 | 뜻 | 예시 |
| --- | --- | --- |
| `payment_id` | 충돌한 결제 시도 번호 | `p-07` |
| `fingerprint_version` | 비교한 지문 규칙 버전 | (현지 님과 정함) |
| `row_count` | 원장에 쌓인 줄 수 | `2` |
| `conflict_fields` | 원장에 저장된 업무 필드 6개 중 값이 다른 것. 6개가 모두 같은데 지문만 다르면 `[payment_content_hash]` (금액·결제 수단·요청 시각 중 하나 이상이 다르다는 뜻. 무엇이 다른지는 `sources`로 원본을 봐야 안다) | `[status, failure_code]`, `[payment_content_hash]` |
| `pgs` | 그 결제에 나온 PG (영향 범위 확인용) | `[PG_A]` |
| `first_completed_at` | 가장 이른 결제 결과 시각 (어느 구간에 영향이 있나) | 15:01:20 |
| `first_loaded_at`, `last_loaded_at` | 처음·마지막으로 쌓인 시각 | 15:02:00, 15:05:00 |
| `sources` | 원본 Kafka 위치 목록 (원본 다시 찾기) | `[{0, 17920}, {0, 17988}]` |

- 원문 값은 넣지 않고 결제 키·원본 위치·충돌 필드명만 남긴다 (공통 계약과 같음).
- 지문 버전이 다른 줄끼리는 비교하지 않는다. 규칙이 다르면 같은 내용도 지문이 달라져 가짜 충돌이 생기기 때문이다. 지문 규칙을 바꾸면 지난 시간 폴더를 재처리해 지문을 다시 만든다 (같은 결제의 중복은 `completed_at`이 같아 같은 시간 폴더에 있으므로 함께 다시 계산된다).
- 탐지는 이 뷰에 줄이 있는 구간을 "확인 필요"로 볼 수 있다. 충돌한 결제는 `payment_attempts`에서 빠지므로 그 구간의 결제 수가 실제보다 적을 수 있다.

### 정리 뷰 `payment_attempts` - 결제 시도 한 건 = 한 줄 (시나리오 1)

① `payment_events`에서 이렇게 정리한다.

- `payment_conflicts`에 있는 `payment_id`는 **모든 줄을 뺀다.** 어느 줄이 맞는지 판단할 수 없는 결제를 정상으로 세지 않는다.
- 남은 결제 중 `payment_id`가 같은 줄은 **가장 먼저 쌓인 줄**(`loaded_at`이 가장 이른 줄) 하나만 남긴다 (Debezium 재시작·전송 재시도로 생긴 중복). 내용이 같으므로 값은 같고, 처음 쌓인 시각이 남는다. 실제 재시도는 `payment_id`가 달라서 그대로 남는다.
- `failure_code`로 실패 원인을 붙인다: `PG_TIMEOUT`, `PG_ERROR` → `PG` / `INSUFFICIENT_BALANCE`, `CARD_LIMIT_EXCEEDED`, `CARD_DECLINED` → `CUSTOMER` / 그 외이거나 코드가 비어 있는 실패 → `UNKNOWN`.

```sql
CREATE OR REPLACE VIEW gold_b.payment_attempts AS
SELECT payment_id, order_id, attempt_no, pg, status, failure_code,
       CASE
         WHEN failure_code IN ('PG_TIMEOUT','PG_ERROR') THEN 'PG'
         WHEN failure_code IN ('INSUFFICIENT_BALANCE','CARD_LIMIT_EXCEEDED','CARD_DECLINED') THEN 'CUSTOMER'
         WHEN status = 'FAILED' THEN 'UNKNOWN'
       END AS failure_cause,
       completed_at, loaded_at
FROM (
  SELECT e.*, ROW_NUMBER() OVER (PARTITION BY payment_id
                                 ORDER BY loaded_at, kafka_partition, kafka_offset) AS rn
  FROM gold_b.payment_events e
  WHERE NOT EXISTS (SELECT 1 FROM gold_b.payment_conflicts c WHERE c.payment_id = e.payment_id)
)
WHERE rn = 1;
```

| 컬럼 | 뜻 | 예시 |
| --- | --- | --- |
| `payment_id` | 결제 시도 번호 | `p-01` |
| `order_id`, `attempt_no` | 주문 번호, 몇 번째 시도 | `o-5`, `1` |
| `pg` | 결제대행사 | `PG_A` |
| `status` | `SUCCESS` / `FAILED` | `FAILED` |
| `failure_code` | 원래 실패 코드 (원인을 더 좁힐 때) | `PG_TIMEOUT` |
| `failure_cause` | 실패 원인 분류 | `PG` |
| `completed_at` | 결제 결과 시각 | 15:01:20 |
| `loaded_at` | 원장에 처음 쌓인 시각 (중복이면 이른 쪽) | 15:02:00 |

### 정리 뷰 `malformed_messages` - 깨진 메시지 하나 = 한 줄 (시나리오 3)

④ `malformed_events`를 메시지 단위로 묶어 준다 (규칙 버전별). 한 줄에 그 메시지의 오류 개수와 **필드·사유 쌍 전부**가 들어 있어서, 탐지는 "몇 건 깨졌나"를, 에이전트는 "어느 필드가 어떤 사유로 틀렸나"를 이 뷰에서 바로 본다. 사유별·필드별로 오류 개수를 세야 할 때만 ④를 직접 읽는다.

```sql
CREATE OR REPLACE VIEW gold_b.malformed_messages AS
SELECT topic, kafka_partition, kafka_offset, rule_version,
       MIN(kafka_timestamp)        AS kafka_timestamp,
       COUNT(DISTINCT field)       AS error_count,
       ARRAY_AGG(CAST(ROW(field, reason) AS ROW(field VARCHAR, reason VARCHAR))) AS errors,
       MIN(loaded_at)              AS loaded_at
FROM gold_b.malformed_events
GROUP BY topic, kafka_partition, kafka_offset, rule_version;
```

| kafka_offset | error_count | errors |
| --- | --- | --- |
| 5230 | 3 | `[{pg, INVALID_VALUE}, {failure_code, MISSING_FIELD}, {completed_at, TYPE_MISMATCH}]` |

깨진 메시지 수를 셀 때는 **현재 `rule_version`의 줄만** 센다. 규칙 버전이 섞이면 같은 메시지가 중복으로 세어진다. `ARRAY_AGG(CAST(ROW(...)))`, `filter(ARRAY[…])` 문법은 Athena에서 처음 만들 때 한 번 돌려서 확인한다.

### 원장을 그대로 읽는 것 (시나리오 2, 3)

| 원장 | 탐지·에이전트가 보는 것 (예) |
| --- | --- |
| `topic_messages` | 토픽별 유입량 (`kafka_timestamp`로 묶기) |
| `bronze_lag_snapshots` | 밀린 메시지 수·시간 최댓값, `committed_offset`이 멈췄는지, `connector_state` |
| `malformed_events` | 어느 필드가 왜 틀렸나, 오염 시작 시점(가장 이른 `kafka_timestamp`), 파티션별 가장 이른 `kafka_offset`(재처리 시작 위치, `anomaly`의 `evidence_ref`), `raw_sample`로 본 실제 메시지 모양 |

유입량은 Kafka 기록 시각으로, Bronze 지연은 측정 시각으로 묶이므로 둘은 대략 비교용이다.

### 탐지가 묶어 세는 예 (시나리오 1)

```sql
SELECT date_add('minute', -(minute(completed_at) % 5), date_trunc('minute', completed_at)) AS window_start,
       pg,
       COUNT(*)                             AS attempts,
       COUNT_IF(failure_cause = 'PG')       AS pg_cause_failures,
       COUNT_IF(failure_cause = 'CUSTOMER') AS customer_cause_failures
FROM gold_b.payment_attempts
WHERE completed_at < date_add('minute', -3, localtimestamp)   -- 비율 규칙용 (세션 시간대 UTC 가정)
GROUP BY 1, 2;
```

구간 크기(예: 5분), 결제가 없는 PG를 0으로 채울지, 기준값은 탐지 규칙에서 정한다. 묶어 세는 SQL이 필요하면 같이 만든다.

### 판정 시점과 상태 확인

- 늦게 도착한 데이터는 건수를 **늘리기만** 한다. 그래서 "PG 원인 실패가 3건 이상" 같은 **건수 규칙은 쌓이는 대로 바로 판정해도** 잘못 잡히지 않고, 늦은 데이터 때문에 조금 늦게 잡힐 뿐이다. 예외는 충돌이다. 나중에 충돌하는 줄이 오면 그 결제가 `payment_attempts`에서 빠져 건수가 줄 수 있다 (원래 0건이어야 함).
- **실패율 같은 비율 규칙**은 늦은 데이터로 값이 내려갈 수 있으므로, 끝난 지 3분 지난 구간만 판정한다.
- 그때 탐지가 본 숫자는 `loaded_at` ≤ 판정 시각인 줄만 세면 재현된다. 뷰는 판정 뒤에 쌓인 충돌 줄도 반영하므로, 정확히 재현할 때는 `payment_events`를 `loaded_at` ≤ 판정 시각으로 거른 뒤 같은 정리 규칙을 적용한다.

**신뢰성 점검 (주현 님 쿼리 3종)**

장애 탐지와 별개로, **Gold B 데이터 자체를 믿을 수 있는지** 확인한다. 세 시나리오 모두 이 점검을 통과한 뒤에 원인을 조사한다.

| 점검 | 읽는 것 | 문제가 나오면 |
| --- | --- | --- |
| 오프셋 빈틈 | `topic_messages` (모든 메시지가 있는 표. `payment_events`로 보면 정상인데도 빈틈처럼 보임). Gold B가 읽기 시작한 번호부터 검사 | Gold B가 메시지를 놓친 것. 그 시간대를 재처리해서 채움 |
| 중복 | `topic_messages`에서 같은 (토픽, 파티션, offset). 같은 `payment_id` 중복은 정상이라 신호가 아님 | Gold B가 같은 위치를 두 번 쌓은 것. 그 시간대를 재처리 |
| 적재 정지 | `loaded_at`, `collected_at` 최댓값 (2분 넘게 멈추면 고장) | 잡을 다시 켬. Kafka 보관(3일)을 넘게 멈췄으면 그 구간만 Bronze로 재처리 |

점검에서 문제가 나오면 그 시간대의 탐지 결과는 믿지 않고, Gold B를 먼저 고친 뒤 재판정한다. 이 경우는 원인이 이미 드러나서 에이전트 조사가 필요 없다. 수집기가 멈춘 동안의 Bronze 지연 측정값은 다시 만들 수 없어 "측정 없음"으로 남는다.

## 처리 규칙

### 중복 제거

원장에는 받은 그대로 쌓고, 중복은 **읽을 때** 거른다. 무엇을 세는지에 따라 기준이 다르다.

| 대상 | 세는 것 | 중복 제거 | 누가 |
| --- | --- | --- | --- |
| 결제 (`payment_attempts`) | 결제 시도 (업무 사실) | `payment_id`와 지문이 같으면 가장 먼저 쌓인 줄 하나. 지문이 다르면 충돌로 보고 모든 줄을 제외 | 정리 뷰 (은서) |
| 결제 충돌 (`payment_conflicts`) | 계약을 어긴 결제 | `payment_id` 하나에 한 줄, 다른 필드 이름 목록 | 정리 뷰 (은서) |
| 유입량 (`topic_messages`) | Kafka에 들어온 메시지 (관측 사실) | 하지 않음. 중복 전송도 파이프라인 상태의 일부 | - |
| 깨진 메시지 (`malformed_events`) | 깨진 필드 하나 | `(topic, kafka_partition, kafka_offset, rule_version, field)`가 같으면 한 번만 | 쌓을 때 (은서) |
| 깨진 메시지 수 (`malformed_messages`) | 깨진 메시지 한 개 | 위치(토픽·파티션·offset)가 같으면 1개, 현재 `rule_version`만 | 뷰 (은서) |

같은 메시지가 두 번 오는 경우는 주로 Debezium 재시작(마지막 저장 위치부터 다시 읽음)과 Kafka 전송 재시도다. 이때 두 메시지는 Kafka 위치(offset)가 다르다. 고객이 실제로 두 번 결제한 것은 `payment_id`가 달라서 따로 센다.

**결제 데이터 계약 (전제, 성철 님 확인):** 결제 시도 1번의 결과가 확정되면 `payments`에 1행을 INSERT하고 수정하지 않는다. 재시도는 같은 `order_id`에 새 `payment_id`와 1 증가한 `attempt_no`를 가진 새 행이다. `(order_id, attempt_no)`는 고유하다. 실패 코드는 시뮬레이터가 붙이고, Gold B는 그대로 가져와 뷰에서 묶는다.

**Silver와 다른 점 (알고 두는 것):** Silver는 같은 `payment_id`의 복사본 하나가 형식 오류이면 정상 복사본도 보류한다(`UNTRUSTED_GROUP`). Gold B는 깨진 복사본을 ④에, 정상 복사본을 ①에 따로 쌓으므로 정상 복사본이 뷰에 남는다. 형식 오류 메시지에서는 `payment_id`를 못 읽을 수도 있어 똑같이 맞추지 않는다.

### 결제 실패 원인 분류

`failure_code` 하나로 분류가 정해지고, 매핑에 없는 값은 모두 `UNKNOWN`이다. 그래서 어떤 구간에서든 실패 건수 = PG 원인 + 고객 원인 + UNKNOWN이 성립한다. 매핑은 뷰 SQL에 있어서 새 코드가 생기면 뷰만 고친다. `UNKNOWN`이 늘면 실패 코드 형식이 바뀌었다는 신호로 본다.

| `failure_code` | 분류 |
| --- | --- |
| `PG_TIMEOUT`, `PG_ERROR` | PG 원인 (`PG`) |
| `INSUFFICIENT_BALANCE`, `CARD_LIMIT_EXCEEDED`, `CARD_DECLINED` | 고객 원인 (`CUSTOMER`) |
| 코드가 있지만 매핑에 없음 | 분류 안 됨 (`UNKNOWN`) |

### 형식 검사 (시나리오 3)

토픽별 필수 컬럼·타입·허용 값 규칙표를 메시지마다 적용한다. **규칙표의 원본은 Git 저장소의 설정 파일(`format_rules.yaml`)**이고, 아래 표는 그 예시다. Gold B 적재 잡과 Silver 정제 잡이 같은 파일을 읽어서, 한쪽은 깨졌다고 하고 다른 쪽은 정상이라고 하는 일이 없게 한다. 파일 안의 `version` 값이 `malformed_events.rule_version`에 그대로 찍힌다. 새 허용 값(예: 새 PG)은 파일에 한 줄 추가하고 `version`을 올린 뒤 재처리한다. 파일 형식과 저장소 위치는 현지 님과(현재 `docs/contracts/format_rules.yaml`), 배포 방식(이미지에 포함할지, S3에서 읽을지)은 재영 님과 정한다. 파일을 바꾼 뒤 적재 잡이 새 규칙을 읽게 하는 절차(재시작 등)도 정한다.

통과한 결제만 ①에 쌓고, 실패한 메시지는 ④에 오류별로 쌓는다. ②에는 통과 여부와 상관없이 모든 메시지를 쌓는다. 메시지 하나가 깨졌는지는 정해진 규칙에 맞는지 확인하는 사실 기록이고, 그게 "이상"인지는 주현 님이 판단한다.

- `FAILED`인데 `failure_code`가 없거나 비어 있으면 `MISSING_FIELD`로 ④에 쌓고 ①에는 넣지 않는다.

| 토픽 | 필수 컬럼 | 규칙 예시 |
| --- | --- | --- |
| `clickstream` | `event_id`, `event_type`, `member_id`, `article_id`, `event_time`, `session_id` | `event_type`은 `view`·`cart_add`만, `article_id`는 10자리 문자열 |
| `payments` | `payment_id`, `order_id`, `attempt_no`, `method`, `pg`, `amount`, `status`, `requested_at`, `completed_at` | `pg`는 `PG_A`·`PG_B`만, `attempt_no` ≥ 1, `FAILED`면 `failure_code` 필수, `SUCCESS`면 비어 있어야 함. 지문에 들어가는 필드는 모두 검사한다 (공통 규칙표와 같음) |
| `orders` | `order_id`, `member_id`, `status`, `ordered_at` | `status`는 7개 값 중 하나 |
| `order-items` | `order_item_id`, `order_id`, `article_id`, `quantity`, `unit_price` | `quantity` ≥ 1, `unit_price` ≥ 5,900 (공통 계약 초안은 `minimum: 1`이라 현지 님과 맞춤) |
| `members-events` | `member_id`, `status`, `created_at` | 개인정보 컬럼이 들어 있으면 오류 |
| `reviews.raw` | 리뷰 컬럼 확정 후 (민혁 님) | `rating`은 1~5 |

오류 사유는 `PARSE_ERROR`(파싱 실패), `MISSING_FIELD`(필수 필드 누락), `TYPE_MISMATCH`(타입 불일치), `INVALID_VALUE`(허용되지 않는 값) 네 가지다. 한 메시지에 오류가 여러 개면 ④에 오류마다 한 줄을 쌓고, 사유는 필드별로 따로 기록한다. 형식 검사는 모양만 보므로, 모양은 맞는데 값이 이상한 경우(금액 0원, 미래 시각)는 잡지 못한다.

### 늦게 오는 데이터

원장에 그대로 쌓이고 다음 조회부터 반영되므로 따로 처리하지 않는다. 다만 시뮬레이터가 결제 결과 시각을 정한 뒤 몇 분 지나서 저장하면 그 결제는 "늦은 데이터"가 되어 판정 후 숫자를 바꿀 수 있으니, **결과 시각을 정하면 바로 저장**하도록 성철 님께 요청한다. 백필(과거 2주) 데이터도 원장에 그대로 쌓여 과거 구간이 자연스럽게 채워진다.

## 탐지 쪽에 제안하는 판정 방식

판정은 주현 님 담당이고, 아래는 원장과 뷰를 어떻게 묶어 읽으면 좋을지에 대한 제안이다. 탐지 규칙은 4개(R1~R4)이고, R2는 단독으로 이상을 기록하지 않아 실제로 이상을 잡는 건 3개다.

| 시나리오 | 신호 (이상으로 기록) | 같이 보는 값 (다른 원인 지우기) |
| --- | --- | --- |
| 1. PG 장애 (R1) | `payment_attempts`에서 한 PG의 `failure_cause = PG` 건수 (최근 3구간 합 ≥ 기준) | 같은 PG의 고객 원인 실패, 다른 PG, `payment_conflicts`, 같은 시간 `payments`의 형식 오류·Bronze 지연 |
| 2. 트래픽 폭주 (R3, 근거 R2) | `bronze_lag_snapshots`의 밀린 메시지 수·시간 증가, 또는 `committed_offset` 멈춤·`connector_state` 이상 | `topic_messages` 유입량 (원인이 유입 증가인지), `malformed_messages` |
| 3. 스키마 오염 (R4) | `malformed_messages`에서 한 토픽의 깨진 메시지 수 증가 | `malformed_events`의 필드·사유 분포, `topic_messages` 유입량 |

**시나리오 1: PG 원인 건수 + 최근 구간 합산**

주현 님 프로토타입에서 하루 900주문이면 PG_A의 30분간 결제 시도가 5건 안팎이라, 구간 하나로 판정하면 장애를 놓치거나 오탐이 났다. 3구간을 합산하고 "3건 이상" 조건을 걸자 오탐이 크게 줄었다.

- PG 원인 실패 건수를 주 신호로 쓴다. 평소 실패는 대부분 고객 원인이고 PG 원인은 거의 0이라 오탐이 구조적으로 적다.
- 매 구간마다 최근 3구간의 합을 본다.
- 성철 님의 시연 모드(3배·10배)별로 프로토타입을 다시 돌려 허용 지연을 정한다. 하루 900건 기본 규모에서는 PG 장애 탐지가 느리다.
- `failure_rate`는 보조로, `attempts`가 N_min 이상일 때만 본다.

**시나리오 2: 유입 증가는 증거로만**

| 적재 지연 | 유입량 | 해석 |
| --- | --- | --- |
| 증가 | 증가 | 사람이 몰려서 밀림 (시나리오 2) |
| 증가 | 평소대로 | Bronze 적재 자체 문제 |
| 평소대로 | 증가 | 잘 처리 중, 이상 아님 |

**탐지 속도 (주현 님 프로토타입, 탐지 주기 5분)**

| 상황 | 평균 탐지 시간 |
| --- | --- |
| PG 장애, 하루 900건 | 11~13분 (최대 약 28~30분) |
| PG 장애, 하루 3,600건 | 6분 (최대 10분) |
| 소비 지연 | 약 5분 |
| 스키마 오염 | 약 7분 |
| 오탐 | 하루 0.03건 |

가짜 데이터 기준이며 3배·10배 모드는 아직 측정 전이다. 허용 지연은 팀 회의에서 정한다.

**원인별 고칠 사람 (에이전트 참고용)**

깨진 메시지는 오류 종류만으로 고칠 사람이 정해지지 않는다. 에이전트가 증거를 겹쳐 원인을 추정하고 근거와 함께 제안하며, 원인 확인과 최종 배정은 사람이 한다.

| 오류 종류 | 가능한 원인 | 고칠 사람 | 가르는 증거 |
| --- | --- | --- | --- |
| `MISSING_FIELD` | 필드 이름 변경 | 은서 + 현지 (규칙표) | `raw_sample`에 비슷한 새 이름이 있음 |
| `MISSING_FIELD` | 보내는 쪽이 안 보냄 | 성철 | 값이 전혀 없음 |
| `INVALID_VALUE` | 새 정상 값을 규칙이 모름 (`PG_C`) | 은서 + 현지 | 새 값이 한 가지로 꾸준히 들어옴 |
| `INVALID_VALUE` | 시뮬레이터 버그 | 성철 | 값이 제각각이거나 말이 안 됨 |
| `TYPE_MISMATCH` | 보내는 쪽 타입 변경 | 성철 (또는 규칙표) | 특정 시점부터 한 필드만 바뀜 |
| `TYPE_MISMATCH` | Debezium 설정 변경 | 성철 | CDC 토픽 여러 개가 같은 시점에 바뀜 |
| `PARSE_ERROR` | 보내는 쪽이 JSON을 잘못 만듦 | 성철 | 한 토픽에서만 |
| `PARSE_ERROR` | Gold B 파싱 코드 버그 | 은서 | 여러 토픽이 함께 깨지고 Silver는 정상 |
| (`payment_conflicts`) | 시뮬레이터가 결제를 수정함, ID 겹침 | 성철 | 같은 `payment_id`에 다른 값 |

에이전트는 "무엇이, 언제부터, 어떻게 바뀌었나"까지 찾을 수 있지만 "왜 바꿨나"(누가 배포했나)는 Gold B 데이터에 없다. 그래서 리포트는 추정 원인과 근거까지이고, 확정은 사람이 한다.

## 재실행·재처리 설계와 검증

재처리는 **데이터를 고치는 일이 아니라, 원인(규칙·코드)을 고친 뒤 같은 원본을 다시 처리하는 일**이다. 원장 + 뷰 방식에서는 원장의 해당 시간 폴더를 다시 채우면 되고, 뷰는 원장을 따라 자동으로 다시 계산된다. Kafka와 Bronze는 읽기만 하고 바꾸지 않는다. 재처리 잡은 은서가 한 번 만들어 두고, 승인될 때마다 Airflow가 실행한다.

| 경로 | 입력 | 실행 | 쓰기 방식 |
| --- | --- | --- | --- |
| 평소 | Kafka 토픽 | 상시 실행 적재 잡 (Spark Structured Streaming, 1분 트리거) | 원장에 추가 |
| 재처리 (Kafka 보관 3일 안) | Kafka의 해당 위치부터 다시 읽기 | Airflow로 실행하는 재처리 잡 | 해당 시간 폴더를 지우고 다시 채움 |
| 재처리 (보관 기간 넘음) | Bronze의 해당 시간 구간 | 위와 같음 | 위와 같음 |

**재처리하는 경우와 안 하는 경우**

| 상황 | 재처리 | 먼저 할 일 |
| --- | --- | --- |
| Gold B가 메시지를 놓침, 같은 위치를 두 번 쌓음 (신뢰성 점검) | 함 | 없음. 원본을 다시 읽으면 바로잡힘 |
| 규칙이 새 형식·값을 모름 (`sessionId`, `PG_C`) | 함 | 규칙표를 고침 (예: v1.1) |
| Gold B 코드 버그 | 함 | 코드를 고침 |
| 백필 등 과거 구간을 채움 | 함 | 없음 (Bronze로) |
| 보내는 쪽이 값을 안 보냄 | 보통 안 함 | 보내는 쪽이 고쳐서 다시 보냄. 새 메시지는 평소 경로로 처리됨 |
| 진짜 장애 (PG 장애, 트래픽 폭주) | 안 함 | 원장은 사실을 맞게 기록한 것 |
| 뷰 SQL·분류 규칙만 바뀜 | 안 함 | 뷰만 고치면 과거까지 다시 계산됨 |

**재처리 범위와 순서**

- **범위:** 오염이 시작된 시각(`malformed_events`의 가장 이른 `kafka_timestamp`)부터 원인을 고친 시각까지다. 탐지한 시각이나 승인한 시각이 아니다. 고친 뒤 승인하면 승인 시각을 끝으로 써도 결과는 같다.
- **순서:** 반드시 **원인을 고친 뒤** 승인한다. 고치기 전에 재처리하면 같은 규칙으로 다시 처리돼 똑같이 깨진다.
- **승인 메시지:** 원인, 조치, 재처리 범위, 적용할 규칙 버전을 적는다. 이 값들이 재처리 잡의 입력(`request_id`, `window_start`, `window_end`, `rule_version`)으로 들어간다.

**재처리 잡의 동작**

- **교체 단위는 1시간 폴더다.** 15:10~15:30을 승인해도 15시대(15:00~15:59) 폴더 전체를 다시 채운다. 1분마다 쌓은 파일에는 늦게 온 데이터가 섞여 있고 하루 1회 합치기도 해서 특정 줄만 골라 바꾸면 복잡하고 위험하기 때문이다. 같은 입력으로 다시 계산하므로 문제없던 구간의 결과는 원래와 같다.
- **재처리 대상:** `payment_events`, `topic_messages`, `malformed_events`. `bronze_lag_snapshots`는 그 시점에만 잴 수 있는 측정값이라 다시 만들지 않는다. `malformed_events`는 이번 재처리의 `rule_version` 줄만 지우고 다시 만들고, 다른 버전 줄은 그대로 남긴다 (예전 판정 이력 보존).
- **읽기 범위 여유:** 폴더는 이벤트 시각 기준이라, 원본은 앞뒤로 몇 분 여유 있게 읽고 이벤트 시각으로 걸러서 쓴다. 결제는 결과 시각보다 늦게 Kafka에 들어올 수 있다.
- **Kafka 보관 기간:** 3일이다. 3일 안에 잡아서 고친 구간은 Kafka를 다시 읽고, 그보다 오래된 구간(늦게 발견, 백필)은 Bronze로 다시 채운다.
- **Bronze에 필요한 것:** 3일이 지난 구간을 Bronze로 같은 결과로 다시 만들려면 Bronze에 Kafka 위치·시각(`topic`, `partition`, `offset`, `timestamp`)과 깨진 메시지 원본이 있어야 한다. 현재 Bronze 파일에는 메시지 값만 있고(파일 이름에 파티션·시작 offset), S3 Sink에 오류 토픽 설정이 없다. Silver·Gold A를 고칠 때도 이 원본이 필요하다.
- **교체 후 재판정:** 재처리 잡은 시간 폴더 교체가 끝날 때마다 `reprocess_events`에 `LEDGER_REPLACED`와 실제 교체 범위를 남기고, 마지막에 전체 교체 범위를 결과로 넘긴다. 재처리 DAG는 판정을 직접 부르지 않고, 주현 님 판정 잡이 정해진 주기(미정, 제안 5분)마다 이 줄을 읽어 재판정한다. 교체가 끝나지 않은 폴더는 `LEDGER_REPLACED`가 없으므로 재판정되지 않는다.
- **자동 재시도:** 재처리 잡이 일시적으로 실패하면 Airflow가 같은 승인 범위 안에서 2번까지 다시 시도한다. 교체는 처음부터 다시 해도 결과가 같아서 안전하다. 계속 실패하면 `FAILED`로 멈추고 사람이 다시 승인한다. 범위가 바뀌면 새로 승인받는다.
- **한 번에 하나씩:** 같은 시간 폴더를 두 재처리가 동시에 건드리지 않도록 재처리는 한 번에 하나씩 돌린다. 같은 시간대를 순서대로 두 번 재처리하면 재판정도 두 번 되고, 이상 이력은 회차별로 쌓여 문제없다.

**Silver·Gold A와 맞추기**

Gold B는 Kafka를, Silver는 Bronze를 읽는 별도 경로지만 규칙표는 같은 파일이다. 그래서 **원인은 한 번만 고치고, 승인도 한 번만 하고, 각 경로가 자기 원본에서 다시 돈다.** Gold B가 Silver·Gold A의 데이터를 직접 고치지는 않는다 (감시하는 쪽과 감시받는 쪽이 엉키지 않게).

| Silver가 그 구간을 이미 처리했나 | Silver·Gold A |
| --- | --- |
| 아직 안 함 | 할 일 없음. 다음 배치가 새 규칙으로 맞게 만든다 (Gold B가 1분마다 보며 먼저 잡는 이점) |
| 이미 처리함 (격리됨) | 같은 승인으로 Silver 재실행(격리 해제)과 Gold A 재집계를 같이 돌린다 |

이를 판단하려면 Silver가 어디까지 처리했는지 기록이 필요하다.

**재실행 원칙 (필수 ②)**

- 같은 입력과 같은 규칙 버전으로 다시 채우면 원장(과 뷰)이 같아야 한다.
- 재처리는 시간 폴더 단위로 지우고 다시 쓴다. 중간에 실패하면 처음부터 다시 교체한다 (여러 번 돌려도 결과가 같다).
- 원본이 없는 구간(Kafka 보관 밖이고 Bronze에도 없음)은 재시도해도 소용없으므로 재시도 없이 바로 `FAILED`로 두고 `detail`에 이유를 남긴다.
- 평소 경로와 재처리 경로가 같은 정제·검사 함수를 쓴다. 입력만 바뀐다.
- 평소 경로는 체크포인트로 읽은 위치를 기억해 재시작해도 빠뜨리지 않는다. 혹시 두 번 쌓여도 뷰에서 중복을 거른다.
- 재처리 범위는 `malformed_events`의 Kafka 위치·시각과 `anomaly`의 `episode_start`, `episode_end`, `evidence_ref`로 정한다.

**재처리 검증 (필수 ③)**

재처리만으로 원본 데이터가 고쳐지지는 않는다. 같은 깨진 메시지를 같은 규칙으로 다시 처리하면 오류는 그대로 나와야 정상이다. 깨진 메시지를 "고친다"는 것은 메시지 내용을 바꾸는 게 아니라, 규칙표를 바꾸거나(예: 새 PG를 허용 값에 추가) 생산자가 올바른 메시지를 새로 보내는 것이다.

| 경우 | 바뀐 것 | 재처리 후 기대 결과 |
| --- | --- | --- |
| 동일 입력 재실행 | 없음 | 비교 대상 컬럼이 완전히 같음 (재현성) |
| 규칙 변경 | 형식 검사 규칙 버전 (예: v1.0 → v1.1) | 새 버전 기준으로 `payment_events`에 들어오는 결제가 바뀜. 예전 버전 판정은 `malformed_events`에 이력으로 남음 |
| 입력 수정 | 생산자가 올바른 메시지를 새로 보냄 | 새 메시지는 정상 처리됨. 원래 깨진 메시지는 여전히 오류로 남음 |

1. 재처리 전 해당 구간의 뷰 값을 저장한다.
2. 무엇을 바꿨는지(규칙 버전, 입력) 기록한다.
3. 해당 시간 폴더를 재처리한다.
4. 위 표의 기대 결과와 비교한다.
5. 같은 입력과 같은 규칙으로 한 번 더 재처리해 결과가 재현되는지 확인한다.
6. 재처리한 폴더 밖의 원장 줄이 바뀌지 않았는지 확인한다.

**비교 대상 컬럼:** 뷰의 지표 값과 오류 판정 결과(`field`, `reason`, `rule_version`)만 비교한다. `loaded_at`, `collected_at`처럼 실행 시각에 따라 달라지는 컬럼은 제외한다. 다만 `loaded_at`은 "그때 탐지가 본 숫자"를 재현할 때 쓴다.

**확장 후보 (필수 완료 후, 요청이 있을 때)**

- 재시도 여파 보기: 원장의 `order_id`, `attempt_no`로 정리 뷰에서 바로 셀 수 있다
- 주문 단위 지표(주문 수, 피해 주문 수): 피해 규모를 관제 단계에서 봐야 할 때
- 구간 집계 뷰: 탐지 규칙이 확정된 뒤, 반복되는 묶어 세기 SQL을 뷰로 만들어 줄 수 있다
- `payment_events`에 `method` 추가: 결제 수단별 원인까지 볼 때
- Gold B와 Silver 대조: 같은 범위(Kafka offset 기준)에서 `payment_id` 집합과 토픽별 개수를 비교해 규칙 버전 불일치, 적재 유실, Gold B 잡 누락을 원인별로 가린다
- 값 검사 추가: 형식은 맞는데 값이 이상한 오염(금액 0원·비정상 큰 값, 미래 시각)을 잡는 범위 규칙
- 관제 화면 (현재 담당 없음)

## 팀원과 확인할 것

| 상대 | 확인할 것 | 왜 필요한가 | 상태 |
| --- | --- | --- | --- |
| 주현 | 재판정 연결 방식: 판정 잡이 `reprocess_events`를 주기적으로 읽음 (Airflow로 잇지 않음) | 재처리 후 재판정 시작 방법 | 완료 (2026-10-21) |
| 주현 | 판정·재판정 확인 주기 (제안 5분) | 재판정이 늦게 시작되는 정도, 허용 지연 | 미정 |
| 주현 | `reprocess_events` 단계와 쓰는 사람, 재시도 2번 | 재처리 기록과 실패 처리 | 완료 |
| 주현 | `reprocess_events` 최종 컬럼 목록 공유 | 주현 님 문서(12번)와 테이블 정의를 맞추기 | 테이블 정의 후 |
| 주현 | 승인 메시지에 재처리 범위·규칙 버전 넣기 | 재처리 잡의 입력값 | 필요 |
| 주현 | 신뢰성 쿼리는 `topic_messages` 기준, 3분 대기는 비율 규칙에만 | 정상인데 문제처럼 보이는 것을 막기 | 필요 |
| 주현 | `payment_conflicts` 추가, `bronze_lag_snapshots.kafka_partition` 이름 | 탐지 SQL에서 쓰는 이름 | 필요 |
| 주현 | 조사 에이전트 리포트·실행 기록 표를 둘 곳 (`gold_b` 밖 권장: 에이전트는 `gold_b/`를 읽기만 함) | 에이전트 권한, 정답 노출 방지 | 필요 |
| 주현 | 허용 지연 (시연 모드별 재측정 후) | 정답표 채점 기준 | 팀 회의 |
| 성철 | Bronze 적재 방식 | 지연 측정 방식 결정 | 완료 (S3 Sink) |
| 성철 | S3 Sink 커넥터 이름, 소비자 그룹 이름 | 수집기가 처리 위치를 물어볼 대상 | 저장소상 `bronze-s3-sink`. 소비자 그룹 확인 필요 |
| 성철 | 파일 전환 주기 | 정상일 때의 지연 기준선 | 저장소상 15분. 확인 필요 |
| 성철 | Kafka Connect REST 주소 | 커넥터 상태 조회 | 필요 |
| 성철 | 오류 토픽(DLQ) 이름과 S3 저장 여부 | 깨진 원본이 있어야 오래된 구간과 Silver를 고칠 수 있음 | 저장소상 설정 없음. 필요 |
| 성철 | Bronze에 Kafka 위치·시각 저장 여부, 저장 형식(JSON/Parquet) | 3일 넘은 구간을 Bronze로 재처리할 때 필요 | 저장소상 값만 JSON으로 저장. 필요 |
| 성철 | 결제 데이터 계약, 결과 시각을 정하면 바로 저장 | 중복 제거와 재시도 구분, 늦은 데이터 방지 | 필요 |
| 성철 | 시나리오별 시연 모드(3배·10배), 평소 변동 | 탐지 기준과 허용 지연 | 필요 |
| 성철 | 시나리오 3 정답표 (토픽, 필드, 이름 변경인지 누락인지, 시작·끝 시각) | 시나리오 3 검증과 재처리 시연 | 필요 |
| 현지 | 공통 형식 검사 코드(`pipelines/format_rules.py`)를 Gold B도 쓰는 방법: 규칙표의 `gold_b` 사용 승인, 한 메시지의 오류를 전부 돌려주는 함수, 클릭·회원·리뷰 규칙에 필요한 종류(10자리 문자열, true/false 값, 최댓값, 개인정보 컬럼 금지) | Gold B와 Silver가 같은 규칙으로 판단 | 필요 (규칙표 `docs/contracts/format_rules.yaml`은 PR #20으로 머지됨) |
| 현지 | `unit_price` 최솟값 5,900 (계약 초안은 1) | 같은 메시지를 다르게 판단하지 않기 | 필요 |
| 현지 | 결제 지문 규칙(필드 9개의 순서, 시각·NULL·숫자 정규화, 직렬화, 해시)과 `pipelines/payment_fingerprint.py`를 누가 언제 만들지 | Silver와 Gold B가 같은 함수로 같은 지문을 만들기 | 필요 |
| 현지 | Silver 격리 기준 일치 | 같은 메시지를 다르게 판단하지 않기 | 필요 |
| 현지 | 격리 해제와 Silver 재처리 방식 (upsert / 구간 교체), Silver 처리 범위 기록 | 같은 승인으로 Silver·Gold A를 다시 돌리기 | 필요 |
| 현지 | `payment_attempts` 이름 겹침, Gold A 데이터셋 이름 | 발표와 문서에서 헷갈리지 않기 | 필요 |
| 재영 | Kafka 보관 기간, 적재 잡 실행 방식 | 재처리 범위, 실행 환경 | 완료 (3일, Spark Structured Streaming) |
| 재영 | 저장소 폴더 규칙, 브랜치·PR 규칙 | 파일을 어디에 둘지 | Silver와 같이 `pipelines/gold_b/`, `pipelines/gold-b` (사용자 결정) |
| 재영 | S3 폴더(`gold_b/`), Athena 사용, Glue 데이터베이스 관리 방식(Terraform 여부) | 테이블 이름이 실제로 생기려면 필요 | 필요 |
| 재영 | DDL·설계에 버킷 이름을 그대로 둘지, 자리표시자로 바꿀지 (`connectors/bronze-s3-sink.yaml`에는 이미 있음) | 공개 레포 규칙 | 필요 |
| 재영 | 적재 잡·수집기 실행 위치와 자원, 배포 방식 | 상시 실행할 자리 | 필요 |
| 재영 | Athena 접근 경로(NAT 또는 VPC 엔드포인트)와 권한 (주현 님, 대시보드 포함) | 탐지·에이전트·대시보드가 조회하려면 필요 | 필요 |
| 재영 | 규칙 파일 배포 방식 (이미지 포함 / S3) | 규칙 변경을 적재 잡에 반영 | 필요 |
| 재영 | Airflow DAG 위치, 재시도 2번, 같은 시간대 한 번에 하나씩 (재판정은 DAG로 잇지 않음, `team-inputs.md`와 같음) | 재처리 흐름 | 필요 |
| 민혁 | `reviews.raw` 리뷰 컬럼, 운영에서 이 토픽을 쓰는지 | 형식 검사 규칙, 대상 토픽 목록 | 필요 |
| 민혁 | 대시보드(#31)의 Gold B 컬럼: `bronze_lag_snapshots`는 `kafka_partition`, `payment_attempts`에는 `copies`가 없음, `payment_conflicts` 표시 | 실데이터 연결 때 화면이 깨지지 않게 | 필요 |
| 팀 전체 | "consumer lag 수집기 없음" → 수집기 추가, Gold B는 Kafka 직접, 구조도 수정 | 주문 설계·구조도와 맞추기 | 공유 필요 |

## 해야 할 일 워크플로우

1단계는 `pipelines/gold-b`(PR #36)이고 작업 기록은 `docs/tasks/gold-b-pipelines.md`다. 다음 단계부터는 `pipelines/gold-b-<작업>` 새 브랜치와 작업 지시서 `docs/tasks/gold-b-<작업>.md`로 한다 (다음: 5단계 Bronze 지연 수집기). 결제 지문(`pipelines/payment_fingerprint.py`)은 Silver와 같이 쓰는 파일이라 규칙을 현지 님과 정한 뒤 `main`에서 따로 브랜치를 만든다.

**파일 구조**

```
pipelines/gold_b/
  README.md                      # 원장·뷰·잡 설명 (이 문서 요약)
  ddl/
    database.sql
    payment_events.sql
    topic_messages.sql
    bronze_lag_snapshots.sql
    malformed_events.sql
    reprocess_events.sql
  views/                         # 3단계
    payment_conflicts.sql
    payment_attempts.sql
    malformed_messages.sql
  config/
    gold_b.yaml                  # 대상 토픽 목록, PG 목록, S3 경로
  jobs/
    streaming_ingest.py          # Spark Structured Streaming 적재 잡
    reprocess.py                 # 재처리 잡
    compact.py                   # 하루 1회 파일 합치기
  collector/
    bronze_lag_collector.py      # Bronze 지연 수집기
  dags/                          # Airflow (재영 님 규칙 확인 후)
    gold_b_reprocess.py          # 재처리 → 재판정
    gold_b_compact.py            # 파일 합치기
  deploy/                        # EKS 배포 설정 (재영 님 규칙 확인 후)
    gold_b_streaming.yaml
    gold_b_collector.yaml
  tests/
    samples/                     # 샘플 메시지 (JSON)
    test_ddl.py
    test_format_check.py
    test_reprocess.py
# 형식 검사·CDC 표시 읽기·마스킹: 현지 님과 공용 위치를 정하기 전까지 pipelines/gold_b/ 안에 둔다.
# 결제 내용 지문: pipelines/payment_fingerprint.py (Silver와 같은 함수, 2단계)
# 규칙표: docs/contracts/format_rules.yaml (현재 Silver가 읽음)
```

### 0단계: 결정과 준비

- [x]  주현 님 질문 답변 (재판정 연결, 이력 표 단계, 재시도 2번, 단계 추가)
- [x]  Bronze 적재 방식 확인 (S3 Sink)
- [x]  Kafka 보관 기간 확인 (3일)
- [x]  적재 잡 실행 방식 확정 (Spark Structured Streaming)
- [x]  저장소 구조와 브랜치·PR 규칙 (Silver와 같이)
- [ ]  노션 기획서를 이 문서로 교체
- [ ]  팀에 바뀐 점 공유 (수집기 추가, Gold B는 Kafka 직접)
- [ ]  위 「팀원과 확인할 것」 메시지 보내기 (성철, 현지, 재영, 민혁)

### 1단계: 샘플과 테이블 정의

브랜치 `pipelines/gold-b`

- [x]  `tests/samples/` 샘플 메시지 만들기 (정상 결제, PG 원인 실패, 고객 원인 실패, 같은 결제 중복, 같은 결제 내용 충돌(상태가 다른 것, 금액만 다른 것), 필드 누락, 필드 이름 변경, `pg = PG_C`, 오류 여러 개, 6개 토픽 각각)
- [x]  `ddl/` 테이블 5개 + 데이터베이스
- [x]  시간 폴더(`dt`, `hour`)와 파티션 프로젝션 설정
- [ ]  로컬 Spark에서 DDL 실행, 빈 조회와 샘플 파일 조회 확인 (이 PC에서는 Spark가 안 떠서 DDL과 설계 표 비교, pyarrow 시간 폴더 왕복으로 대신 확인)
- [ ]  Athena에서 `CREATE DATABASE gold_b`, 테이블 생성, 빈 조회 확인 (권한 준비 후)
- [x]  `reprocess_events` 최종 컬럼을 주현 님께 공유 (#29 리뷰, #36 리뷰 요청)
- [ ]  PR 올리고 합치기

### 2단계: 정제·형식 검사

(현지 님과 공용 모듈 위치·분담 먼저 확정)

- [ ]  규칙표에 6개 토픽 규칙 추가 (`docs/contracts/format_rules.yaml`과 합칠지 현지 님과)
- [ ]  CDC 표시 읽기 (`__op = c` 또는 `r`)
- [ ]  결제 내용 지문 `pipelines/payment_fingerprint.py` (Silver와 같은 함수, 규칙은 현지 님과 확정)
- [ ]  형식 검사 (사유 4가지, 오류마다 한 줄, `rule_version` 기록)
- [ ]  `raw_sample` 마스킹 (필드 이름 유지, 값만 가림)
- [ ]  `tests/test_format_check.py` 샘플로 검사 결과 확인
- [ ]  샘플로 원장 ①②④를 S3에 쌓아 보기
- [ ]  PR 올리고 합치기

### 3단계: 정리 뷰

- [ ]  `views/payment_conflicts.sql` (지문 비교, 같은 지문 버전끼리, 충돌 필드명)
- [ ]  `views/payment_attempts.sql` (충돌 제외, 가장 먼저 쌓인 줄, 원인 분류)
- [ ]  `views/malformed_messages.sql` (필드·사유 쌍 배열)
- [ ]  Athena에서 뷰 생성, 문법 확인 (`ARRAY_AGG(CAST(ROW(...)))`, `filter(ARRAY[...])`)
- [ ]  샘플로 확인: 중복이 1건으로, 충돌 결제 두 쌍이 `payment_attempts`에서 빠지고 `payment_conflicts`에 1줄씩(금액만 다른 쌍은 `[payment_content_hash]`), 오류 3개가 1줄·`error_count` 3으로
- [ ]  PR 올리고 합치기

### 4단계: 적재 잡

- [ ]  `config/gold_b.yaml` (토픽 목록, PG 목록, S3 경로, 체크포인트 경로)
- [ ]  `jobs/streaming_ingest.py` Spark Structured Streaming, Kafka 6개 토픽, 1분 트리거, 체크포인트
- [ ]  메시지마다 ②에 쌓기, 결제는 형식 통과 시 ①, 깨진 건 ④
- [ ]  이벤트 시각 기준 시간 폴더로 쓰기, `loaded_at` 기록
- [ ]  로컬 또는 개발 Kafka로 샘플을 흘려 원장 확인
- [ ]  `deploy/gold_b_streaming.yaml` 배포 설정 (재영 님 규칙)
- [ ]  EKS에 상시 실행, 시뮬레이터 메시지가 1~2분 안에 원장에 보이는지 확인
- [ ]  잡을 재시작해도 빠지거나 두 번 쌓이지 않는지 확인 (체크포인트)
- [ ]  PR 올리고 합치기

### 5단계: Bronze 지연 수집기

- [ ]  `collector/bronze_lag_collector.py` (Kafka 관리 API로 `end_offset`·`committed_offset`, Connect REST로 상태)
- [ ]  `lag_msgs`, `lag_sec` 계산, ③에 1분마다 쌓기
- [ ]  `deploy/gold_b_collector.yaml` (CronJob 또는 상시 파드)
- [ ]  정상일 때 값이 파일 전환 주기 기준선과 맞는지 확인
- [ ]  S3 Sink를 잠깐 멈춰서 밀림·멈춤이 잡히는지 확인
- [ ]  PR 올리고 합치기

### 6단계: 파일 합치기

- [ ]  `jobs/compact.py` 시간 폴더 안 작은 파일 합치기
- [ ]  `dags/gold_b_compact.py` 하루 1회
- [ ]  합친 뒤 조회 결과가 같은지 확인
- [ ]  PR 올리고 합치기

### 7단계: 재처리 잡 (필수 ②)

- [ ]  `jobs/reprocess.py` 입력: `request_id`, `window_start`, `window_end`, `rule_version`
- [ ]  승인 범위를 시간 폴더 단위로 넓히기
- [ ]  원본 선택: 3일 안은 Kafka(해당 offset부터), 넘으면 Bronze
- [ ]  원본을 앞뒤 몇 분 여유 있게 읽고 이벤트 시각으로 걸러 쓰기
- [ ]  원장 3개(①②④)를 폴더마다 교체 (`malformed_events`는 이번 `rule_version` 줄만), `bronze_lag_snapshots`는 건드리지 않음
- [ ]  `reprocess_events`에 `STARTED`, 폴더마다 `LEDGER_REPLACED`, 실패 시 `FAILED`(+`detail`) 기록
- [ ]  원본이 없는 구간은 재시도 없이 바로 `FAILED`
- [ ]  실제 교체 범위를 결과로 넘기기
- [ ]  `tests/test_reprocess.py` 같은 입력으로 두 번 돌려 결과가 같은지 확인
- [ ]  `dags/gold_b_reprocess.py` 재시도 2번, 한 번에 하나씩 (재영 님과). 재판정은 판정 잡이 `LEDGER_REPLACED`를 읽어 시작하므로 DAG로 잇지 않는다
- [ ]  PR 올리고 합치기

### 8단계: Silver 경로와 맞추기

- [ ]  현지 님과 Silver 재처리 잡 연결 (Silver가 이미 처리한 구간이면 같은 승인으로 Silver 재실행·Gold A 재집계)
- [ ]  규칙 변경 시 Gold B와 Silver가 같은 `rule_version`으로 도는지 확인

### 9단계: 재처리 검증 (필수 ③)

- [ ]  동일 입력 재실행 → 비교 대상 컬럼이 완전히 같음
- [ ]  규칙 변경(v1.0 → v1.1) → 새 버전 기준으로 바뀌고 옛 판정은 이력으로 남음
- [ ]  입력 수정 → 새 메시지는 정상, 원래 깨진 메시지는 오류로 남음
- [ ]  재처리한 폴더 밖의 원장 줄이 바뀌지 않음
- [ ]  `reprocess_events`에 단계가 순서대로 쌓이고, 판정 잡이 `LEDGER_REPLACED`를 보고 재판정하는지 확인

### 10단계: 시나리오 검증과 시연

- [ ]  주현 님 신뢰성 쿼리가 Athena에서 도는지 같이 확인
- [ ]  시나리오 1: 한 PG의 PG 원인 실패가 늘고 다른 PG·고객 원인은 평소대로
- [ ]  시나리오 2: `bronze_lag_snapshots`의 밀린 양·시간이 늘고 `topic_messages` 유입도 늘었는지
- [ ]  시나리오 3: `malformed_messages` 건수가 한 토픽에서 늘고, 필드·사유·시작 시각·offset이 보임
- [ ]  `malformed_messages` 깨진 메시지 수 = ④의 위치별 고유 개수
- [ ]  늦게 도착한 데이터가 판정 후 숫자를 바꾸는 비율 확인
- [ ]  재처리 시연 리허설 (필드 이름 변경 → 규칙 v1.1 → 승인 → 재처리 → 재판정)
- [ ]  `pipelines/gold_b/README.md` 정리 (원장·뷰·잡 설명, 실행 방법)

### 11단계: 여유가 있으면

- [ ]  확장 후보 중 팀이 필요하다고 한 것부터
