# simulator/

가상 쇼핑몰의 회원 데이터를 만들어 RDS(PostgreSQL)에 쓰는 시뮬레이터이다. 회원·주문·결제는 Kafka에 직접 쓰지 않고 Debezium이 변경 로그를 읽어 보낸다. 클릭 로그만 예외로 Kafka 토픽 `clickstream`에 직접 발행한다. 설계는 `docs/design/`에 있다. 작업 규칙은 `CLAUDE.md`를 따른다.

## 코드 구조

```
simulator/
├── pyproject.toml
├── Dockerfile             # 이미지 하나, 실행 명령만 다르게
├── docker-compose.yml     # 로컬 Postgres (이후 Kafka·Debezium 프로필)
├── .env.example           # 더미 값만
├── data/                  # 지역 목록 CSV 등 (필요한 브랜치에서 추가)
├── src/sim/
│   ├── cli.py             # sim 명령 진입점
│   ├── cdc/               # 로컬 CDC: 커넥터 등록·상태·초기화, 토픽 검증 (sim cdc)
│   ├── sink/              # 로컬 S3 Sink: 커넥터 등록·상태·초기화, S3 파일 검증 (sim sink)
│   ├── clickstream/       # 클릭 로그 토픽 만들기·상태·검증·지우기 (sim clickstream)
│   ├── product/           # 상품 시드(Parquet)를 DB에 옮기고 확인 (sim product)
│   ├── common/            # 설정, 시드·난수, DB 연결, Kafka 설정, 시계, 곡선, 제어 신호, 로깅, 지역 로더
│   ├── controller/        # 모드 전환, 장애 주입, 정답표 기록 (sim controller)
│   ├── member/            # 회원 생성 함수, 베이스라인 적재, 신규 가입 실행기
│   └── behavior/          # 쇼핑 행동: 방문, 주문, 결제, 상태 전이 (sim behavior)
└── tests/
```

`member`, `behavior`, `controller`, `clickstream`은 서로 import하지 않고 `common`만 공유한다. 데이터는 DB로, 제어는 컨트롤러 신호로만 주고받는다. DDL은 `db/schema/`에 있다.

## 로컬 실행

```bash
cd simulator
python3.12 -m venv .venv && source .venv/bin/activate   # Windows: py -3.12 -m venv .venv
pip install -e ".[dev]"

cp .env.example .env         # 로컬 더미 값. 커밋하지 않는다
docker compose up -d         # 로컬 Postgres (wal_level=logical)

sim --help
pytest
ruff check . && ruff format --check .
```

로컬 DB 접속 (호스트에 `psql`이 없어도 된다):

```bash
docker compose exec postgres psql -U sim -d clothes
```

## 회원 베이스라인

가상 회원 10만 명을 만들어 로컬 `members` 테이블에 한 번에 적재하고, 결과를 확인한다. 이 명령은 로컬 DB용이다 (RDS 접속은 이후 작업).

```bash
docker compose up -d
sim member baseline --dry-run          # DB 없이 생성만 하고 요약(재현성 해시)을 본다
sim member baseline --yes              # 10만 명 적재 (--yes가 없으면 대상 DB를 보여 주고 묻는다)
sim member verify                      # 12개 항목 확인, 하나라도 실패하면 종료 코드 1
```

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `baseline --count` | 100000 | 만들 회원 수 |
| `baseline --seed` | `SIM_SEED`, 없으면 42 | 난수 시드 |
| `baseline --batch-size` | 5000 (1000~5000) | COPY 한 번에 넣는 행 수. 결과에는 영향이 없다 |
| `baseline --dry-run` | | DB에 접속하지 않고 생성만 한다 |
| `verify --expected` | 100000 | 기대하는 행 수 |

- `members` 테이블에 행이 하나라도 있으면 아무것도 넣지 않고 멈춘다. 로컬에서 다시 하려면 `docker compose down -v` 후 `up -d`.
- 적재가 끝나면 PII 없는 집계값 요약을 출력하고 `.local/baseline_run.json`에 쓴다.
- 직접 확인: `docker compose exec postgres psql -U sim -d clothes -c "SELECT count(*), count(DISTINCT email), count(DISTINCT phone) FROM members;"`
- **재현성 해시**는 생성한 모든 행의 SHA-256 앞 12자리다. 시드·인원·지역 파일이 같으면 배치 크기와 상관없이 같다. 다르면 다른 조건으로 만든 데이터다.
- **지역 파일** `data/region_weights_202609.csv`의 이름에 기준월(2026-09)이 들어 있다. 파일을 바꾸면 같은 시드라도 결과(해시)가 달라지므로, 어느 파일로 만들었는지 요약에 남긴다. 다른 파일은 `SIM_REGION_FILE`로 지정한다.
- 환경 변수: `DATABASE_URL`(필수), `SIM_SEED`, `SIM_REGION_FILE`. 상대 경로와 `.env`는 현재 작업 폴더(`simulator/`) 기준이다.
- PII(이름·이메일·전화·생년월일·해시)는 출력하지 않는다. DB 오류도 예외 종류, sqlstate, 제약 이름만 보여 준다.

통합 테스트는 로컬 DB가 필요하며 기본 `pytest`에서는 제외된다 (임시 스키마를 만들었다 지운다).

```bash
pytest -m integration
```

## 신규 가입 (live)

베이스라인 뒤에 신규 가입을 계속 만들어 `members`에 **한 건씩(건당 트랜잭션 하나)** 넣는다. 로컬 DB 전용이다 (호스트가 `localhost`/`127.0.0.1`이 아니면 실행을 거부한다). **베이스라인(10만 명)을 먼저 적재한 뒤에 켠다.**

```bash
sim member live                                   # normal, 실시간, 하루 평균 25,000명 (요일·시간대 곡선)
sim member live --mode burst --speed 60 --duration 30   # 폭주로 시작, 시뮬레이터 30분
sim member live --speed 1440 --duration 30        # 시뮬레이터 하루 = 실제 1분으로 30초 실행
sim member live --daily 86400 --max-signups 20    # 초당 약 1건, 20건 만들고 종료
```

| 옵션 | 환경 변수 | 기본값 | 설명 |
|---|---|---|---|
| `--mode` | `SIM_LIVE_MODE` | `normal` | 시작 모드 (`normal` \| `medium` \| `burst`) |
| `--daily` | `SIM_LIVE_DAILY` | 25000 | `normal`의 하루 평균 가입 수. `medium`·`burst` 속도도 이 값에서 정해진다 |
| `--speed` | `SIM_LIVE_SPEED` | 1 | 시간 배속 (1 = 실시간) |
| `--duration` | | 계속 | **실제 시간** 기준 실행 초. 지나면 정상 종료 |
| `--max-signups` | | 없음 | 이 건수만큼 만들면 정상 종료 |
| `--control-file` | `SIM_CONTROL_FILE` | `.local/control.json` | 제어 신호 파일 |
| `--seed` | `SIM_SEED` | 42 | 기본 시드. 신규 회원은 여기서 **다른 줄기**로 파생한다 |

