# 작업 지시서: sim/clickstream

> 상태: 완료 · 브랜치: `sim/clickstream` (분기 기준: 최신 `main`, `sim/controller` 머지 후) · 이전 작업: `sim/behavior-core` · 다음 작업: `sim/cdc-orders`(클릭 로그 S3 Sink 포함), `sim/ecs-image`

## 목표

방문 중에 생기는 **조회(`view`)와 장바구니 담기(`cart_add`) 클릭 로그를 Kafka 토픽 `clickstream`에 발행**한다. `sim/behavior-core`에서 만든 `ClickSink` 인터페이스에 Kafka 구현(`KafkaClickSink`)을 하나 더하고, 토픽을 만들고 확인하는 `sim clickstream` 명령을 만든다.

이 브랜치가 끝나면 `sim behavior live --click-sink kafka`로 방문을 돌렸을 때 클릭 로그가 로컬 Kafka의 `clickstream` 토픽에 쌓이고, `sim clickstream verify`로 내용·순서·중복을 확인할 수 있다. 주문·결제는 지금처럼 RDS(DB)에 쓰고, Kafka로는 클릭만 보낸다.

이 시뮬레이터는 **ECS에 그대로 올라가는 것을 전제**로 한다. 접속 정보는 환경 변수, 로그는 stdout, 종료는 SIGTERM이다. 단 **ECS(Fargate)에서 EKS 안 Kafka에 닿는 경로는 아직 없다**(Kafka가 EKS 내부 전용). 이 브랜치는 **로컬 Kafka로 만들고 검증**한다. ECS 경로는 만들지 않는다(아래 "만들지 않는 것").

이 지시서는 **자기 완결형**이다. 설계 문서(`docs/design/*`)가 레포에 있으면 함께 읽되, **이 지시서와 어긋나면 추측하지 말고 묻는다.**

## 먼저 읽을 것

