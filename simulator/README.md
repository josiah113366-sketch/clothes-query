# simulator/

가상 쇼핑몰의 회원 데이터를 만들어 RDS(PostgreSQL)에 쓰는 시뮬레이터이다. Kafka에는 직접 쓰지 않고, Debezium이 변경 로그를 읽어 보낸다. 설계는 `docs/design/`에 있다. 작업 규칙은 `CLAUDE.md`를 따른다.

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
│   ├── product/           # 상품 시드(Parquet)를 DB에 옮기고 확인 (sim product)
│   ├── common/            # 설정, 시드·난수, DB 연결, 시계, 제어 신호, 로깅, 지역 로더
│   ├── controller/        # 모드 전환, 장애 주입, 주입 기록
│   ├── member/            # 회원 생성 함수, 베이스라인 적재, 신규 가입 실행기
│   └── behavior/          # 쇼핑 행동 (나중에)
└── tests/
```

`member`, `behavior`, `controller`는 서로 import하지 않고 `common`만 공유한다. 데이터는 DB로, 제어는 컨트롤러 신호로만 주고받는다. DDL은 `db/schema/`에 있다.

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
sim member live                                   # 평상시, 실시간, 하루 평균 5,000명
sim member live --speed 1440 --duration 30        # 시뮬레이터 하루 = 실제 1분으로 30초 실행
sim member live --daily 86400 --max-signups 20    # 초당 약 1건, 20건 만들고 종료
```

| 옵션 | 환경 변수 | 기본값 | 설명 |
|---|---|---|---|
| `--mode` | `SIM_LIVE_MODE` | `normal` | 시작 모드 (`normal` \| `surge`) |
| `--daily` | `SIM_LIVE_DAILY` | 5000 | 평상시 하루 평균 가입 수 |
| `--surge-multiplier` | `SIM_LIVE_SURGE_MULTIPLIER` | 4.6 | 폭주 모드의 배율 |
| `--speed` | `SIM_LIVE_SPEED` | 1 | 시간 배속 (1 = 실시간) |
| `--duration` | | 계속 | **실제 시간** 기준 실행 초. 지나면 정상 종료 |
| `--max-signups` | | 없음 | 이 건수만큼 만들면 정상 종료 |
| `--control-file` | `SIM_CONTROL_FILE` | `.local/control.json` | 제어 신호 파일 |
| `--seed` | `SIM_SEED` | 42 | 기본 시드. 신규 회원은 여기서 **다른 줄기**로 파생한다 |

환경 변수 중 `DATABASE_URL`, `SIM_SEED`는 `.env`에서도 읽고, 나머지 `SIM_LIVE_*`, `SIM_CONTROL_FILE`은 실제 환경 변수로만 읽는다.

- **가입 간격**은 푸아송 과정(지수분포)이다. 속도는 `하루 가입 수 × 모드 배율 ÷ 86,400`건/초이고, 하루 안의 시간대·날짜별 차이는 아직 없다(균등). 그 자리는 `member/schedule.py`의 `rate_multiplier`다.
- **제어 파일**을 약 1초마다 읽는다. 로컬에서는 이렇게 바꾼다.

  ```bash
  echo '{"running": true,  "mode": "surge"}'  > .local/control.json   # 폭주 (평상시의 4.6배)
  echo '{"running": true,  "mode": "normal"}' > .local/control.json   # 평상시로 복귀
  echo '{"running": false, "mode": "normal"}' > .local/control.json   # 멈춤 (프로세스는 살아 있음)
  ```

  모드가 바뀌면 `mode: normal → surge` 한 줄이 출력되고 새 속도로 간격을 다시 뽑는다. 파일이 없거나 깨졌거나 값이 잘못되면 마지막 상태를 유지하고 경고를 한 번만 낸다. 제어 파일은 시작 상태(`--mode`)를 이후에 덮어쓴다.
- **제어 신호 전달 수단은 아직 정해지지 않았다.** 파일 방식은 로컬 개발용이고, 실제 수단은 컨트롤러 작업에서 `ControlSource`를 새로 구현해 붙인다.
- **배속과 시각:** `signup_at`은 시뮬레이터 시각(KST)이고 `created_at`은 DB가 기록한 실제 시각이다. 배속 1이면 거의 같고, 배속이 크면 어긋난다. 정상이다.
- **껐다 켜도 이어진다:** k번째 신규 회원은 `derive_seed(시드, "live", k)`로 난수를 다시 심어 만들어 값이 시드와 k만으로 정해진다. 시작할 때 k는 `members`에서 `signup_at >= 2026-10-01 00:00 KST`인 행 수로 센다(탈퇴는 행을 지우지 않으므로 줄지 않는다). 그래서 껐다 켜도 같은 순서로 이어지고 `member_id`가 겹치지 않는다. 시뮬레이터 시각이 10/1 KST보다 이르면 이 기준이 깨지므로 오류로 멈춘다.
- **전화번호:** 무작위로 뽑아 넣고, `member_phone_key` 위반이면 같은 난수 줄기에서 새 번호로 최대 10번 다시 시도한다(전화번호만 바뀐다). 다른 제약 위반은 재시도하지 않고 오류로 처리한다. 번호를 확인하려고 DB에서 읽어 오지 않는다.
- **종료:** `Ctrl+C`(SIGINT)나 SIGTERM이면 하던 INSERT를 끝내고 요약을 출력한 뒤 종료 코드 0으로 끝난다. DB 연결이 끊기면 1, 2, 4, … 최대 30초 간격으로 다시 연결한다.
- 실제 시간 10초마다 진행 한 줄(모드, 구간 건수와 초당 건수, 누적, 시뮬레이터 시각)을 출력한다. 회원 값(PII)은 출력하지 않는다.
- 이 명령으로 `member`에 신규 가입이 섞이면 `sim member verify`의 가입 기간·일별·시간대별 항목은 베이스라인 기준이라 실패할 수 있다.
- 확인 후 로컬에서 신규 가입만 지우려면: `DELETE FROM members WHERE signup_at >= '2026-10-01 00:00:00+09';`

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