환경 변수 중 `DATABASE_URL`, `SIM_SEED`는 `.env`에서도 읽고, 나머지 `SIM_LIVE_*`, `SIM_CONTROL_FILE`은 실제 환경 변수로만 읽는다.

- **가입 간격**은 푸아송 과정(지수분포)이다. 속도는 `--daily ÷ 86,400 × rate_factor(모드, 시뮬레이터 시각)`건/초다. `rate_factor`는 `common/curve.py`에 있고, 방문(`behavior`)도 같은 함수를 쓴다.

  | 모드 | `rate_factor` (하루 평균 대비) | `--daily 25000`일 때 |
  |---|---|---|
  | `normal` (일상) | 요일 배율 × 시간대 배율 | 하루 평균 25,000명. 월요일 20시는 분당 약 28명 |
  | `medium` (중간) | 일상 피크 시간대 배율(1.8) × 3 = 5.4, 고정 | 시간당 5,625명 |
  | `burst` (폭주) | 일상 피크 시간대 배율(1.8) × 10 = 18, 고정 | 시간당 18,750명 |

  **곡선:** 요일 배율은 H&M 요일 비율 × 7(월 0.896 … 토 1.113, 한 주 평균 1), 시간대 배율은 우리가 정한 시간대 비율 ÷ 구간 길이(0~6시 0.20, 6~9시 0.64, 9~12시 1.12, 12~14시 1.32, 14~18시 1.02, 18~24시 1.80)다. 날짜와 시각은 KST 기준이고, 구간 안에서는 일정한 계단 함수다. 간격은 뽑은 시점의 속도로 뽑으므로 구간 경계에서 약간의 오차가 있다. `medium`·`burst`는 시간대·요일과 상관없이 고정이라 밤에 바꿔도 폭주가 된다. 자동 복귀(중간 60분, 폭주 15분)는 아직 없다(컨트롤러 작업).
- **제어 파일**을 약 1초마다 읽는다. 로컬에서는 이렇게 바꾼다.

  ```bash
  echo '{"running": true,  "mode": "burst"}'  > .local/control.json   # 폭주 (피크 시간대의 10배)
  echo '{"running": true,  "mode": "medium"}' > .local/control.json   # 중간 (피크 시간대의 3배)
  echo '{"running": true,  "mode": "normal"}' > .local/control.json   # 일상(곡선)으로 복귀
  echo '{"running": false, "mode": "normal"}' > .local/control.json   # 멈춤 (프로세스는 살아 있음)
  ```

  모드가 바뀌면 `mode: normal → burst` 한 줄이 출력되고 새 속도로 간격을 다시 뽑는다. 파일이 없거나 깨졌거나 값이 잘못되면 마지막 상태를 유지하고 경고를 한 번만 낸다. 제어 파일은 시작 상태(`--mode`)를 이후에 덮어쓴다.
- **제어 신호 전달 수단은 아직 정해지지 않았다.** 파일 방식은 로컬 개발용이고, 실제 수단은 컨트롤러 작업에서 `ControlSource`를 새로 구현해 붙인다.
- **배속과 시각:** `signup_at`은 시뮬레이터 시각(KST)이고 `created_at`은 DB가 기록한 실제 시각이다. 배속 1이면 거의 같고, 배속이 크면 어긋난다. 정상이다.
- **껐다 켜도 이어진다:** k번째 신규 회원은 `derive_seed(시드, "live", k)`로 난수를 다시 심어 만들어 값이 시드와 k만으로 정해진다. 시작할 때 k는 `members`에서 `signup_at >= 2026-10-01 00:00 KST`인 행 수로 센다(탈퇴는 행을 지우지 않으므로 줄지 않는다). 그래서 껐다 켜도 같은 순서로 이어지고 `member_id`가 겹치지 않는다. 시뮬레이터 시각이 10/1 KST보다 이르면 이 기준이 깨지므로 오류로 멈춘다.
- **전화번호:** 무작위로 뽑아 넣고, `member_phone_key` 위반이면 같은 난수 줄기에서 새 번호로 최대 10번 다시 시도한다(전화번호만 바뀐다). 다른 제약 위반은 재시도하지 않고 오류로 처리한다. 번호를 확인하려고 DB에서 읽어 오지 않는다.
- **종료:** `Ctrl+C`(SIGINT)나 SIGTERM이면 하던 INSERT를 끝내고 요약을 출력한 뒤 종료 코드 0으로 끝난다. DB 연결이 끊기면 1, 2, 4, … 최대 30초 간격으로 다시 연결한다.
- 실제 시간 10초마다 진행 한 줄(모드, 구간 건수와 초당 건수, 누적, 시뮬레이터 시각)을 출력한다. 회원 값(PII)은 출력하지 않는다.
- 이 명령으로 `member`에 신규 가입이 섞이면 `sim member verify`의 가입 기간·일별·시간대별 항목은 베이스라인 기준이라 실패할 수 있다.
- 확인 후 로컬에서 신규 가입만 지우려면: `DELETE FROM members WHERE signup_at >= '2026-10-01 00:00:00+09';`

## 행동 (behavior)

회원의 쇼핑 행동을 만들어 `orders`, `order_items`, `payments`에 쓴다. 회원(`members`)과 상품(`product_variant`)이 먼저 있어야 하고, 로컬 DB에 `db/schema/004_orders.sql`이 적용돼 있어야 한다.

```bash
docker compose exec -T postgres psql -U sim -d clothes < ../db/schema/004_orders.sql   # 처음 한 번
sim behavior live                                                  # normal, 실시간, 하루 평균 55만 5천 방문
sim behavior live --visits-daily 20000 --speed 1440 --duration 60 --click-sink jsonl
```

| 옵션 | 환경 변수 | 기본값 | 설명 |
|---|---|---|---|
| `--mode` | `SIM_LIVE_MODE` | `normal` | 시작 모드 (`normal` \| `medium` \| `burst`). `member live`와 같은 변수 |
| `--visits-daily` | `SIM_VISITS_DAILY` | 555000 | `normal`의 하루 평균 방문 수 |
| `--speed` | `SIM_LIVE_SPEED` | 1 | 시간 배속 |
| `--duration` | | 계속 | **실제 시간** 기준 실행 초 |
| `--max-visits` | | 없음 | 이만큼 방문을 만들면 정상 종료 |
| `--control-file` | `SIM_CONTROL_FILE` | `.local/control.json` | 제어 신호 파일 (`member live`와 **같은 파일**) |
| `--seed` | `SIM_SEED` | 42 | 기본 시드 |
| `--run-salt` | | 시작 시각의 epoch 초 | 실행 구분값 (아래) |
| `--click-sink` | `SIM_CLICK_SINK` | `none` | 클릭 로그 출력: `none`(버림), `jsonl`(파일), `kafka`(토픽 `clickstream`, 아래 "클릭 로그" 절) |
| `--click-file` | | `.local/clicks.jsonl` | `jsonl`일 때 경로. `.local/`은 커밋하지 않는다 |

