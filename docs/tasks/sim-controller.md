# 작업 지시서: sim/controller

> 상태: 진행 전 · 브랜치: `sim/controller` · 이전 작업: `sim/modes`, `sim/behavior-core` · 다음 작업: `sim/ecs-image`, `sim/clickstream`, `sim/cdc-orders`

## 목표

시연자가 **버튼으로 시뮬레이터를 조작**하고, 조작한 **사건(장애)을 정답표로 먼저 기록**하는 컨트롤러를 만든다. 세 가지를 한다.

1. **모드 전환과 시작·정지.** `normal` / `medium` / `burst`와 `running`을 바꾼다. `medium`은 60분, `burst`는 15분 뒤 `normal`로 **자동 복귀**한다(`sim/modes`에서 뺐던 것).
2. **장애 주입.** (a) 결제사(PG) 장애, (b) burst로 인한 적재 지연(= burst 모드), (c) 데이터 오염을 만든다.
3. **정답표(`incident_log`) 기록.** 장애를 **바꾸기 전에** JSON 파일로 먼저 남긴다. 조사 에이전트가 맞혀야 할 정답이므로, 로컬은 폴더에, 나중에는 `[버킷]/ground_truth/incident_log/`에 쓴다.

이 브랜치가 끝나면 `sim controller serve`를 켜고 버튼 화면(또는 `sim controller ...` 명령)으로 모드와 장애를 바꾸면, 실행 중인 `sim member live`와 `sim behavior live`가 **제어 파일**을 통해 바로 따라 움직인다. 모듈끼리는 서로 import하지 않는다(데이터는 DB로, 제어는 제어 파일로).

이 시뮬레이터는 **ECS에 그대로 올라가는 것을 전제**로 한다. 로컬 전용 경로를 따로 두지 않는다. 설정은 환경 변수, 로그는 stdout, 종료는 SIGTERM이다.

이 지시서는 **자기 완결형**이다. 설계 문서(`docs/design/*`)가 레포에 있으면 함께 읽되, **이 지시서와 어긋나면 추측하지 말고 묻는다.**

## 먼저 읽을 것

- 루트 `CLAUDE.md`, `simulator/CLAUDE.md`, `simulator/README.md`
- `docs/tasks/sim-behavior-core.md`, `docs/tasks/sim-modes.md` (제어 파일을 읽는 두 실행기)
- 코드: `common/control.py`(`ControlState`, `FileControlSource`), `common/config.py`, `common/db.py`(`connect`, `check_db_target`), `common/rng.py`, `common/clock.py`(`FakeTime`), `behavior/runner.py`(`_poll_control`, `pg_extra_fail`), `behavior/payment.py`(`failure_probabilities`), `behavior/params.py`(`PGS`)
- DDL: `db/schema/004_orders.sql` (오염이 **DB 제약을 통과해야** 한다)

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- 루트 `CLAUDE.md`의 Git 규칙을 따른다 (작은 커밋, **push와 PR은 사용자 확인 후**). 커밋 메시지는 **타입을 붙인다**: `<타입>(sim/controller): <한국어 요약>`. 타입은 `feat`, `fix`, `test`, `docs`, `refactor`, `chore` 중 하나이고, 한 커밋에 타입 하나만 쓴다.
- 브랜치를 만들면 `docs/BRANCHES.md`의 `sim` 구역에 한 줄을 추가하고(같은 PR), 머지 전에 이 지시서 맨 아래 `작업 결과` 절을 채운다. 이 지시서 파일은 `docs/tasks/sim-controller.md`로 둔다.
- **로컬 DB에만** 쓴다. RDS에는 접속하지 않는다. S3 기록기는 **가짜 클라이언트로만** 검증하고 실제 S3에는 쓰지 않는다. (RDS TLS·전용 계정·Task Role은 `sim/ecs-image`와 인프라 몫이다.)
- 새 의존성을 추가하지 않는다. HTTP 서버는 표준 라이브러리(`http.server`), S3는 이미 있는 `boto3`를 쓴다.
- 완료 확인 중 만든 `orders`, `order_items`, `payments` 행은 **확인 후 삭제**하고 건수를 보고한다 (단, 시작 전에 비어 있었을 때만).

## 결정된 사항 (사용자가 확정)