- 루트 `CLAUDE.md`, `simulator/CLAUDE.md`, `simulator/README.md`
- `docs/tasks/sim-behavior-core.md` (`ClickSink`, `JsonlClickSink`, 클릭 로그 6개 필드)
- 코드: `behavior/sink.py`(`ClickSink`, `click_record`, `JsonlClickSink`), `behavior/model.py`(`ClickEvent`), `behavior/cli.py`(`--click-sink`), `behavior/runner.py`(`clicks.publish`), `common/config.py`(`kafka_bootstrap`, `KAFKA_BOOTSTRAP`), `cdc/consume.py`·`cdc/cli.py`·`sink/cli.py`(로컬 Kafka를 다루는 기존 방식. **수정하지 않는다**)
- `simulator/docker-compose.yml`(프로필 `cdc`의 `kafka`), `connectors/README.md`(토픽 이름과 파티션 3개 방식)

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- 루트 `CLAUDE.md`의 Git 규칙을 따른다 (작은 커밋, **push와 PR은 사용자 확인 후**). 커밋 메시지는 **타입을 붙인다**: `<타입>(sim/clickstream): <한국어 요약>`. 타입은 `feat`, `fix`, `test`, `docs`, `refactor`, `chore` 중 하나이고, 한 커밋에 타입 하나만 쓴다.
- **분기 기준:** 처음에는 `sim/controller`가 머지되기 전이라 그 브랜치에서 분기하는 특례를 두었으나, 작업 시작 전에 `sim/controller`가 `main`에 머지되었다(PR #23). 그래서 특례 없이 루트 `CLAUDE.md`대로 **최신 `main`에서 만든다**. Claude는 push, PR 생성, 머지를 하지 않고 커밋까지만 한다.
- 브랜치를 만들면 `docs/BRANCHES.md`의 `sim` 구역에 한 줄을 추가하고(같은 PR), 머지 전에 이 지시서 맨 아래 `작업 결과` 절을 채운다. 이 지시서 파일은 `docs/tasks/sim-clickstream.md`로 둔다.
- **로컬 Docker의 Kafka에만** 쓴다(`docker compose --profile cdc up -d kafka`). 원격 Kafka(EKS)에는 접속하지 않는다. RDS에도 접속하지 않는다.
- **`simulator/CLAUDE.md`의 "Kafka에는 직접 쓰지 않는다"를 고친다.** 주문·결제·회원은 지금처럼 RDS에만 쓰고(Debezium이 Kafka로 보낸다), **클릭 로그만 예외로 Kafka에 직접 발행**한다고 적는다. 같은 문서의 시뮬레이터 설명, 모듈 목록(`clickstream` 추가), "PII를 Kafka 메시지에 싣지 않는다"는 그대로 둔다. 이 수정은 "README 갱신" 커밋에 함께 넣는다.
- 새 의존성을 추가하지 않는다. `confluent-kafka`는 이미 있다.
- 기존 `cdc/`, `sink/` 코드와 커넥터 설정은 **수정하지 않는다.**
- 완료 확인 중 만든 `orders`, `order_items`, `payments` 행과 `clickstream` 토픽은 **확인 후 삭제**하고 건수를 보고한다 (DB는 시작 전에 비어 있었을 때만).

## 결정된 사항 (사용자가 확정)

| 항목 | 결정 |
|---|---|
| 토픽 이름 | `clickstream` (조회와 담기 둘 다 한 토픽, `event_type` 필드로 구분) |
| 메시지 키 | `session_id` (같은 방문의 `view` → `cart_add` 순서를 한 파티션 안에서 지킨다) |
| 클릭은 RDS에 넣지 않는다 | Kafka로 직접 발행한다 |
| 보관 | 72시간 (인프라 토픽 계약과 같다) |
| 로컬 우선 | 로컬 Kafka로 검증한다. ECS 연결 방식은 별도 결정이다 |
| 백필 | 하지 않는다 |

## 기본값 (지시서가 정한 값. 바꾸려면 사용자에게 알린다)

| 항목 | 기본값 | 이유 |
|---|---|---|
| 파티션·복제 | 3 · 1 (로컬) | `members-events`와 같다 |
| 메시지 값 | 기존 `click_record(event)`의 **6개 필드를 그대로** JSON(UTF-8, 공백 없는 `separators`)으로 | `JsonlClickSink`와 같은 모양이라 파일 방식과 Kafka 방식이 같은 내용을 낸다. `event_time`의 시간대 표기도 기존 그대로다(바꾸지 않는다) |
| 메시지 시각 | Kafka 레코드 시각은 프로듀서가 정하는 기본값 | Bronze 폴더 기준(수집 시각)에 쓰인다. `ingest_time`은 파이프라인이 붙이므로 넣지 않는다 |
| 프로듀서 설정 | `acks=all`, `enable.idempotence=true`, `linger.ms=50`, `message.timeout.ms=10000`, `allow.auto.create.topics=false` | 순서·중복을 지키고 한 건씩 보내지 않는다. 토픽이 없을 때 1파티션으로 자동 생성되는 것을 막는다 |
| 발행 실패 정책 | **버리고 센다.** `publish`는 전송 실패로 예외를 던지지 않고 실패 건수를 세며, 처음 실패할 때 경고를 한 번만 출력한다 | 클릭은 주문 흐름(RDS)을 멈추게 하면 안 된다 |
| 시작할 때 | 브로커에 닿지 않거나 `clickstream` 토픽이 없으면 **시작하지 않는다**(종료 코드 1). 이 확인이 토픽을 만들어 버리면 안 된다 | 설정 실수는 처음에 잡는다. 실행 중 끊김은 위 정책으로 견딘다 |
| 토픽 만들기·지우기 | `setup`/`reset`은 **로컬 부트스트랩(`localhost`, `127.0.0.1`)에서만** 한다 | EKS의 토픽은 인프라가 만든다 |
| TLS 설정 | 환경 변수로 받을 수 있게만 한다. 기본은 평문(로컬) | 나중에 EKS Kafka(mTLS)에 붙일 때 코드를 다시 열지 않게 한다. **로컬에서는 검증하지 못한다** |

## 메시지 모양

토픽 `clickstream`, 키 = `session_id`(UTF-8 바이트), 값 = 한 건당 JSON 하나:

```json
{"event_id": "<uuid>", "event_type": "view", "member_id": "<uuid>", "article_id": "0108775015",
 "event_time": "2026-10-19T15:20:01.123456+09:00", "session_id": "<uuid>"}
```

- `event_type`은 `view` 또는 `cart_add`.
- 회원 이름, 연락처 등 PII는 들어가지 않는다(`member_id`와 `article_id`뿐이다). 메시지 내용을 로그·콘솔에 출력하지 않는다.

## 만드는 것

### 1. `common/kafka.py` (새)

두 모듈(`behavior`, `clickstream`)이 서로 import하지 않고 같은 값을 쓰기 위한 공용 자리다.

- 상수: `CLICK_TOPIC = "clickstream"`, `CLICK_TOPIC_PARTITIONS = 3`, `TOPIC_RETENTION_MS = 259200000`(72시간)
- `KafkaSettings`(불변 데이터 클래스): `bootstrap`, `security_protocol`(기본 `PLAINTEXT`), `ssl_ca_file`, `ssl_cert_file`, `ssl_key_file`. 환경 변수 `KAFKA_BOOTSTRAP`(기존), `KAFKA_SECURITY_PROTOCOL`, `KAFKA_SSL_CA_FILE`, `KAFKA_SSL_CERT_FILE`, `KAFKA_SSL_KEY_FILE`에서 읽는다. `repr`에 경로·주소를 싣지 않는다.
- `producer_config(settings)`, `admin_config(settings)`, `consumer_config(settings, group_id)`: librdkafka 설정 딕셔너리를 만든다(`security.protocol`, `ssl.ca.location`, `ssl.certificate.location`, `ssl.key.location` 포함). 위 "기본값"의 프로듀서 설정은 `producer_config`에 둔다.
- `is_local_bootstrap(bootstrap)`: 모든 주소의 호스트가 `localhost`/`127.0.0.1`이면 참.
- 새 설정값의 기본값·검증은 `load_config`의 방식을 따른다(`common/config.py`를 크게 바꾸지 않는다. 필요하면 `KafkaSettings`만 별도로 만든다).

### 2. `KafkaClickSink` (`behavior/kafka_sink.py`)

```python
class KafkaClickSink:
    def __init__(self, settings: KafkaSettings, topic: str = CLICK_TOPIC,
                 producer_factory: Callable[[dict], Producer] | None = None) -> None: ...
    def check_ready(self) -> None: ...      # 브로커 연결과 토픽 존재 확인. 안 되면 ClickSinkError
    def publish(self, event: ClickEvent) -> None: ...
    def close(self) -> None: ...            # flush(최대 30초) 후 닫는다
    @property
    def stats(self) -> ClickStats: ...      # sent, failed
```

- `ClickSink` 인터페이스(`publish`, `close`)를 그대로 만족한다. `behavior/sink.py`의 `ClickSink`는 바꾸지 않는다.
- `publish`: `click_record(event)`를 키 `session_id`, 값 JSON으로 `produce`하고 `poll(0)`을 부른다. 전송 결과 콜백에서 성공/실패를 센다. 내부 큐가 가득 차면(`BufferError`) 짧게 `poll`한 뒤 다시 시도하고, 그래도 안 되면 그 건을 실패로 센다. **전송 실패로 예외를 던지지 않는다**(닫힌 뒤 호출 같은 프로그램 오류는 예외).
- 처음 실패할 때 경고를 한 번 출력한다(메시지에 브로커 주소, 이벤트 내용을 싣지 않는다). 이후 실패는 건수만 센다.
- `close()`는 남은 메시지를 `flush`하고 두 번 불러도 안전하다.
- `producer_factory`는 테스트가 가짜 프로듀서를 넣기 위한 자리다.
- `click_record`는 **그대로 재사용한다**(복사해 두 곳에서 관리하지 않는다).

### 3. `sim behavior live`에 `--click-sink kafka`

- `CLICK_SINKS = ("none", "jsonl", "kafka")`. `--click-sink`에 **환경 변수 `SIM_CLICK_SINK`**를 붙인다(ECS가 환경 변수로 고르게 한다).
- `kafka`일 때: `KafkaSettings`를 만들고 `KafkaClickSink.check_ready()`를 **시작 시 한 번** 부른다. 실패하면 `오류: ...`를 출력하고 종료 코드 1이다(메시지에 브로커 주소 없음, "`sim clickstream setup`을 먼저 실행하세요" 안내는 로컬일 때만).
- 시작 출력의 `클릭 Sink` 항목은 `kafka (topic clickstream)`로 나온다(브로커 주소는 출력하지 않는다).
- 종료할 때(`Ctrl+C`/`SIGTERM` 포함) 싱크를 닫아 flush한 뒤 `클릭 발행: 성공 N건, 실패 M건` 한 줄을 요약에 더한다.
- 기존 `none`, `jsonl` 동작은 바꾸지 않는다.

### 4. `sim clickstream` 명령 (`clickstream/` 모듈, 새)

`behavior`를 import하지 않고 `common`만 쓴다. `sim/cli.py`에 등록한다.

| 명령 | 동작 |
|---|---|
| `sim clickstream setup` | 토픽이 없으면 만든다(파티션 3, 복제 1, `retention.ms=259200000`). 이미 있으면 그대로 두고 설정이 다르면 알린다. **로컬 부트스트랩에서만** 한다 |
| `sim clickstream status` | 토픽 존재 여부, 파티션 수, 파티션별 low/high offset, 합계. 토픽이 없으면 종료 코드 1 |
| `sim clickstream verify` | 토픽을 처음(earliest)부터 **현재 끝까지** 한 번 읽어 아래를 확인한다. 임시 컨슈머 그룹을 쓰고 offset을 저장하지 않는다 |
| `sim clickstream reset --yes` | 토픽을 지운다. `--yes`가 없으면 하지 않는다. **로컬 부트스트랩에서만** 한다 |

`verify` 확인 항목 (각각 통과/실패와 건수를 출력, 하나라도 실패면 종료 코드 1):

1. 모든 메시지가 JSON이고 6개 필드가 있다
2. `event_type`이 `view` 또는 `cart_add`
3. 메시지 키가 값의 `session_id`와 같다
4. 같은 `session_id`의 메시지가 **한 파티션에만** 있다
5. `event_id`가 중복이 없다
6. 같은 파티션 안에서 같은 `session_id`의 `event_time`이 **줄어들지 않는다**
7. 메시지가 0건이면 "비어 있음"으로 알린다(실패가 아니라 종료 코드 2)

- 메시지 내용(`member_id` 등)을 출력하지 않는다. 틀린 메시지는 파티션·offset만 알린다.
- Kafka에 닿지 않으면 알아볼 수 있는 메시지와 종료 코드 1이다.

## 시작 전 확인 (Claude가 한다)

- 현재 브랜치가 **`sim/controller`에서 만든 `sim/clickstream`**인지 확인하고(`git merge-base`로 `sim/controller`의 끝이 조상인지), 그 위에 `sim/behavior-core`가 이미 들어 있는지 본다. `sim/controller`가 어디까지 구현됐는지(`ControlState`의 `pg_extra_fail`, `controller/` 모듈)를 확인해 사용자에게 한 줄로 알린다. `docs/BRANCHES.md`의 `sim` 구역 형식도 읽어 둔다. `behavior/sink.py`에 `ClickSink`, `click_record`가 없으면 만들지 말고 알린다.
- `pytest`(단위)와 `ruff check .`가 변경 전에 통과하는지 먼저 본다.
- `docker compose --profile cdc up -d kafka`로 로컬 Kafka를 켜고, 주문 세 테이블 행 수와 `clickstream` 토픽이 이미 있는지 확인한다(있으면 알린다). 비어 있지 않으면 완료 확인의 DB 삭제 단계는 하지 않는다.

## 테스트

**단위 (Kafka 없이, 가짜 프로듀서):**

- `KafkaClickSink`: 한 이벤트가 토픽 `clickstream`, 키 `session_id`, 값이 `click_record`와 **같은 JSON**으로 나간다. `view`와 `cart_add` 둘 다.
- 같은 방문의 이벤트를 순서대로 발행하면 가짜 프로듀서가 받은 순서가 같다.
- `BufferError` 뒤 재시도, 계속 실패하면 실패로 센다(예외 없음).
- 전송 콜백 실패가 `failed`로 세어지고 경고가 **한 번만** 출력된다. 경고와 어떤 출력에도 브로커 주소, 이벤트 내용이 없다.
- `close()`는 `flush`를 부르고 두 번 불러도 안전하다. 닫힌 뒤 `publish`는 예외.
- `check_ready()`: 브로커 불가, 토픽 없음은 `ClickSinkError`. 이 확인이 `produce`나 토픽 생성을 부르지 않는다.
- `common/kafka.py`: 환경 변수 → `KafkaSettings`(기본 평문), `producer_config`가 기본값 설정과 TLS 키를 만든다(`PLAINTEXT`일 때는 `ssl.*`가 없다), `repr`에 주소·경로 없음, `is_local_bootstrap`(`localhost:29092`, `127.0.0.1:9092` 참, 그 밖은 거짓).
- CLI: `--click-sink kafka`와 `SIM_CLICK_SINK=kafka` 둘 다 선택된다. 잘못된 값은 오류. `kafka`인데 시작 확인이 실패하면 종료 코드 1이고 방문을 시작하지 않는다. 종료 요약에 `클릭 발행` 줄이 나온다.
- `clickstream` CLI: 원격 부트스트랩에서 `setup`/`reset`은 거부. `reset`은 `--yes` 없이는 하지 않는다. `verify`의 7개 확인 항목을 가짜 메시지 목록으로(정상, 키 불일치, 순서 역전, 중복 id, 한 세션이 두 파티션, 필드 누락, 빈 토픽) 각각 확인한다.
- PII 없음: 모든 출력에 `example.com`, `010-` 없음.

**통합 (`@pytest.mark.integration`, 로컬 Kafka).** 기존 통합 테스트처럼 `localhost`가 아니거나 브로커에 닿지 않으면 **건너뛰고 알린다.**

- 테스트마다 고유 이름의 임시 토픽을 만들고 끝에 지운다(`clickstream` 토픽을 건드리지 않는다).
- `KafkaClickSink`로 이벤트 N건(여러 세션)을 발행하고 `close()` 후 컨슈머로 모두 읽는다: 건수 일치, 키·값 일치, 세션별 순서 유지, 같은 세션이 한 파티션.
- `verify` 로직을 같은 토픽에 돌려 통과한다.

## 만들지 않는 것

- **ECS(Fargate)에서 EKS Kafka로 가는 경로.** 내부 NLB, 클라이언트 인증서 공급, 네트워크 규칙은 인프라와 `sim/ecs-image`에서 정한다. TLS 설정 코드는 환경 변수 연결까지만 하고 실제 TLS 브로커 검증은 하지 않는다.
- **클릭 로그를 S3에 직접 쓰는 방식**(필요해지면 별도 작업).
- **`clickstream` 토픽의 S3 Sink 커넥터와 Bronze 적재** (→ `sim/cdc-orders`에서 다른 토픽과 함께 한다). 이 브랜치는 토픽까지 만든다.
- 쇼핑몰 API 경유 발행(`ApiClickSink`), 컨트롤러 연동
- 이벤트 종류 추가(`view`, `cart_add` 외), 메시지 필드 변경, `event_time` 표기 변경
- 기존 `cdc/`, `sink/`, `connectors/` 수정, `infra/` 변경, 설계 문서 수정

## 작업 순서

1. 시작 전 확인을 하고, **계획을 먼저 제시해 사용자 확인을 받는다**
2. `docs/BRANCHES.md`에 `sim/clickstream` 한 줄 추가(상태: 진행 중) + 이 지시서를 `docs/tasks/sim-clickstream.md`로 추가 → 커밋 `docs(sim/clickstream): 브랜치 등록과 작업 지시서 추가`
3. `common/kafka.py` + 단위 테스트 → 커밋 `feat(sim/clickstream): Kafka 공용 설정 추가`
4. `behavior/kafka_sink.py`의 `KafkaClickSink` + 단위 테스트 → 커밋 `feat(sim/clickstream): Kafka 클릭 Sink 추가`
5. `behavior/cli.py`의 `--click-sink kafka`, `SIM_CLICK_SINK`, 종료 요약 + 테스트 → 커밋 `feat(sim/clickstream): behavior live에 kafka 클릭 Sink 연결`
6. `clickstream/` 모듈(`setup`/`status`/`verify`/`reset`)과 `sim/cli.py` 등록 + 단위 테스트 → 커밋 `feat(sim/clickstream): clickstream 명령 추가`
7. 통합 테스트 → 커밋 `test(sim/clickstream): 로컬 Kafka 통합 테스트 추가`, 이어서 `simulator/README.md`, `simulator/.env.example` 갱신 → 커밋 `docs(sim/clickstream): README와 .env.example 갱신`
8. "완료 확인"을 **실제로 실행**해서 결과 보고
9. 이 지시서 맨 아래 `작업 결과` 절을 채우고, 맨 위 상태를 `완료`로 바꾸고, `docs/BRANCHES.md`의 상태를 "머지됨"으로 바꾼다 → 커밋 `docs(sim/clickstream): 작업 결과 기록`. 그다음 사용자 확인을 기다린다.

## 완료 확인

아래를 **실제로 실행**해서 결과를 보고한다. 확인용으로 만든 것은 마지막에 지운다.

- [ ] `ruff check .`, `ruff format --check .`, `pytest`(단위) 통과, `docker compose up -d` + `docker compose --profile cdc up -d kafka` 후 `pytest -m integration` 통과. 기존 baseline·live·behavior 테스트와 **`sim/controller`에서 만든 테스트도 그대로 통과**
- [ ] **토픽 만들기:** `sim clickstream setup` → 토픽 생성(파티션 3). 한 번 더 실행해도 오류 없이 "이미 있음". `sim clickstream status`가 파티션 3개와 offset 0을 보여 준다. 토픽이 없을 때 `behavior live --click-sink kafka`가 **시작하지 않고** 종료 코드 1이며 토픽이 자동으로 생기지 않았다
- [ ] 로컬 DB 상태 확인(주문 세 테이블 행 수). **비어 있을 때만** DB를 쓰는 아래 단계를 진행한다
- [ ] **발행 (배속 1440, 하루 2만 방문):** `sim behavior live --visits-daily 20000 --speed 1440 --duration 60 --click-sink kafka` → 정상 종료 코드 0. 요약의 `클릭 발행` 성공 건수와 `sim clickstream status`의 offset 합계가 **같다**. 실패 0건
- [ ] **검증:** `sim clickstream verify`의 7개 항목이 모두 통과한다
- [ ] **주문과의 연결:** 주문 테이블의 모든 `session_id`가 `clickstream` 토픽에 있다 (파이썬 한 줄로 비교, 스크립트는 커밋하지 않는다). `cart_add`가 없는 세션의 주문은 직접 주문(방문의 약 0.3%)뿐이다
- [ ] **같은 시드면 같은 내용:** `--seed 42 --run-salt 1 --max-visits 300 --click-sink jsonl`과 `--click-sink kafka`(토픽은 비운 뒤)를 같은 조건으로 한 번씩 돌려, 두 쪽의 `event_id` 집합과 `session_id`별 `event_type` 순서가 **같다**. (두 번째 실행은 DB에 이미 있는 주문이라 `23505`로 건너뛴다. 오류가 아니다.)
- [ ] **Kafka가 끊겨도 주문은 계속된다:** 실행 중 `docker compose --profile cdc stop kafka` → 방문과 주문(DB)이 계속 만들어지고 경고가 **한 번만** 나온다. 다시 `start kafka` 하면 새 클릭이 다시 쌓이고(producer 재연결) 종료 요약에 실패 건수가 보인다. 이 구간의 주문 정합성(총액 = 항목 합계 등)은 `sim/behavior-core`의 정합성 쿼리로 확인한다
- [ ] **종료:** 실행 중 `Ctrl+C` → 종료 코드 0, 요약에 `클릭 발행` 줄, 트레이스백 없음. 종료 직후 `status`의 offset이 요약 성공 건수와 같다(flush 확인)
- [ ] **원격 거부:** `KAFKA_BOOTSTRAP=kafka.example.internal:9093`처럼 로컬이 아닌 주소로 `sim clickstream setup`/`reset --yes`가 거부된다(실제 접속 없음). `reset`은 `--yes` 없이 하지 않는다
- [ ] **PII·접속 정보가 출력에 없다:** 위 실행 출력을 파일로 저장해 `grep -E "example\.com|010-"` 결과가 없고, 브로커 주소·토큰·접속 문자열이 출력에 없다. 토픽의 메시지 값에 PII 필드가 없다
- [ ] `docker build -t sim-local ./simulator` 성공, `docker run --rm sim-local behavior live --help`에 `kafka`가 보인다
- [ ] 확인 후 **삭제:** `sim clickstream reset --yes`, `DELETE FROM payments; DELETE FROM order_items; DELETE FROM orders;` (DB는 시작 전에 비어 있었던 경우만). 삭제 건수를 보고하고 세 테이블이 0행인지 확인
- [ ] `git status`에 `.env`, `simulator/.local/`이 없다. push, PR을 하지 않았다 (사용자 확인 대기)

## README 갱신

- `simulator/README.md`: `## 클릭 로그 (clickstream)` 절 — 하는 일 한 단락, 메시지 모양(토픽, 키, 값 예시), `--click-sink none|jsonl|kafka`와 `SIM_CLICK_SINK`, `sim clickstream` 명령 표(`setup`/`status`/`verify`/`reset`)와 `verify`가 확인하는 7가지, **발행 실패는 버리고 센다**는 정책, Kafka 환경 변수(`KAFKA_BOOTSTRAP`, `KAFKA_SECURITY_PROTOCOL`, `KAFKA_SSL_*`)와 TLS는 로컬 검증 전이라는 점, **ECS에서 EKS Kafka로 가는 경로는 아직 없다**는 점, 알려진 한계
- `simulator/.env.example`: Kafka TLS 변수를 **주석으로** 더한다(더미 값만, 실제 값 없음)
- `simulator/CLAUDE.md`: "시뮬레이터가 하는 일"의 "Kafka에는 직접 쓰지 않는다"를 "주문·결제·회원은 RDS에만 쓰고, 클릭 로그만 Kafka에 직접 발행한다"로 고치고, 모듈 설명과 폴더 구조에 `clickstream/`을 한 줄 더한다

## 막히면

- 이 지시서의 내용끼리, 또는 설계 문서·기존 코드와 어긋나 보이면 **추측하지 말고 묻는다.**
- 이 지시서에 없는 파일·명령·컬럼·토픽이 필요해 보이면 만들지 말고 먼저 이유를 설명한다.
- `ClickSink`, `click_record`가 지시서의 설명과 다르거나 `sim/behavior-core`가 아직 머지되지 않았으면 만들지 말고 알린다.
- 클릭의 `event_time`이 KST로 나가는 것이 "Bronze는 UTC" 규칙과 어긋나 보이면 **바꾸지 말고** 알린다(사용자가 확인한다).
- 시작 확인이 토픽을 자동으로 만들어 버리거나 `allow.auto.create.topics=false`가 먹지 않으면 고쳐서 맞추지 말고 먼저 알린다.

## 작업 결과

### 무엇을 만들었나

- `common/kafka.py`: 토픽 상수(`clickstream`, 파티션 3, 보관 72시간), `KafkaSettings`(TLS 환경 변수, `repr`에 주소·경로 없음), producer/admin/consumer 설정, `is_local_bootstrap`, librdkafka 내부 로그를 버리는 `quiet_logger`
- `behavior/kafka_sink.py`: `KafkaClickSink`
  - 키 `session_id`, 값은 `click_record` 재사용(공백 없는 JSON)
  - 시작 확인 `check_ready`, 발행 실패는 버리고 세며 경고는 한 번만
  - `BufferError`면 재시도, `close`는 최대 30초 flush하고 두 번 불러도 안전
- `sim behavior live --click-sink kafka`(환경 변수 `SIM_CLICK_SINK`): 시작 확인이 실패하면 방문을 시작하지 않고 종료 코드 1. 종료 요약에 `클릭 발행: 성공 N건, 실패 M건`
- `clickstream/` 모듈과 `sim clickstream setup | status | verify | reset --yes`. `setup`·`reset`은 로컬 부트스트랩에서만 동작하고, `verify`는 7개 항목을 확인
- 테스트: 단위 57개 추가(공용 설정 15, Sink 15, CLI 5, clickstream 22), 로컬 Kafka 통합 2개(임시 토픽)
- 문서: `simulator/README.md`의 `## 클릭 로그 (clickstream)` 절, `.env.example`(TLS 변수 주석), `simulator/CLAUDE.md`(클릭만 Kafka 직접 발행, `clickstream` 모듈)

### 지시서와 다르게 한 것

- **분기 기준:** 작업을 시작하기 전에 `sim/controller`가 `main`에 머지돼서(PR #23), 특례 없이 최신 `main`에서 분기했다. 지시서 위쪽의 특례 문구도 그에 맞게 고쳤다.
- **`quiet_logger` 추가:** librdkafka는 브로커가 끊기면 브로커 주소가 들어간 로그를 stderr에 계속 찍는다. "출력에 브로커 주소 없음, 경고는 한 번" 조건을 지키려고 클라이언트마다 이 로거를 넣었다(새 의존성 없음).
- **admin·consumer에도 `allow.auto.create.topics=false`:** 시작 확인과 `status`·`verify`의 메타데이터 조회가 토픽을 만들지 않게 했다. 로컬 브로커는 자동 생성이 켜진 기본값인데, 없는 토픽을 조회해도 생기지 않는 것을 확인했다.

### 확인한 결과 (로컬 Docker Postgres + Kafka)

- `ruff check`, `ruff format --check` 통과
- 단위 테스트 398개 통과(기존 341개 + 57개)
- 통합 테스트 22개 통과(기존 DB 20개 + Kafka 2개). `.env`에 `DATABASE_URL`이 없어서 로컬 compose 더미 값을 환경 변수로 넣고 돌렸다
- **토픽:**
  - 토픽이 없을 때 `behavior live --click-sink kafka`는 종료 코드 1이었고, 토픽이 자동으로 생기지 않았다
  - `setup`은 토픽을 만들었고(파티션 3, `retention.ms=259200000`), 다시 실행하면 "이미 있습니다"가 나왔다
  - `status`는 파티션 3개, offset 0을 보여 줬다
- **발행** (`--visits-daily 20000 --speed 1440 --duration 60`): 종료 코드 0
  - 방문 18,031, 조회 91,077, 담기 6,742, 주문 845
  - `클릭 발행: 성공 97,819건, 실패 0건` = `status` 합계 97,819건 (파티션별 32,515 / 32,647 / 32,657)
- **검증:** `verify` 6개 항목 모두 통과(97,819건)
- **주문과의 연결:**
  - 주문 845건의 `session_id`가 모두 토픽에 있었다
  - `cart_add` 없는 주문은 39건(방문 대비 0.22%)으로, 직접 주문 비율(약 0.3%)에 맞는다
  - 토픽 세션은 18,030개로 방문 수보다 1개 적다. 조회 0번으로 끝난 방문이다
- **같은 시드:** `--seed 42 --run-salt 1 --max-visits 300`을 jsonl과 kafka로 한 번씩 돌렸다. 두 쪽 모두 1,543건이었고 `event_id` 집합과 세션별 `event_type` 순서가 같았다(세션 299개)
- **Kafka 끊김** (150초 실행 중 40초 뒤 `stop kafka`, 54초 뒤 `start kafka`):
  - 꺼진 동안에도 주문이 계속 쌓였다(950 → 1,536)
  - 경고는 한 번만 나왔다(`_MSG_TIMED_OUT`), 종료 코드 0
  - Kafka를 켠 지 약 6초 뒤부터 클릭이 다시 쌓였다
  - 요약은 성공 60,390건, 실패 91,234건이었다
  - 토픽은 60,453건으로 성공보다 63건 많다. 끊기는 순간 기록됐지만 응답을 못 받은 메시지라서 실패 건수는 상한값이다. 그래도 `verify`(중복 없음 포함)는 모두 통과했다
  - 이 구간 주문 정합성 7개 쿼리(총액, 줄 없는 주문, SUCCESS 2건+, PAID 이상 SUCCESS 없음, PAYMENT_FAILED 짝, 시도 번호, 결제 금액)는 모두 0건
- **종료:** 실행 중 SIGINT를 보내면 종료 코드 0이었고, 요약에 `클릭 발행: 성공 49,660건, 실패 0건`이 나왔으며 트레이스백은 없었다. 종료 직후 `status` 합계 49,660건이 성공 건수와 같았다(flush 확인)
- **원격 거부:** `KAFKA_BOOTSTRAP=kafka.example.internal:9093`이면 `setup`과 `reset --yes`가 접속 없이 종료 코드 1로 거부됐다. `reset`은 `--yes` 없이는 종료 코드 1이었다
- **PII·접속 정보:**
  - 모든 실행 출력에 `example.com`, `010-`, 브로커 주소(`29092`), 접속 문자열이 없었다
  - 토픽 메시지 49,660건의 키는 모두 6개 필드뿐이었다
- `docker build -t sim-local ./simulator`에 성공했고, `docker run --rm sim-local behavior live --help`에 `kafka`와 `SIM_CLICK_SINK`가 보였다
- **삭제:**
  - `clickstream` 토픽을 지웠다. 통합 테스트용 임시 토픽도 남은 것이 없다
  - 결제 2,670, 주문 항목 8,993, 주문 2,555건을 지웠고 세 테이블 모두 0행이다
  - 시작 전 남아 있던 주문 265건 등은 사용자 승인으로 미리 지웠다
- `git status`에 `.env`와 `simulator/.local/`이 없다. push와 PR은 하지 않았다

### 알려진 한계

- 끊김이 있으면 실패 건수는 상한값이다(위 63건). 중복은 생기지 않는다(멱등 프로듀서).
- TLS(`KAFKA_SECURITY_PROTOCOL=SSL`)는 설정 연결까지만 했고, 실제 TLS 브로커로는 검증하지 않았다.
- ECS(Fargate)에서 EKS Kafka로 가는 경로가 아직 없다.
- 클릭 `event_time`이 `+09:00`(KST) 표기로 나간다. 지시서대로 바꾸지 않았고, "Bronze는 UTC" 규칙과 맞출지는 사용자 확인이 필요하다.
- 재시작하면 메모리 큐에 예약돼 있던 클릭은 발행되지 않는다(주문과 같은 한계).
- (기존 동작) 시작 직후 회원·상품을 읽는 동안 SIGINT를 받으면, 신호 처리기가 걸리기 전이라 요약 없이 종료 코드 130으로 끝난다. 이때는 아직 발행한 클릭이 없다.

### 다음 할 일

- `sim/cdc-orders`: 주문 세 테이블 CDC와 `clickstream` 토픽의 S3 Sink(Bronze). Debezium tombstone(null 메시지) 설정도 함께 정리한다
- `sim/ecs-image`: ECS에서 EKS Kafka로 가는 경로(내부 NLB, 클라이언트 인증서, 네트워크 규칙), TLS 실제 검증, `SIM_CLICK_SINK=kafka` 운영값