- **흐름:** 방문이 푸아송으로 도착한다(속도 `--visits-daily ÷ 86,400 × rate_factor(모드, 시각)`, `member live`와 같은 곡선·모드 규칙). 방문마다 회원을 고르고 `session_id`를 붙여 조회(평균 약 5번) → 담기(15%) → 주문(담은 방문의 28%, 담기 없이 바로 주문 0.3%)으로 이어진다. 주문은 결제를 시도하고(실패하면 최대 3번까지 재시도) `PLACED → PAID → SHIPPED → DELIVERED`, 또는 취소·결제 실패·반품으로 바뀐다. 하루 55만 5천 방문이면 주문은 약 25,000건이다. `SHIPPED` 뒤 3~6시간에 `DELIVERED`가 된다.
- **값을 바꾸는 곳:** 확률, 분포, 지연은 모두 `src/sim/behavior/params.py` 한 곳에 있다. `[가정]` 표시는 팀과 맞추는 임시값이다.
- **쓰는 방식:** 주문과 그 상품 줄은 한 트랜잭션, 결제 INSERT와 상태 UPDATE는 한 건씩 자동 커밋이다. `orders.updated_at`과 모든 전이 시각은 **예정된 시뮬레이터 시각**이다(실제 UPDATE 시각이 아니다). 결제는 INSERT만 하고 환불도 결제 행을 만들지 않는다.
- **Sink 두 개:** 주문은 `OrderSink`(지금은 `DbOrderSink`, DB 직접 쓰기), 클릭은 `ClickSink`(`NullClickSink`, `JsonlClickSink`, `KafkaClickSink`)로 나간다. 나중에 쇼핑몰 API로 바꿀 때 같은 인터페이스(`behavior/sink.py`)를 구현해 `cli.py`에서 끼우면 된다. 클릭 로그 한 줄은 `event_id`, `event_type`(`view`/`cart_add`), `member_id`, `article_id`, `event_time`(UTC, `Z`로 끝남), `session_id`다.
- **제어 파일:** `member live`와 같은 파일을 약 1초마다 읽는다. 모드를 바꾸면 다음 방문 간격을 지금부터 다시 뽑고 `mode: normal → burst` 한 줄이 나온다. `{"running": false, ...}`는 **새 방문만 멈춘다.** 이미 예약된 클릭·결제·상태 전이는 계속 실행된다.
- **run_salt:** 같은 시드 + 같은 `run_salt` + 같은 시계 + 같은 제어 순서이면 결과가 완전히 같다. 기본값이 시작 시각이라 재시작마다 달라지고, 그래서 `order_id`·`payment_id`가 이전 실행과 겹치지 않는다. 시작 출력에 항상 보인다.
- **알려진 한계: 재시작하면 진행 중이던 주문이 멈춘다.** 예약된 결제·상태 전이는 메모리 큐에만 있고 DB에서 복구하지 않는다. 껐다 켜면 그때 `PLACED`, `PAID`, `SHIPPED`였던 주문은 그 상태로 남는다.
- **원격 DB:** 접속 대상이 `localhost`/`127.0.0.1`이 아니면 실행을 거부한다. ECS에서 RDS에 붙을 때는 `SIM_ALLOW_REMOTE_DB=1`을 명시한다. 오류 메시지에는 호스트와 비밀번호를 싣지 않는다.
- **오류와 종료:** DB 연결이 끊기면 실패한 항목을 큐 맨 앞에 되돌리고 1, 2, 4, … 최대 30초 간격으로 다시 연결한 뒤 그 항목부터 이어서 한다. 다시 할 때 `23505`(PK/UNIQUE 위반)는 이미 반영된 것으로 본다. SIGINT/SIGTERM이면 하던 항목을 끝내고 요약(남은 큐 건수 포함)을 출력한 뒤 종료 코드 0으로 끝난다.
- **출력:** 실제 시간 10초마다 진행 한 줄(모드, 구간 방문·주문·결제 시도, 누적, 큐 길이, 시뮬레이터 시각). 회원 값은 읽지도 출력하지도 않는다(회원은 `member_id`만 읽는다).
- 확인 후 로컬에서 거래 행을 지우려면: `DELETE FROM payments; DELETE FROM order_items; DELETE FROM orders;`

## 컨트롤러 (controller)

시연자가 버튼(또는 명령)으로 모드와 장애를 바꾸고, 바꾸기 **전에** 정답표(`incident_log`)를 JSON으로 남긴다. 정답표는 AI 조사 에이전트가 맞혀야 할 답이라, 기록이 실패하면 아무것도 바꾸지 않는다. 컨트롤러는 제어 파일만 쓰고(데이터 오염만 DB에 직접 쓴다), 실행 중인 `sim member live`와 `sim behavior live`가 1초마다 그 파일을 읽어 따라 움직인다.

```bash
sim controller serve                                   # http://127.0.0.1:8080 (버튼 화면)
sim controller mode burst                              # 다른 터미널에서
sim controller pg-outage --pg PG_B --extra-fail 0.85 --minutes 10
sim controller pollution --kind ORDER_TOTAL_MISMATCH --count 30
sim controller end                                     # 진행 중 사건 종료
```

| 명령 | 동작 |
|---|---|
| `serve` | 서버를 켠다. `--host`(`SIM_CONTROLLER_HOST`, 기본 `127.0.0.1`), `--port`(`SIM_CONTROLLER_PORT`, 기본 8080), `--control-file`(기본 `.local/control.json`), `--incident-log file\|s3`(기본 `file`), `--incident-dir`(기본 `.local/incident_log`), `--medium-minutes`(`SIM_MEDIUM_MINUTES`, 기본 60), `--burst-minutes`(`SIM_BURST_MINUTES`, 기본 15, 소수 허용) |
| `status` | 현재 상태 |
| `mode <normal\|medium\|burst>` | 모드 전환 |
| `running <true\|false>` | 새 가입·방문 멈춤/재개 |
| `pg-outage --pg PG_B [--extra-fail 0.85] [--minutes 10]` | PG 장애 시작 |
| `pollution [--kind ORDER_TOTAL_MISMATCH] [--count 30]` | 데이터 오염 |
| `end` | 진행 중 사건 종료 |

`serve` 밖의 명령은 `--url`(`SIM_CONTROLLER_URL`, 기본 `http://127.0.0.1:8080`)로 서버를 HTTP로 부르는 얇은 클라이언트다. 파일을 쓰는 곳은 서버 하나다.

**제어 파일** (`member live`, `behavior live`가 같은 파일을 읽는다):

```json
{"running": true, "mode": "normal", "pg_extra_fail": {"PG_B": 0.85}}
```

`pg_extra_fail`(PG 이름 → 그 PG의 PG 원인 실패 확률 추가분, 0~1)은 없어도 된다. 값이 틀리면 파일 전체를 잘못된 값으로 보고 마지막 상태를 유지한다. `behavior live`는 바뀌면 `pg_extra_fail: {} → {"PG_B": 0.85}` 한 줄을 출력하고, 그 뒤에 시작하는 결제 시도부터 적용한다. `member live`는 이 항목을 무시한다. 컨트롤러는 임시 파일에 쓴 뒤 `os.replace`로 바꿔, 읽는 쪽이 반쯤 쓴 파일을 보지 않는다.