| 항목 | 결정 |
|---|---|
| 장애 3종 | PG 장애, burst로 인한 적재 지연, 데이터 오염 |
| 주입 방법 | **버튼**으로 시연자가 직접 누른다 (자동 스케줄 없음) |
| 정답표 위치·형식 | `[버킷]/ground_truth/incident_log/`, JSON. 로컬은 파일로 먼저 만든다 |
| 정답표 순서 | **바꾸기 전에 기록한다** (기록이 실패하면 바꾸지 않는다) |
| 기록 시각 | UTC |
| 조사 에이전트 | 정답표를 읽지 못한다 (실제 차단은 인프라 IAM. 컨트롤러 화면은 에이전트가 접근하지 않는 운영자용이다) |
| 자동 복귀 | `medium` 60분, `burst` 15분 |
| 없는 시나리오 | "PG_B 장애 때 PG_A로 우회" 시나리오는 만들지 않는다 |
| 백필 | 하지 않는다 |

## 기본값 (지시서가 정한 값. 바꾸려면 사용자에게 알린다)

| 항목 | 기본값 | 이유 |
|---|---|---|
| 동시에 진행하는 사건 | **한 번에 하나** (이미 있으면 409) | 정답표가 겹치지 않아야 채점이 쉽다 |
| 모드 → 사건 이름 | `burst` = `INGEST_LAG`, `medium` = `TRAFFIC_SURGE` | burst는 적재 지연이 목적이고 medium은 약한 급증이다 |
| `running` 변경 | 사건은 아니지만 `OPERATOR_PAUSE`로 **기록**하고, "한 번에 하나" 규칙에서는 뺀다 | 트래픽 공백이 장애로 오해되지 않게 정답표에 남긴다 |
| PG 장애 | PG 하나, 추가 실패율 0.85, 10분(최대 60분) | 실패율이 눈에 띄게 올라간다 |
| 데이터 오염 | **DB 제약은 통과하지만 업무 규칙은 어기는 행**만 만든다. 스키마 변경(`ALTER TABLE`)은 만들지 않는다 | `total_amount`와 SUCCESS 건수 검증은 Silver 몫으로 남겨 뒀다. 생성기 계정에 DDL 권한을 주지 않는다 |
| 오염 종류 | `ORDER_TOTAL_MISMATCH`(기본), `DUPLICATE_SUCCESS_PAYMENT` | 아래 "데이터 오염" 참고 |
| 오염 건수 | 기본 30, 최대 500 | 정답표에 주문 id를 다 싣는 상한이다 |
| 시각 기준 | 컨트롤러는 **벽시계(UTC)** 만 쓴다 | ECS에서는 `--speed 1`이다. 배속이 1이 아니면 정답표 시각과 데이터 시각이 어긋난다 |
| 컨트롤러 재시작 | **깨끗한 상태로 시작**(모드 `normal`, 장애 없음, `running` true). 정상 종료(SIGINT/SIGTERM)하면 진행 중 사건을 끝내고 기록한다 | 죽은 컨트롤러가 장애를 남겨 두지 않게 한다 (비정상 종료로 끝 기록이 없는 사건은 알려진 한계) |

## 제어 파일

기존 `.local/control.json`(`member live`와 `behavior live`가 같은 파일을 읽는다)에 **선택 항목 하나를 더한다.**

```json
{"running": true, "mode": "normal", "pg_extra_fail": {"PG_B": 0.85}}
```

- `pg_extra_fail`은 없어도 된다(없으면 `{}`). PG 이름 → 0 이상 1 이하의 숫자다. 틀리면 **파일 전체가 잘못된 값**으로 처리되어 마지막 상태를 유지한다(경고 한 번, 기존 동작).
- `common/control.py`의 `ControlState`에 `pg_extra_fail: Mapping[str, float]`을 **기본값 빈 값**으로 더한다. 기존 호출(`ControlState(running=..., mode=...)`)과 기존 테스트가 그대로 통과해야 한다. `common`은 PG 이름을 모른다(`behavior`를 import하지 않는다).
- `behavior/runner.py`의 `_poll_control`이 `state.pg_extra_fail`을 `self.pg_extra_fail`에 반영한다. 알 수 없는 PG 이름은 무시한다. 값이 바뀌면 `pg_extra_fail: {...} → {...}` 한 줄을 출력한다(PII 없음). 결제 시도는 시작 시점의 값을 쓴다(기존 동작).
- `member live`는 이 항목을 무시한다.
- 컨트롤러가 쓸 때는 **임시 파일에 쓴 뒤 `os.replace`** 로 바꾼다(읽는 쪽이 반쯤 쓴 파일을 보지 않게).

## 만드는 것

모두 `simulator/src/sim/controller/` 안에 둔다. `member`, `behavior`를 import하지 않고 `common`만 쓴다.

### 1. `model.py`

- 사건 종류 상수: `PG_OUTAGE`, `INGEST_LAG`, `TRAFFIC_SURGE`, `DATA_POLLUTION`, `OPERATOR_PAUSE`
- PG 이름 `("PG_A", "PG_B")`, 오염 종류 상수, 상한(PG 장애 60분, 오염 500건)
- 진행 중 사건을 나타내는 불변 데이터 클래스(`incident_id`, `type`, `started_at`, `ends_at`, `params`)
- 테스트가 `behavior.params.PGS`와 같은지 비교한다(테스트에서는 둘 다 import해도 된다).

### 2. `log.py` — 정답표 기록기

```python
class IncidentLogError(RuntimeError): ...

class IncidentLog(Protocol):
    def write(self, record: dict) -> None:
        """기록이 끝까지 성공해야 돌아온다. 실패하면 IncidentLogError."""
```

- `FileIncidentLog(directory)`: 레코드 하나를 **파일 하나**로 쓴다. 파일명 `YYYYMMDDTHHMMSSZ_<incident_id>_<phase>.json`. 임시 파일에 쓰고 `fsync` 뒤 `os.replace`한다. 기본 폴더 `.local/incident_log`.
- `S3IncidentLog(bucket, client=None)`: 같은 파일명을 키 `ground_truth/incident_log/<파일명>`으로 `put_object`한다. `client`를 주입할 수 있다(테스트는 가짜). 실패하면 `IncidentLogError`(메시지에 버킷 이름·자격 증명을 싣지 않는다).
- `MemoryIncidentLog`: 테스트용.

레코드 모양 (UTF-8 JSON, 시각은 `YYYY-MM-DDTHH:MM:SSZ`):

```json
{"schema_version": 1, "incident_id": "<uuid4>", "phase": "start", "type": "PG_OUTAGE",
 "at": "2026-10-18T08:12:00Z", "params": {"pg": "PG_B", "extra_fail": 0.85, "planned_minutes": 10}}
{"schema_version": 1, "incident_id": "<uuid4>", "phase": "end", "type": "PG_OUTAGE",
 "at": "2026-10-18T08:22:00Z", "ended_by": "timer", "result": {}}
```

- `ended_by`: `timer` | `manual` | `shutdown` | `complete`(오염처럼 즉시 끝나는 것) | `failed`(적용 실패)
- 오염의 `result`: `{"kind": "...", "affected_count": n, "order_ids": [...]}` (주문 id는 PII가 아니다. 최대 500개)
- 회원 정보, 접속 정보, 버킷 이름은 레코드에 넣지 않는다.

### 3. `control_writer.py`

`FileControlWriter(path)`: `write(running, mode, pg_extra_fail)`을 위 제어 파일 모양으로 원자적으로 쓴다. `read_current()`는 컨트롤러 안에서 현재 값을 확인하는 용도다.

### 4. `pollution.py` — 데이터 오염

`PollutionExecutor` 인터페이스 `apply(kind, count, incident_id) -> PollutionResult`(영향 건수와 주문 id 목록)와 구현 둘.

- `DbPollution(database_url)`: `common/db.py`의 `connect`로 **한 트랜잭션** 안에서 실행한다. 파라미터 바인딩만 쓴다.
  - `ORDER_TOTAL_MISMATCH`: 상태가 `PAID`, `SHIPPED`, `DELIVERED`인 주문 중 **`ordered_at`이 가장 최근인 `count`건**(`ORDER BY ordered_at DESC, order_id`)의 `total_amount`에 10,000을 더한다. `updated_at`은 건드리지 않는다. 결과: 주문 총액이 항목 합계와 결제 금액과 어긋난다.
  - `DUPLICATE_SUCCESS_PAYMENT`: `SUCCESS` 결제가 있는 최근 주문 `count`건에 **`SUCCESS` 결제 행을 한 건 더** 넣는다. `method`, `pg`, `amount`, `order_id`는 기존 성공 행과 같고, `attempt_no`는 그 주문 최대 시도 번호 + 1, `requested_at`/`completed_at`은 기존 `completed_at`의 +1초/+2초, `payment_id`는 `SimRandom(derive_seed(seed, "pollution", incident_id, order_id)).uuid4()`로 만든다. 결과: 한 주문에 SUCCESS가 둘 이상이다.
  - 두 종류 모두 **DB 제약(CHECK, UNIQUE, FK)을 위반하지 않아야 한다.** 대상이 없으면(`count`보다 적어도 1건은 있어야 함) `PollutionError`.
  - 사전 점검으로 대상이 있는지 **읽기만 먼저** 한다(기록하기 전에 실패시키려는 것).