**사건 종류** (한 번에 하나만 진행한다. 진행 중에 다른 사건을 요청하면 409. 일시정지는 예외):

| 사건 | 만드는 법 | 끝나는 때 |
|---|---|---|
| `INGEST_LAG` | `mode burst` (적재 지연이 목적) | 15분 뒤 자동으로 `normal`, 또는 `mode normal` |
| `TRAFFIC_SURGE` | `mode medium` (약한 급증) | 60분 뒤 자동으로 `normal`, 또는 `mode normal` |
| `PG_OUTAGE` | `pg-outage` (PG 하나, 기본 추가 실패율 0.85, 10분, 최대 60분) | 정한 시간 뒤 자동, 또는 `end` |
| `DATA_POLLUTION` | `pollution` (기본 30건, 최대 500건) | 즉시 (`complete`) |
| `OPERATOR_PAUSE` | `running false` (사건은 아니지만 트래픽 공백이 장애로 오해되지 않게 남긴다) | `running true` |

**데이터 오염**은 DB 제약(CHECK, UNIQUE, FK)은 통과하지만 업무 규칙을 어기는 행만 만든다. 스키마 변경은 하지 않는다. 한 종류의 오염은 한 트랜잭션이다.

| 종류 | 하는 일 | 어기는 규칙 |
|---|---|---|
| `ORDER_TOTAL_MISMATCH` | `PAID`·`SHIPPED`·`DELIVERED` 중 가장 최근 주문의 `total_amount`에 10,000을 더한다 (`updated_at`은 그대로) | 주문 총액 = 항목 합계 = 결제 금액 |
| `DUPLICATE_SUCCESS_PAYMENT` | SUCCESS 결제가 있는 최근 주문에 같은 수단·PG·금액의 SUCCESS 결제를 한 건 더 넣는다 (`attempt_no`는 최대 + 1) | 주문당 SUCCESS 결제는 1건 |

**정답표**는 레코드 하나를 파일 하나로 쓴다. 로컬은 `.local/incident_log/YYYYMMDDTHHMMSSZ_<incident_id>_<phase>.json`, S3는 키 접두어 `ground_truth/incident_log/`(`--incident-log s3`, `S3_BUCKET` 필요)다. 시각은 UTC다.

```json
{"schema_version": 1, "incident_id": "…", "phase": "start", "type": "PG_OUTAGE", "at": "2026-10-18T08:12:00Z", "params": {"pg": "PG_B", "extra_fail": 0.85, "planned_minutes": 10.0}}
{"schema_version": 1, "incident_id": "…", "phase": "end", "type": "PG_OUTAGE", "at": "2026-10-18T08:22:00Z", "ended_by": "timer", "result": {}}
```

`ended_by`는 `timer`, `manual`, `shutdown`, `complete`, `failed`(적용 실패) 중 하나다. 오염의 `result`에는 `kind`, `affected_count`, `order_ids`(최대 500개)가 들어간다. 회원 정보, 접속 정보, 버킷 이름은 넣지 않는다. 기록 순서는 "시작 기록 → 바꾸기"이고, 끝은 "되돌리기 → 끝 기록"이다. 끝 기록이 실패하면 1초마다 다시 쓴다.

- **인증:** `/api/*`는 `Authorization: Bearer <SIM_CONTROLLER_TOKEN>`이 필요하다. 로컬(`127.0.0.1`)에 열 때만 토큰 없이 켤 수 있고, 다른 주소에 열면서 토큰이 없으면 시작하지 않는다. `/healthz`는 토큰 없이 `{"ok": true}`다. 버튼 화면은 운영자용이라 정답표 내용(`result`)은 보여 주지 않는다.
- **데이터 오염**은 `DATABASE_URL`이 있을 때만 켜진다(없으면 오염 요청만 503). 로컬이 아니면 `SIM_ALLOW_REMOTE_DB=1`이 필요하다.
- **시각:** 컨트롤러는 벽시계(UTC)만 쓴다. ECS에서는 실행기를 `--speed 1`로 돌린다. 배속이 1이 아니면 정답표 시각과 데이터 시각이 어긋난다.
- **종료와 재시작:** SIGINT/SIGTERM이면 진행 중 사건을 `shutdown`으로 끝내고 제어 파일을 `normal`, 장애 없음으로 되돌린 뒤 종료 코드 0으로 끝난다. 다시 켜면 깨끗한 상태로 시작한다.
- **알려진 한계:** 비정상 종료(강제 종료)하면 진행 중이던 사건의 끝 기록이 남지 않는다. 컨트롤러를 다시 켜도 그 사건을 복구하지 않는다.

## 클릭 로그 (clickstream)

방문 중에 생기는 조회(`view`)와 장바구니 담기(`cart_add`)를 Kafka 토픽 `clickstream`에 직접 발행한다. 주문·결제·회원은 지금처럼 DB에만 쓰고(Debezium이 Kafka로 보낸다), **클릭만 예외**다. 클릭은 DB에 넣지 않는다. EKS에서는 S3 Sink(`connectors/bronze-s3-sink.yaml`)가 다른 업무 토픽과 함께 `bronze/clickstream/`에 쌓는다(`sim/cdc-orders`). ECS에서 EKS Kafka로 보내는 경로는 아직 없다.

```bash
docker compose --profile cdc up -d kafka
sim clickstream setup                       # 토픽 만들기 (처음 한 번)
sim behavior live --visits-daily 20000 --speed 1440 --duration 60 --click-sink kafka
sim clickstream status                      # 파티션별 offset과 합계
sim clickstream verify                      # 내용·순서·중복 확인
sim clickstream reset --yes                 # 토픽 지우기 (로컬만)
```

**메시지 모양:** 토픽 `clickstream`(파티션 3, 보관 72시간), 키는 `session_id`(UTF-8), 값은 한 건당 JSON 하나다. `--click-sink jsonl`의 한 줄과 **같은 6개 필드**다.

```json
{"event_id":"<uuid>","event_type":"view","member_id":"<uuid>","article_id":"0108775015","event_time":"2026-10-19T06:20:01.123456Z","session_id":"<uuid>"}
```

- 키가 `session_id`라서 같은 방문의 `view` → `cart_add` 순서가 한 파티션 안에서 지켜진다. PII는 없다(`member_id`, `article_id`뿐). 메시지 내용은 로그·콘솔에 출력하지 않는다.
- Kafka 레코드 시각은 프로듀서 기본값(보낸 시각)이다. `ingest_time`은 파이프라인이 붙이므로 메시지에 넣지 않는다.

| 명령 | 하는 일 |
|---|---|
| `sim clickstream setup` | 토픽이 없으면 만든다(파티션 3, 복제 1, `retention.ms=259200000`). 있으면 그대로 두고 설정이 다르면 알린다. **로컬 부트스트랩에서만** 한다 |
| `sim clickstream status` | 토픽 존재 여부, 파티션별 low/high offset, 합계. 토픽이 없으면 종료 코드 1 |
| `sim clickstream verify` | 처음부터 **실행 시점의 끝까지** 한 번 읽는다(임시 컨슈머 그룹, offset 저장 없음). 아래 확인 중 하나라도 실패면 종료 코드 1, 메시지가 0건이면 "비어 있음"으로 종료 코드 2 |
| `sim clickstream reset --yes` | 토픽을 지운다. `--yes`가 없으면 하지 않는다. **로컬 부트스트랩에서만** 한다 |