- `MemoryPollution`: 테스트용.
- DB 오류 메시지는 `common/db.py`의 오류 가리기를 거친다(호스트·비밀번호 없음).

### 5. `service.py` — 컨트롤러 핵심 (HTTP 없이 테스트 가능)

`ControllerService(control_writer, incident_log, pollution, clock, new_id, medium_minutes=60, burst_minutes=15)`. 시계는 `() -> datetime(UTC)`로 주입한다.

| 메서드 | 동작 |
|---|---|
| `status()` | 모드, running, `pg_extra_fail`, 진행 중 사건(있으면), 마지막 오류 |
| `set_mode(mode)` | `medium`/`burst`: 사건 시작(`TRAFFIC_SURGE`/`INGEST_LAG`), 자동 복귀 시각 설정. `normal`: 진행 중인 모드 사건을 `manual`로 끝낸다. 이미 같은 모드면 변화 없음 |
| `set_running(bool)` | `false`: `OPERATOR_PAUSE` 시작 기록, `true`: 끝 기록. 다른 사건과 충돌하지 않는다 |
| `start_pg_outage(pg, extra_fail, minutes)` | 검증(PG 이름, 0 < `extra_fail` ≤ 1, 0 < `minutes` ≤ 60) 후 사건 시작 |
| `start_data_pollution(kind, count)` | 검증, 사전 점검, 시작 기록 → 적용 → 끝 기록(`complete`) |
| `end_active(reason="manual")` | 진행 중 사건을 되돌리고 끝 기록 |
| `tick()` | 자동 복귀 시각이 지난 사건을 `timer`로 끝낸다. 끝 기록이 실패했으면 다시 쓴다 |
| `shutdown()` | 진행 중 사건(일시정지 포함)을 `shutdown`으로 끝내고, 제어 파일을 `normal`, 장애 없음으로 되돌린다 |

**순서 규칙 (이 작업의 핵심이다):**

1. 시작: 검증 → **시작 기록**(실패하면 `IncidentLogError`를 올리고 **아무것도 바꾸지 않는다**) → 바꾸기(제어 파일 또는 DB). 바꾸기가 실패하면 `ended_by="failed"` 끝 기록을 **최선을 다해** 남기고 오류를 올린다.
2. 끝: 되돌리기(제어 파일) → 끝 기록. 끝 기록이 실패하면 사건을 "끝나는 중"으로 두고 다음 `tick()`에서 다시 쓴다. `status()`에 표시한다.
3. 같은 시각에 두 스레드가 부르지 않도록 **잠금 하나**로 보호한다.
4. 사건이 진행 중인데 다른 사건을 시작하면 `IncidentActiveError`(HTTP 409). 단 `OPERATOR_PAUSE`는 제외.

### 6. `server.py` — HTTP 서버와 버튼 화면

표준 라이브러리 `ThreadingHTTPServer`. 요청마다 서비스를 부른다. 백그라운드 스레드가 1초마다 `tick()`을 부른다.

| 경로 | 설명 |
|---|---|
| `GET /` | 버튼 화면(HTML 한 장, 외부 스크립트·CDN 없음) |
| `GET /healthz` | `{"ok": true}` (인증 없음. ECS 상태 확인용) |
| `GET /api/status` | `status()` |
| `POST /api/mode` | `{"mode": "burst"}` |
| `POST /api/running` | `{"running": false}` |
| `POST /api/incidents/pg-outage` | `{"pg": "PG_B", "extra_fail": 0.85, "minutes": 10}` |
| `POST /api/incidents/data-pollution` | `{"kind": "ORDER_TOTAL_MISMATCH", "count": 30}` |
| `POST /api/incidents/end` | 진행 중 사건 종료 |

- 모든 `/api/*`는 `Authorization: Bearer <토큰>`이 필요하다. 토큰은 환경 변수 `SIM_CONTROLLER_TOKEN`이다. **로컬(127.0.0.1) 바인딩에서만 토큰이 없어도 시작**하고, 그 밖의 호스트에 바인딩하면 토큰이 없을 때 시작을 거부한다. 토큰은 출력·로그에 싣지 않는다.
- 오류 코드: 400(잘못된 값), 401(토큰), 409(사건 진행 중), 503(정답표 기록 실패, DB 설정 없음). 응답 본문에 DB 오류 내용·접속 정보를 싣지 않는다.
- 버튼 화면: 토큰 입력 칸, 모드 세 버튼, 시작/정지, PG 장애(PG 선택, 분)와 시작 버튼, 데이터 오염(종류, 건수)과 시작 버튼, 진행 중 사건과 종료 버튼, 현재 상태(2초마다 갱신). 토큰은 자바스크립트 변수에만 두고 저장하지 않는다. 화면은 꾸미지 않는다.
- 이 서버는 **운영자용**이다. 정답표 내용(`result`)은 `GET /api/status`에 싣지 않고 진행 중 사건의 종류와 시각만 보여 준다.

### 7. `cli.py`와 `sim/cli.py` 등록

| 명령 | 동작 |
|---|---|
| `sim controller serve` | 서버를 켠다. 옵션: `--host`(`SIM_CONTROLLER_HOST`, 기본 `127.0.0.1`), `--port`(`SIM_CONTROLLER_PORT`, 기본 8080), `--control-file`(기본 `.local/control.json`), `--incident-log file\|s3`(기본 `file`), `--incident-dir`(기본 `.local/incident_log`), `--medium-minutes`(`SIM_MEDIUM_MINUTES`, 기본 60), `--burst-minutes`(`SIM_BURST_MINUTES`, 기본 15, 소수 허용) |
| `sim controller status` | 켜져 있는 서버에 `GET /api/status` |
| `sim controller mode <normal\|medium\|burst>` | `POST /api/mode` |
| `sim controller running <true\|false>` | `POST /api/running` |
| `sim controller pg-outage --pg PG_B [--extra-fail 0.85] [--minutes 10]` | `POST /api/incidents/pg-outage` |
| `sim controller pollution [--kind ORDER_TOTAL_MISMATCH] [--count 30]` | `POST /api/incidents/data-pollution` |
| `sim controller end` | `POST /api/incidents/end` |

- 서버 밖 명령은 `--url`(`SIM_CONTROLLER_URL`, 기본 `http://127.0.0.1:8080`)과 `SIM_CONTROLLER_TOKEN`으로 **HTTP만** 부르는 얇은 클라이언트다(`urllib`). 파일을 직접 쓰는 명령은 만들지 않는다 (**쓰는 곳은 서버 하나**다).
- `--incident-log s3`는 `S3_BUCKET`(`Config.s3_bucket`)이 없으면 시작하지 않는다.
- 데이터 오염은 `DATABASE_URL`이 있을 때만 켠다. 없으면 오염 요청이 503이고 나머지는 동작한다. DB 대상은 `check_db_target`을 거친다(`SIM_ALLOW_REMOTE_DB`와 같은 방식).
- 시작 출력: 호스트, 포트, 제어 파일 이름, 정답표 위치(폴더 또는 `s3`), 자동 복귀 시간. **토큰, 접속 문자열, 버킷 이름은 출력하지 않는다.**
- `SIGINT`/`SIGTERM`을 받으면 `shutdown()`을 부르고 종료 코드 0으로 끝난다.

## 시작 전 확인 (Claude가 한다)

- 현재 브랜치가 **최신 `main`**(`sim/modes`, `sim/behavior-core`가 머지된 상태)에서 만든 `sim/controller`인지 확인한다. `docs/BRANCHES.md`의 `sim` 구역 형식도 읽어 둔다. `behavior/runner.py`에 `pg_extra_fail`이 없으면 만들지 말고 알린다.
- `pytest`(단위)와 `ruff check .`가 변경 전에 통과하는지 먼저 본다.
- `docker compose ps`로 로컬 Postgres를 확인하고 `SELECT count(*) FROM orders;`, `payments`, `order_items`를 본다. 비어 있지 않으면 완료 확인의 삭제 단계는 하지 않고 알린다.

## 테스트