`verify`가 확인하는 것: ① 모든 메시지가 JSON이고 6개 필드가 있다 ② `event_type`이 `view` 또는 `cart_add` ③ 메시지 키 = 값의 `session_id` ④ 같은 `session_id`는 한 파티션에만 있다 ⑤ `event_id` 중복 없음 ⑥ 같은 파티션·세션 안에서 `event_time`이 줄어들지 않는다 ⑦ 0건이면 비어 있음. 틀린 메시지는 파티션·offset(`p2@17`)만 알리고 내용은 출력하지 않는다.

- **발행 실패는 버리고 센다.** 클릭이 주문 흐름(DB)을 멈추게 하면 안 되기 때문이다. 전송이 실패해도 예외를 던지지 않고, 처음 실패할 때 경고를 한 번만 출력한 뒤 건수만 센다. 종료 요약에 `클릭 발행: 성공 N건, 실패 M건`이 나온다. Kafka가 잠깐 끊겼다 돌아오면 프로듀서가 다시 연결해 새 클릭부터 다시 쌓인다(끊긴 동안 10초 넘게 못 보낸 클릭은 실패로 센다). 끊기는 순간 실제로는 기록됐지만 응답을 못 받은 메시지도 실패로 세므로, 끊김이 있었으면 **실패 건수는 상한값**이다(토픽 건수가 성공 건수보다 조금 많을 수 있다. 중복은 생기지 않는다).
- **시작할 때 확인:** `--click-sink kafka`는 시작할 때 브로커와 토픽을 한 번 확인한다. 닿지 않거나 토픽이 없으면 방문을 시작하지 않고 종료 코드 1이다. 이 확인은 토픽을 만들지 않는다(`allow.auto.create.topics=false`).
- **프로듀서 설정:** `acks=all`, `enable.idempotence=true`, `linger.ms=50`, `message.timeout.ms=10000`. 종료할 때(`Ctrl+C`/SIGTERM 포함) 최대 30초 동안 남은 메시지를 보낸다.

| 환경 변수 | 기본값 | 설명 |
|---|---|---|
| `KAFKA_BOOTSTRAP` | `localhost:29092` | 브로커 주소. 출력하지 않는다 |
| `KAFKA_SECURITY_PROTOCOL` | `PLAINTEXT` | `PLAINTEXT` 또는 `SSL` |
| `KAFKA_SSL_CA_FILE` | | CA 인증서 경로 (`SSL`일 때) |
| `KAFKA_SSL_CERT_FILE`, `KAFKA_SSL_KEY_FILE` | | 클라이언트 인증서·키 경로 (mTLS, 둘은 함께) |

- **TLS는 로컬에서 검증하지 않았다.** 환경 변수를 librdkafka 설정(`ssl.ca.location` 등)으로 연결하는 데까지만 했다.
- **ECS에서 EKS 안 Kafka로 가는 경로는 아직 없다.** Kafka가 EKS 내부 전용이라 Fargate에서 닿지 않는다. 경로(내부 NLB, 클라이언트 인증서 공급, 네트워크 규칙)는 인프라와 `sim/ecs-image`에서 정한다.
- **시각:** 클릭 `event_time`은 UTC(`Z`로 끝남)로 나간다(`jsonl`도 같다). "Bronze는 UTC, Silver에서 KST로 한 번만 바꾼다" 규칙과 Debezium 시각 표기에 맞췄다(`sim/cdc-orders`, 이전에는 `+09:00`).
- **알려진 한계:** 재시작하면 메모리 큐에 예약돼 있던 클릭은 발행되지 않는다(주문과 같은 한계).

## 업무 API로 쓰기 (`--backend api`)

`sim member live`와 `sim behavior live`는 RDS에 직접 쓰는 대신 **업무 API(`api/`)**로 쓰고 읽을 수 있다. 이 경우 시뮬레이터에 DB 계정이 필요 없다(`DATABASE_URL` 불필요). 기본은 지금처럼 `--backend db`다.

```bash
export SIM_BACKEND=api                 # 또는 --backend api
export SIM_API_URL=http://localhost:8000
sim member live --speed 60
sim behavior live --click-sink api --speed 60 --visits-daily 20000 --duration 120   # 실제 2분: 주문 약 80건
```

`--max-visits`로 짧게 끊으면 주문·결제가 거의 실행되지 않는다. 배속 60이면 방문 300이 몇 초 만에 차서, 조회 뒤에 예약된 주문·결제가 실행되기 전에 끝나기 때문이다(종료 요약의 `남은 큐`).

| 무엇 | `--backend api`일 때 |
|---|---|
| 가입 | `POST /v1/members`. 시작 위치는 `GET /v1/members/signup-count`. 전화번호 중복(`PHONE_TAKEN`)이면 지금처럼 번호를 다시 뽑는다 |
| 주문·결제·상태 | `POST /v1/orders`, `POST /v1/orders/{id}/payments`, `PATCH /v1/orders/{id}`. ID·시각·결제 결과는 시뮬레이터가 정해 보낸다 |
| 회원 목록 | 시작 때 `GET /v1/members/active` 전체, 그다음 **5초마다** `GET /v1/members/changes` 변경분만 (지금의 60초마다 전체 다시 읽기 대신) |
| 상품 목록 | 시작 때 `GET /v1/catalog` 한 번 |
| 클릭 | `--click-sink api`: **1초 또는 500건**마다 `POST /v1/events/clicks`로 묶어 보낸다. API가 `clickstream`에 발행한다. 실패한 묶음은 버리고 센다(경고 1회). 종료 요약에 `클릭 전송(API)` 줄 |
| API가 닿지 않음·5xx·503 | 그 항목부터 1, 2, 4, … 최대 30초 간격으로 다시 시도한다. ID가 고정이라 다시 보내도 중복이 생기지 않는다(같은 내용이면 API가 200) |
| 회원 비활성(409 `MEMBER_NOT_ACTIVE`) | 그 주문을 버리고 회원을 목록에서 뺀다. 종료 요약의 `주문` 줄에 거절 수 |
| 그 밖의 4xx(검증 실패, `ID_CONFLICT`) | 멈춘다(시뮬레이터 버그다). 오류 코드만 출력한다 |

- 출력에는 API 호스트만 나오고 요청 본문(가입 PII)은 나오지 않는다.
- 컨트롤러의 데이터 오염 주입은 지금처럼 DB에 직접 쓴다(API를 거치지 않는다).
- **EKS의 API에 붙이기**: Windows PowerShell에서 `kubectl port-forward --address 0.0.0.0 -n api svc/api 8000:80`을 켜고, WSL에서는 Windows 호스트 주소로 접속한다(`SIM_API_URL=http://$(ip route show default | awk '{print $3}'):8000`). WSL을 mirrored 네트워킹으로 쓰면 `http://localhost:8000`도 된다. 이렇게 돌린 주문은 **실제 RDS에 남는 실제 시뮬레이션 데이터**다.

## ECS에서 실행 (`sim/ecs-image`)

ECS Fargate 태스크 1개에 같은 이미지 컨테이너 3개(`controller`, `member`, `behavior`)가 돌고, 공유 볼륨 `/control`의 `control.json`으로 소통한다. 시뮬레이터는 내부 ALB를 거쳐 업무 API로만 쓰고 읽는다(`--speed 1`, 실제 시각). 예외로 컨트롤러의 데이터 오염만 RDS에 직접 쓴다(오염 전용 계정 `clothes_sim_admin`). 인프라는 `infra/stacks/ecs-simulator`(README에 apply 순서).

**이미지** (`Dockerfile`): 베이스 digest 고정, 비root(10001), RDS CA 묶음 `/etc/ssl/rds/ap-northeast-1-bundle.pem`(sha256 고정), `/control`은 비root가 쓸 수 있게 `VOLUME`으로 둔다. `.dockerignore`로 `.env`·`.local`(PII 시드)·`.venv`를 빌드 컨텍스트에서 뺀다.

순서 (Windows PowerShell, 레포 루트. kubectl 쓰는 단계는 관리자 kubeconfig):

1. **ECS 기반 apply**: `infra/stacks/ecs-simulator` README 1단계(이미지 없이). 출력 `ecr_repository_url`, `security_group_id`, `secret_name`을 적어 둔다.
2. **오염 계정**:
   ```powershell
   $pw = aws secretsmanager get-random-password --password-length 32 --exclude-punctuation --query RandomPassword --output text --region ap-northeast-1
   $pw | Set-Clipboard
   ```
   DBeaver(마스터, `postgres` DB)에서 `simulator/deploy/sql/sim-admin-account.sql`의 `BEGIN;`~`COMMIT;`을 실행한다(`'여기에_붙여넣기'` 안쪽에 붙여 넣기). 이어서 접속 문자열을 Secret에 넣는다.
   ```powershell
   $rdsHost = aws rds describe-db-instances --db-instance-identifier clothes-query-dev-rds --query "DBInstances[0].Endpoint.Address" --output text --region ap-northeast-1
   $tmp = "E:\sim-db-" + [guid]::NewGuid() + ".txt"
   [IO.File]::WriteAllText($tmp, "postgresql://clothes_sim_admin:${pw}@${rdsHost}:5432/postgres?sslmode=verify-full&sslrootcert=/etc/ssl/rds/ap-northeast-1-bundle.pem")
   aws secretsmanager put-secret-value --secret-id clothes-query-dev-ecs-simulator/sim-admin-database-url --secret-string "file://$tmp" --region ap-northeast-1
   Remove-Item $tmp; Remove-Variable pw, rdsHost, tmp
   ```
3. **RDS 허용**: `infra/stacks/rds`의 비공개 입력 `database_clients`에 `"ecs-simulator": "<security_group_id>"`를 넣고 rds plan(인바운드 규칙 1개 추가뿐) → apply.
4. **이미지 push**:
   ```powershell
   $acct = aws sts get-caller-identity --query Account --output text
   $repo = "$acct.dkr.ecr.ap-northeast-1.amazonaws.com/clothes-query-dev/simulator"
   $tag = "sim-" + (git rev-parse --short HEAD)
   aws ecr get-login-password --region ap-northeast-1 | docker login --username AWS --password-stdin "$acct.dkr.ecr.ap-northeast-1.amazonaws.com"
   docker build --platform linux/amd64 -t "${repo}:$tag" simulator
   docker push "${repo}:$tag"
   $digest = aws ecr describe-images --repository-name clothes-query-dev/simulator --image-ids imageTag=$tag --query "imageDetails[0].imageDigest" --output text --region ap-northeast-1
   docker logout "$acct.dkr.ecr.ap-northeast-1.amazonaws.com"
   $digest
   ```
5. **태스크 띄우기**: ECS 스택 비공개 입력에 `image_digest`(위 `$digest`)와 `api_url`(`http://` + `kubectl get ingress api -n api`의 주소)을 넣고 plan(태스크 정의·서비스 2개 추가) → apply.
6. **API ALB 좁히기**: `api/deploy/chart/runtime.local.yaml`의 `inboundCIDRs`를 app subnet 두 대역(network 비공개 입력의 `subnets`)으로 바꾸고 `helm upgrade --install api …`(`api/README.md` 6단계).

확인:

```powershell
$c = "clothes-query-dev-ecs-simulator"
aws ecs describe-services --cluster $c --services $c --query "services[0].{run:runningCount,want:desiredCount,events:events[0:3].message}" --region ap-northeast-1
aws logs tail "/ecs/$c" --since 10m --region ap-northeast-1     # 세 컨테이너의 [진행] 줄, 오류 없음
```

- 컨테이너 3개 RUNNING, 재시작 없음. `behavior` 진행 줄에 방문·주문·클릭, `member`에 가입
- 15분 안에 S3 `bronze/clickstream/`, `bronze/orders/` 등에 새 파일

**컨트롤러 화면** (ECS Exec 포트 포워딩, PC에 [Session Manager 플러그인](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html) 필요):

```powershell
$c = "clothes-query-dev-ecs-simulator"
$task = aws ecs list-tasks --cluster $c --service-name $c --query "taskArns[0]" --output text --region ap-northeast-1
$rid = aws ecs describe-tasks --cluster $c --tasks $task --query "tasks[0].containers[?name=='controller'].runtimeId | [0]" --output text --region ap-northeast-1
aws ssm start-session --target "ecs:${c}_$($task.Split('/')[-1])_$rid" --document-name AWS-StartPortForwardingSession --parameters "portNumber=8080,localPortNumber=8080" --region ap-northeast-1
```

켜 둔 채로 브라우저 `http://localhost:8080`. 다른 창에서 `sim controller …` 명령도 같은 주소로 된다(`SIM_CONTROLLER_URL` 기본값).

- 멈추기: ECS 스택 `desired_count = 0`으로 apply. 다시 띄우면 메모리에 있던 예약(결제·배송 전이)은 사라진다(알려진 한계).
- 새 이미지: 4단계 → `image_digest`만 바꿔 apply. 서비스는 옛 태스크를 먼저 내리고 새 태스크를 띄운다(두 개가 겹치지 않음).

## 로컬 CDC

로컬 `members` 테이블을 Debezium이 읽어 Kafka 토픽 `members-events`로 흘리고, 그 결과가 설계대로인지(특히 PII가 한 글자도 안 나가는지) `sim cdc verify`로 확인한다. `verify`가 토픽을 직접 읽어 "Bronze에 들어갈 모양"을 검증한다. 커넥터 설정은 `connectors/`에 있다 (`connectors/README.md`).