**단위 (DB 없이, 가짜 시계·메모리 기록기·가짜 S3):**

- `ControlState`: `pg_extra_fail` 없는 옛 파일이 그대로 읽힌다. 범위 밖 값, 숫자가 아닌 값, 객체가 아닌 값은 **잘못된 파일**로 처리된다. 기존 `member live`·`behavior live` 테스트가 그대로 통과한다.
- `BehaviorRunner`: 가짜 제어 신호로 `pg_extra_fail`이 바뀌면 이후 결제 시도만 영향을 받고 알 수 없는 PG 이름은 무시되며 변경 줄이 한 번 출력된다.
- 기록기: `FileIncidentLog` 파일명·JSON 내용·UTC `Z` 형식, 같은 파일을 덮어쓰지 않음. `S3IncidentLog`가 키 `ground_truth/incident_log/<파일명>`으로 가짜 클라이언트를 한 번 부른다. 실패 시 `IncidentLogError`이고 메시지에 버킷·키가 없다.
- 서비스 순서 규칙: 시작 기록이 실패하면 제어 파일과 DB가 **그대로**다(쓰기 기록이 없다). 바꾸기가 실패하면 `failed` 끝 기록이 남는다. 끝 기록이 실패하면 다음 `tick()`에서 다시 쓴다.
- 자동 복귀: 가짜 시계로 `burst` 15분, `medium` 60분 뒤 `tick()`이 `normal`로 되돌리고 `timer` 끝 기록을 남긴다. 14분 59초에는 안 되돌린다.
- 한 번에 하나: 사건 중 다른 사건은 `IncidentActiveError`. `OPERATOR_PAUSE`는 예외. `normal`로의 전환은 모드 사건을 끝낸다.
- PG 장애: 제어 파일에 `pg_extra_fail`이 들어가고, 끝나면 `{}`로 돌아온다. 잘못된 PG 이름, `extra_fail` 0 또는 1 초과, `minutes` 0 또는 61은 400 성격의 오류.
- 오염: 대상이 없으면 시작 기록 전에 실패한다. 정답표 `result.affected_count`와 `order_ids` 수가 같다.
- `shutdown()`: 진행 중 사건이 `shutdown`으로 끝나고 제어 파일이 `normal`, 장애 없음.
- 모델: `PG` 이름이 `behavior.params.PGS`와 같다.
- HTTP(`http.client`로 포트 0 서버에): 토큰 없음 401, 잘못된 값 400, 사건 중 409, 정상 흐름(모드 전환, PG 장애 시작·종료), `/healthz`는 토큰 없이 200, 비로컬 호스트 + 토큰 없음이면 시작 거부, 응답과 출력에 토큰·DB 정보가 없다.
- CLI: 옵션 파싱, 서버에 연결 못 하면 종료 코드 1과 알아볼 수 있는 메시지.
- PII 없음: 모든 출력과 정답표에 `example.com`, `010-` 없음.

**통합 (`@pytest.mark.integration`, 로컬 DB, 임시 스키마).** 기존 통합 테스트처럼 `localhost`가 아니면 건너뛴다.

- 임시 스키마에 `db/schema/*.sql`을 적용하고 회원, 상품, 주문, 항목, 결제 몇 건을 직접 넣는다.
- `ORDER_TOTAL_MISMATCH`: 영향 건수가 `count`이고, 해당 주문의 `total_amount`가 항목 합계와 달라졌으며 제약 오류가 없다.
- `DUPLICATE_SUCCESS_PAYMENT`: 해당 주문의 SUCCESS가 정확히 2건이 되었고 `(order_id, attempt_no)` 유니크를 지켰다.
- 트랜잭션: 중간에 실패하면 아무 행도 바뀌지 않는다.

## 만들지 않는 것

- 스키마 변경 장애(`ALTER TABLE` 등)와 그에 필요한 DDL 권한
- 클릭 로그, Kafka, CDC, 실제 S3 쓰기와 IAM (→ `sim/clickstream`, `sim/cdc-orders`, `sim/ecs-image`, 인프라)
- ECS에서 버튼 화면에 **접속하는 경로**(ECS Exec, 포트 포워딩, 내부 ALB 등. → `sim/ecs-image`와 인프라에서 정한다)
- 회원 탈퇴, 신규 가입 로직 변경
- 컨트롤러 재시작 뒤 진행 중 사건의 복구, 여러 사용자 인증, 화면 꾸미기
- 자동 스케줄로 장애를 일으키는 기능
- 정답표를 읽어 채점하는 기능 (채점은 다른 영역)
- 설계 문서 수정, `infra/` 변경