```bash
sim member baseline --yes                  # 1. 베이스라인 10만 명 (이미 있으면 생략)
docker compose --profile cdc up -d         # 2. Kafka, Connect(Debezium), Kafka UI를 추가로 켬
sim cdc setup                              # 3. 커넥터 등록 → 10만 명이 스냅샷(op=r)으로 흐름
sim member live --mode normal --max-signups 200 --speed 1440   # 4. 신규 가입 → op=c
sim cdc verify --live-expected 200         # 5. 13개 항목 확인, 하나라도 실패하면 종료 코드 1
```

`docker compose up -d`만 하면 Postgres만 뜬다 (Kafka 쪽은 프로필 `cdc`).

| 명령 | 설명 |
|---|---|
| `sim cdc setup [--config PATH]` | 안전장치 검사(`column.include.list`가 정확히 10컬럼, `exclude.list` 없음, 테이블 하나, 비밀번호는 `${env:...}`)를 통과해야 등록한다. `members`가 0행이면 멈춘다. 같은 이름의 커넥터가 이미 있으면 **아무것도 바꾸지 않고** 상태만 보여 준다 |
| `sim cdc status` | 커넥터·task 상태, 복제 슬롯(활성 여부, **밀린 WAL 크기**), publication의 테이블, `members-events` 파티션별 건수 (읽기 전용) |
| `sim cdc verify [--snapshot-expected 100000] [--live-expected N]` | 토픽을 처음부터 읽어(읽어도 offset을 남기지 않는다) 13개 항목을 확인한다. 실패해도 회원 값은 출력하지 않고 필드 이름, 건수, 최대 5개의 `member_id`만 보여 준다 |
| `sim cdc reset [--yes]` | **로컬 전용.** 커넥터 정지 → offset 삭제 → 커넥터 삭제 → 슬롯·publication 삭제 → 토픽 삭제. `members` 행은 건드리지 않는다 |

- **`reset`이 필요한 경우:** 스냅샷을 다시 하고 싶을 때, 설정을 잘못 넣었을 때. **커넥터 offset을 지우지 않으면 같은 이름으로 다시 만들어도 "이미 스냅샷함"으로 보고 스냅샷을 건너뛴다.** `reset`이 offset까지 지우는 이유다. 컬럼을 바꿀 때도 `reset` 후 `setup`을 한다.
- **`members` 행을 지울 때는 커넥터를 먼저 `reset`한다.** 켜 둔 채 지우면 삭제(`d`) 이벤트가 토픽에 생긴다.
- **메시지 모양:** Debezium 봉투를 벗기고 `after`의 값을 펼친 한 행이다. 컬럼 10개 + 관리 컬럼 3개 `__op`(`r`/`c`/`u`), `__source_ts_ms`(epoch 밀리초), `__source_snapshot`(스냅샷 행은 `first`/`true`/`last`, 스냅샷이 아닌 이벤트는 `null`). 시각은 UTC(`...Z`)다. 키는 `member_id`.
- **주소가 둘이다:** 컨테이너끼리는 `kafka:9092`, WSL(파이썬 CLI)에서는 `localhost:29092`. 헷갈리면 컨테이너 안에서는 되는데 밖에서 접속이 안 된다(또는 그 반대). 환경 변수는 `CONNECT_URL`(기본 `http://localhost:8083`), `KAFKA_BOOTSTRAP`(기본 `localhost:29092`).
- **Kafka UI:** `http://127.0.0.1:8080`. 토픽과 커넥터를 눈으로 본다 (`127.0.0.1`에만 열려 있다).
- **메모리:** Kafka, Connect, Kafka UI 합쳐서 약 1.5GB를 쓴다 (힙 상한 512MB·512MB·384MB). 쓰지 않을 때는 `docker compose --profile cdc stop kafka connect kafka-ui`.
- **자주 막히는 곳:** 토픽 파티션은 3개다 (`topic.creation.default.partitions=3`). 처음 구성할 때 1개로 나온 적이 있어 원인은 확인하지 못했다. 비밀번호는 커넥터 JSON이 아니라 Connect 컨테이너의 환경 변수 `CDC_DB_PASSWORD`로 준다.
- **Kafka 데이터 파일을 직접 grep할 때:** `.log` 파일만 대상으로 한다 (`.index`는 10MB씩 미리 잡힌 희소 파일이라 전체를 읽으면 오래 걸린다). 전화번호 정규식(`010-[0-9]{4}-[0-9]{4}`)은 member_id(UUID) 안에서 우연히 걸릴 수 있으니, 걸리면 UUID 모양을 지운 뒤에도 걸리는지 본다.
- 이 구성은 로컬 전용이다. RDS, MSK는 인프라 작업에서 다룬다.

## S3 Sink

Kafka 토픽 `members-events`를 **S3의 `bronze/`에 JSON Lines 파일로 쌓는** Confluent S3 Sink 커넥터를 로컬 Connect에 붙이고, 쌓인 파일이 설계대로인지 `sim sink verify`로 확인한다. 커넥터 설정은 `connectors/member-s3-sink.json`이다 (값마다 이유와 IAM 정책 예시는 `connectors/README.md`).

```
시뮬레이터 → Postgres → Debezium → Kafka 토픽 → S3 Sink → S3
                                                   └ bronze/members-events/year=YYYY/month=MM/day=DD/*.json
```

```bash
# 1. simulator/.env에 키를 둔다 (S3_BUCKET, AWS_REGION, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY). 커밋하지 않는다
docker compose --profile cdc build connect   # 2. Connect 이미지에 S3 Sink 플러그인을 넣는다 (처음 한 번)
docker compose --profile cdc up -d           # 3. 켠다
sim sink setup                               # 4. S3 접근 확인 → 커넥터 등록
sim sink status                              # 5. S3에 파일이 생기는지 본다
sim sink verify                              # 6. 11개 항목 확인, 하나라도 실패하면 종료 코드 1
```

| 명령 | 설명 |
|---|---|
| `sim sink setup [--config PATH]` | 안전장치 검사(토픽이 source와 같음, 자격 증명 키·문자열 없음, 버킷 이름이 `${env:S3_BUCKET}` 참조, UTC 일별 `year=/month=/day=` 파티션, JSON 형식)와 **S3 접근 확인**(버킷·`bronze/` 조회)을 통과해야 등록한다. 같은 이름의 커넥터가 있으면 **아무것도 바꾸지 않고** 상태만 보여 준다 |
| `sim sink status` | 커넥터·task 상태, **소비자 그룹이 얼마나 밀렸는지**, 버킷 공개 차단 설정(조회 권한이 있을 때), `bronze/members-events/` 아래 날짜별 파일 수·크기·가장 최근 파일 시각 (읽기 전용. 객체 내용은 읽지 않는다) |
| `sim sink verify` | S3 파일과 토픽을 대조해 11개 항목을 확인한다. 아직 쓰는 중(밀림 > 0, 또는 마지막 파일 이후 30초 미만. 파일을 15분마다 끊어서 방금 가입한 건은 최대 15분 뒤에 S3에 보인다)이면 실패가 아니라 **종료 코드 2**로 "잠시 뒤 다시"라고 알린다 |
| `sim sink reset [--yes]` | 커넥터 정지 → 소비자 그룹 offset 삭제 → 커넥터 삭제. **S3 객체는 건드리지 않는다.** 지우는 `aws s3 rm` 명령을 출력만 한다 |

- **경로 규칙:** `bronze/members-events/year=YYYY/month=MM/day=DD/members-events+<파티션>+<시작offset>.json`. **날짜 폴더는 Kafka 레코드 시각(수집 시각, UTC)이고 가입일이 아니다.** 가입일은 값의 `signup_at`에 있다.
- **파일을 끊는 조건:** 15분마다(벽시계) 또는 파티션 파일 하나가 10,000건이 되면. 방금 만든 가입을 바로 확인하려면 `connectors/member-s3-sink.json`의 `rotate.schedule.interval.ms`를 임시로 `30000`으로 바꿔 등록한다 (확인이 끝나면 되돌린다).
- **at-least-once다.** 재시작·오류 뒤에 같은 메시지가 파일에 두 번 들어갈 수 있다. Silver에서 `member_id` 기준으로 중복을 제거한다. `verify`는 겹친 구간과 초과 행을 "중복 N건"으로 보고만 한다.
- **`reset` 뒤에 다시 `setup`하면 같은 데이터가 S3에 한 번 더 쌓인다.** 토픽을 처음부터 다시 읽기 때문이다. 먼저 S3 파일을 지울지 정한다.
- **자격 증명을 파일에 쓰지 않는다.** 키와 버킷 이름은 `simulator/.env`(gitignore)에만 두고, compose는 `connect` 서비스에 환경 변수를 **이름만** 넘긴다. 커넥터 JSON에는 키도 버킷 이름도 없다. `docker compose config`와 `env` 출력에는 키 값이 나오니 화면 공유나 로그에 쓰지 않는다.
- **`.env` 줄 이름:** `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`다 (`AWS_ACCESS_KEY` 같은 이름은 읽히지 않는다).
- **S3 쓰기·삭제 코드는 없다.** `sim sink`의 S3 접근은 읽기 전용이다 (쓰는 것은 Connect의 S3 Sink 커넥터다).
- **플러그인:** Confluent S3 Sink 12.1.13 (Confluent Community License, 로컬 사용). 버전과 체크섬은 `connect/Dockerfile`에 고정돼 있다.

## 상품 적재

팀이 EDA로 정리한 **상품 시드 Parquet 2개**를 로컬 PostgreSQL의 `product_design`, `product_variant`에 **그대로 옮기고**, 옮겨진 것이 원본과 같은지 확인한다. 회원과 달리 **새로 만들지 않는다.** 값을 고치거나 걸러내지 않고, 랜덤도 시드도 없다.

```
simulator/.local/seed_v2/product_design.parquet   ┐
simulator/.local/seed_v2/product_variant.parquet  ┴→ sim product load → Postgres (product_design, product_variant)
```

**원본:** S3 `hm-ecommerce-data`(도쿄)의 `seed_v2/product_design/product_design.parquet`, `seed_v2/product_variant/product_variant.parquet`가 기준이다. 레포에는 커밋하지 않는다. 로컬 파일이 기본 입력이고, 받는 것은 사용자가 한다 (명령이 자동으로 받지 않는다).

```bash
mkdir -p .local/seed_v2        # simulator/ 에서 (.local/은 gitignore)
aws s3 cp s3://hm-ecommerce-data/seed_v2/product_design/product_design.parquet   .local/seed_v2/
aws s3 cp s3://hm-ecommerce-data/seed_v2/product_variant/product_variant.parquet .local/seed_v2/
```

**테이블 만들기:** DDL은 `db/schema/003_product.sql`이다. `docker-entrypoint-initdb.d`에 마운트돼 있지만 **이미 만들어진 볼륨에서는 다시 실행되지 않는다.** 그래서 이미 쓰던 DB에는 직접 적용한다 (회원 테이블은 건드리지 않고 새 테이블 2개만 추가한다). 새 볼륨에서는 자동으로 적용된다.

```bash
docker compose exec -T postgres psql -U sim -d clothes < ../db/schema/003_product.sql
```

```bash
sim product load --dry-run     # DB에 접속하지 않고 두 파일의 컬럼·행 수만 본다
sim product load --yes         # 한 트랜잭션에 적재 (design 먼저, variant 나중)
sim product verify             # 원본과 DB를 둘 다 읽어 8개 항목 확인, 하나라도 실패하면 종료 코드 1
```

| 옵션 | 설명 |
|---|---|
| `--source` | 원본 디렉터리 또는 `s3://버킷/seed_v2` (기본: `SEED_DIR`, 없으면 `.local/seed_v2`). 디렉터리는 `<디렉터리>/<테이블>.parquet`, S3는 `<접두사>/<테이블>/<테이블>.parquet`를 읽는다 |
| `--dry-run` | (`load`) DB에 접속하지 않고 스키마와 행 수만 보여 준다 |
| `--yes` | (`load`) 확인 질문을 건너뛴다 |
| `--batch-size` | (`load`) COPY 배치 크기 (기본 5,000) |

- **스키마 확인:** `load`와 `verify`는 먼저 Parquet의 컬럼·타입이 DDL과 같은지 본다. 다르면(컬럼 추가·누락·타입 다름, 설명문·이미지·현지화 계열 컬럼, 정해 두지 않은 타입) 어떤 컬럼인지 알리고 아무것도 넣지 않는다. 타입은 `int64→BIGINT`, `string→TEXT`만 정해 두었다 (`double`, `bool`, 시간대 있는 `timestamp`는 코드에 매핑이 있고, 시간대 없는 `timestamp`와 그 밖의 타입은 오류다).
- **빈 테이블 규칙:** 두 테이블 중 하나라도 행이 있으면 아무것도 넣지 않고 멈춘다. 삭제·`TRUNCATE` 옵션은 없다. 로컬을 처음부터 다시 하려면 `docker compose down -v`인데, **회원 데이터도 함께 지워지니 주의한다.**
- **롤백:** 두 테이블은 한 트랜잭션이다. 중간에 실패하면 둘 다 비어 있다.
- **`verify` 항목:** ① 행 수 ② 키 중복·NULL ③ 참조 무결성(variant 없는 design 수는 보고만) ④ `article_id` 형식(숫자, 같은 길이, 앞자리 0 보존) ⑤ `*_name`에 `Unknown` 없음 ⑥ 가격 규칙(`design_price`는 5,900 이상, **500원 단위** → 끝자리 900 또는 400) ⑦ 컬럼별 집계가 원본과 같음 ⑧ 무작위(시드 고정) 1,000행씩 전 컬럼 대조.
- **출력:** 상품 값은 출력하지 않는다. 컬럼 이름, 건수, 최대 5개의 키(`product_code`/`article_id`)만 보여 준다.
- **S3에서 읽기:** `--source s3://hm-ecommerce-data/seed_v2`는 읽기 전용이다 (쓰기·삭제 코드 없음). 자격 증명은 `.env`나 환경 변수의 기존 AWS 설정을 쓰고, 그 계정에 읽기 권한이 있어야 한다.
- **이번 범위 밖:** 상품 데이터 생성·가공, 가격 변동·재고, 주문·결제, CDC 대상에 상품 테이블 추가, RDS 접속.