## 작업 순서

1. 시작 전 확인을 하고, **계획을 먼저 제시해 사용자 확인을 받는다**
2. `docs/BRANCHES.md`에 `sim/controller` 한 줄 추가(상태: 진행 중) + 이 지시서를 `docs/tasks/sim-controller.md`로 추가 → 커밋 `docs(sim/controller): 브랜치 등록과 작업 지시서 추가`
3. `common/control.py`의 `pg_extra_fail`, `behavior/runner.py` 반영 + 테스트 → 커밋 `feat(sim/controller): 제어 신호에 PG 추가 실패율 추가`
4. `model.py`, `log.py`, `control_writer.py` + 테스트 → 커밋 `feat(sim/controller): 정답표 기록기와 제어 파일 쓰기 추가`
5. `pollution.py` + 단위 테스트 → 커밋 `feat(sim/controller): 데이터 오염 실행기 추가`
6. `service.py` + 단위 테스트 → 커밋 `feat(sim/controller): 모드·장애 컨트롤러 핵심 추가`
7. `server.py`, 버튼 화면 + 테스트 → 커밋 `feat(sim/controller): HTTP 서버와 버튼 화면 추가`
8. `cli.py`, `sim/cli.py` 등록 + 테스트 → 커밋 `feat(sim/controller): controller 명령 추가`
9. 통합 테스트 → 커밋 `test(sim/controller): 데이터 오염 통합 테스트 추가`, 이어서 `simulator/README.md` 갱신 → 커밋 `docs(sim/controller): README 갱신`
10. "완료 확인"을 **실제로 실행**해서 결과 보고
11. 이 지시서 맨 아래 `작업 결과` 절을 채우고, 맨 위 상태를 `완료`로 바꾸고, `docs/BRANCHES.md`의 상태를 "머지됨"으로 바꾼다 → 커밋 `docs(sim/controller): 작업 결과 기록`. 그다음 사용자 확인을 기다린다.

## 완료 확인

아래를 **실제로 실행**해서 결과를 보고한다. 확인용으로 넣은 행은 마지막에 지운다.

- [ ] `ruff check .`, `ruff format --check .`, `pytest`(단위) 통과, `docker compose up -d` 후 `pytest -m integration` 통과. 기존 baseline·live·behavior 테스트가 **그대로 통과**
- [ ] 로컬 DB 상태 확인(주문 세 테이블 행 수). **비어 있을 때만** 아래 DB 단계를 진행한다
- [ ] **서버와 모드:** `SIM_CONTROLLER_TOKEN=test-token sim controller serve --burst-minutes 0.2 --medium-minutes 0.4`를 켜고, 다른 터미널에서 `sim behavior live --visits-daily 20000 --speed 60`을 켠다. `sim controller mode burst` → 정답표 폴더에 **시작 파일이 제어 파일 변경보다 먼저** 생기고(파일 수정 시각으로 비교), 행동 실행기에 `mode: normal → burst` 줄이 나온다. 약 12초 뒤 자동으로 `normal`로 돌아오고 `timer` 끝 파일이 생긴다
- [ ] **PG 장애 (배속 1):** `sim behavior live --mode medium --visits-daily 111000 --speed 1`(주문이 분당 약 19건)을 켜 두고 `sim controller pg-outage --pg PG_B --extra-fail 0.9 --minutes 5`. 장애 구간(정답표의 시작·끝 시각)에 `requested_at`이 속한 `PG_B` 결제 시도의 실패율이 **0.8 이상**이고 같은 구간 `PG_A`는 평시 수준(약 10%)이다. 실패 코드는 `PG_TIMEOUT`/`PG_ERROR`가 대부분이다. 끝난 뒤 제어 파일의 `pg_extra_fail`이 `{}`이다
- [ ] **데이터 오염:** 위 실행으로 주문이 쌓인 뒤 `sim controller pollution --kind ORDER_TOTAL_MISMATCH --count 20`. 정답표 끝 파일의 `affected_count`가 20이고, 아래 쿼리 결과 행 수가 일치한다: `SELECT o.order_id FROM orders o JOIN order_items i USING (order_id) GROUP BY o.order_id, o.total_amount HAVING sum(i.quantity * i.unit_price) <> o.total_amount;`. 이어서 `DUPLICATE_SUCCESS_PAYMENT`로 `SUCCESS`가 둘 이상인 주문 수가 `affected_count`와 일치하고 행동 실행기가 계속 정상 동작한다(오류 없음)
- [ ] **한 번에 하나:** 사건 진행 중 다른 사건 요청이 409다. 토큰 없이 요청하면 401이다
- [ ] **정답표 내용:** 만들어진 JSON 파일을 파이썬으로 모두 읽어 `schema_version`, `phase`, `type`, `at`(UTC `Z`)이 있고 같은 `incident_id`의 시작·끝이 짝을 이루며 `example.com`, `010-`이 없다. 파일 목록과 요약을 보고한다
- [ ] **종료:** 사건이 진행 중일 때 서버를 `Ctrl+C`로 끈다. 종료 코드 0, `shutdown` 끝 파일, 제어 파일이 `normal`이고 `pg_extra_fail`이 `{}`
- [ ] **시작 거부:** `sim controller serve --host 0.0.0.0`을 토큰 없이 켜면 시작하지 않고 메시지에 토큰·접속 정보가 없다
- [ ] **버튼 화면:** 서버를 켜고 `GET /`이 200이며 `/healthz`가 토큰 없이 200이다. 브라우저로 열 수 있으면 버튼으로 모드 전환을 한 번 확인한다(없으면 `curl`로 대신하고 알린다)
- [ ] **S3 기록기:** 실제 S3에는 쓰지 않았다. 가짜 클라이언트 단위 테스트가 통과했다는 것을 보고한다
- [ ] 출력 전체에서 `grep -E "example\.com|010-"` 결과가 없다. 토큰, `DATABASE_URL`, 버킷 이름이 출력에 없다
- [ ] 확인 후 **삭제:** `DELETE FROM payments; DELETE FROM order_items; DELETE FROM orders;` (시작 전에 비어 있었던 경우만). 삭제 건수를 보고하고 세 테이블이 0행인지 확인. `.local/incident_log`의 확인용 파일도 지운다
- [ ] `git status`에 `.env`, `simulator/.local/`이 없다. push, PR을 하지 않았다 (사용자 확인 대기)

## README 갱신

- `simulator/README.md`: `## 컨트롤러 (controller)` 절 — 하는 일 한 단락, 명령 표, 제어 파일 모양(`pg_extra_fail` 포함), 모드 자동 복귀(60분/15분)와 사건 종류 표(`PG_OUTAGE`, `INGEST_LAG`, `TRAFFIC_SURGE`, `DATA_POLLUTION`, `OPERATOR_PAUSE`), 정답표 레코드 예시와 저장 위치(로컬 폴더, S3 키 접두어 `ground_truth/incident_log/`), 데이터 오염 두 종류가 **무엇을 어기는지**, 환경 변수(`SIM_CONTROLLER_HOST`/`PORT`/`TOKEN`, `SIM_MEDIUM_MINUTES`, `SIM_BURST_MINUTES`), **벽시계 기준이라 ECS에서는 `--speed 1`이어야 한다**는 점, 알려진 한계(비정상 종료 시 끝 기록 없음, 컨트롤러 재시작 시 깨끗한 상태로 시작)
- `simulator/CLAUDE.md`: 폴더 구조의 `controller/` 설명에 "(정답표 기록)"이 없다면 그 한 줄만 보완한다

## 막히면

- 이 지시서의 내용끼리, 또는 설계 문서·기존 코드와 어긋나 보이면 **추측하지 말고 묻는다.**
- 이 지시서에 없는 파일·명령·컬럼·테이블이 필요해 보이면 만들지 말고 먼저 이유를 설명한다.
- `sim/behavior-core`가 아직 머지되지 않아 `pg_extra_fail` 등이 없으면 만들지 말고 알린다.
- 기존 코드가 이 지시서의 가정과 다르면(예: `_poll_control`이 다른 모양) 고쳐서 맞추지 말고 먼저 알린다.

## 작업 결과

(머지 전에 Claude Code가 채운다: 무엇을 만들었나, 왜, 확인한 결과(완료 확인 실행 결과), 알려진 한계, 다음 할 일. 다음 작업은 `sim/ecs-image`, `sim/clickstream`, `sim/cdc-orders`.)