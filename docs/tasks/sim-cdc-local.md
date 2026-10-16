# 작업 지시서: sim/cdc-local

> 상태: 진행 전 · 브랜치: `sim/cdc-local` · 이전 작업: `sim/skeleton`, `sim/member-baseline`, `sim/member-live` · 다음 작업: 탈퇴(`u`)·장애 주입·클라우드 이전

## 목표

로컬 PostgreSQL의 `members` 테이블을 **Debezium이 읽어 Kafka 토픽 `members-events`로 흘리는 구성**을 로컬에 만들고, **그 결과가 설계대로인지(특히 PII가 한 글자도 안 나가는지) 확인하는 `sim cdc verify` 명령**을 만든다.

이 브랜치가 끝나면 이런 흐름이 로컬에서 돈다.

```
docker compose --profile cdc up -d      ← Kafka + Kafka Connect(Debezium) 추가로 켬
sim cdc setup                           ← 커넥터 등록 → 10만 명이 스냅샷(op=r)으로 흘러감
sim member live ...                     ← 신규 가입 → op=c 이벤트
sim cdc verify                          ← 토픽 내용이 Bronze 모양인지, PII가 없는지 확인
```

**S3 Sink(Bronze 파일 쓰기)는 이번에 만들지 않는다.** 대신 `verify`가 토픽을 직접 읽어서 "Bronze에 들어갈 모양"을 검증한다. 이 모양이 맞으면 S3 Sink는 이 토픽을 파일로 옮기기만 하면 된다.

이 지시서는 **자기 완결형**이다. 필요한 설계 수치와 기본값이 본문에 있다. `docs/design/member.md`(특히 4-3, 4-5절), `docs/design/simulator-member.md`가 레포에 있으면 함께 읽되, **이 지시서와 어긋나면 추측하지 말고 묻는다.**

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- **커밋하지 않는다.** 파일만 만들고 테스트까지 진행한다. 커밋, push, PR은 사용자가 확인한 뒤 직접 한다. (`sim/member-live`와 같은 방식)
- 이번에는 **로컬에서만** 한다. RDS, MSK, EKS, Terraform은 건드리지 않는다. AWS 자격 증명도 쓰지 않는다.
- Python 3.12 가상환경(`simulator/.venv`, WSL)과 사용자 컴퓨터의 WSL Docker를 쓴다. `psql`이 없으므로 DB 확인은 `docker compose exec postgres psql -U sim -d clothes`로 한다.
- 기존 파일을 고칠 때 줄바꿈(CRLF/LF)만 바꾸지 않는다. 필요한 파일만 git 기준(LF)으로 편집한다.
- 로컬 DB에 이미 있는 10만 명(`members` 테이블)을 **그대로 쓴다.** 지우거나 다시 만들지 않는다.
- 완료 확인이 끝난 뒤 **Kafka·Connect·DB 상태(커넥터, 슬롯, 토픽, 가입 테스트로 늘어난 행)를 남길지 지울지 사용자에게 묻는다.** 임의로 `down -v`, `DELETE` 하지 않는다.

## 시작 전 확인 (Claude가 한다)

- 현재 브랜치가 `sim/cdc-local`이고, 최신 `main`에서 만들어졌는지 확인한다.
- `git log --oneline`에 `sim/member-baseline`, **`sim/member-live` 머지가 보이는지** 확인한다.
  - `sim member live` 명령이 없으면: **스냅샷(`r`) 구간까지만** 진행하고, 신규 가입(`c`) 확인은 "보류"로 보고한다. 임의로 가입 코드를 새로 만들지 않는다.
- `db/schema/001_member.sql`, `simulator/docker-compose.yml`, `simulator/CLAUDE.md`를 읽는다. `connectors/` 폴더가 있는지 본다 (없으면 이번에 만든다).
- 로컬 DB 상태를 확인한다: `docker compose up -d` 후 `SELECT count(*) FROM members;`. **100,000이 아니면 알리고 멈춘다** (신규 가입 테스트 잔여 행이 있을 수 있다. 어떻게 할지는 사용자가 정한다).
- 이 지시서가 저장소 루트에 있으면 `docs/tasks/sim-cdc-local.md`로 옮긴다.
- 사용할 이미지의 **태그가 실제로 존재하는지** 확인한다 (아래 표). `latest` 태그는 쓰지 않는다. 고른 태그는 사용자에게 알린다.

## 이번 작업에서 확정된 값

값은 코드 곳곳에 흩뿌리지 않는다. 파이썬 쪽은 `src/sim/cdc/params.py` **한 곳**, 커넥터 쪽은 `connectors/member-source.json` **한 곳**에 둔다.

| 항목 | 값 | 출처 |
|---|---|---|
| 대상 테이블 | `public.members` **하나만**. `members_archive`는 대상이 아니다 | 설계 결정 (4-5절) |
| 내보내는 컬럼 | **`column.include.list`** 로 10개만: `member_id, signup_at, signup_channel, gender, age_band, region_sigungu, marketing_consent, status, withdrawn_at, created_at`. **`column.exclude.list`는 쓰지 않는다** | 설계 결정 (4-3, 4-5절) |
| 내보내지 않는 컬럼 | `name, email, phone, birth_date, password_hash` | 설계 결정 |
| 관리 컬럼 | `__op`(r/c/u), `__source_ts_ms`(epoch 밀리초), 스냅샷 여부. 이름은 Debezium이 만드는 대로 둔다 (아래 "관리 컬럼 이름" 참고) | 설계 결정 (이름은 설명용) |
| 메시지 모양 | Debezium 봉투를 벗기고 `after`의 값을 **펼친 한 행** + 관리 컬럼. `before`는 없다. 삭제(`d`) 이벤트는 없어야 한다 | 설계 결정 (4-3절) |
| 토픽 | `members-events` | 설계 결정 |
| 메시지 키 | `member_id` | 설계 결정 |
| 시각 | `timestamptz` 컬럼 → **UTC** ISO 문자열(`...Z`로 끝남). `dt=` 파티션은 S3 Sink 몫이라 이번에 없음 | 설계 결정 (4-3절) |
| 스냅샷 | 저장된 offset이 없을 때만 한다. 스냅샷 행은 `op=r` | 설계 결정 |
| 베이스라인 | 100,000행 → `r` 100,000건 | 설계 결정 |
| 하트비트 | 켠다 (`heartbeat.interval.ms=10000`). 하트비트 토픽은 `members-events`가 아니다 | 설계 결정 (4-5절) |
| WAL 보관 한도 | 로컬 Postgres에 `max_slot_wal_keep_size=1GB` | 설계 결정 (4-5절, 로컬 값은 지시서 기본값) |
| 복제 슬롯 / publication | 슬롯 `member_slot`, publication `member_pub` (Debezium이 `filtered` 모드로 만든다) | 지시서 기본값 |
| 토픽 접두사 | `cdc` (Debezium 기본 토픽은 `cdc.public.members`, 이름을 `members-events`로 바꿔 보낸다) | 지시서 기본값 |
| 파티션 / 복제 | 3 / 1 (키 분산을 눈으로 확인하려는 값. 파티션 수는 설계에서 정해진 적 없음) | 지시서 기본값 |
| 값 형식 | JSON (스키마 정보 없이 값만). 사람이 읽고 검증하기 쉬우려는 선택 | 지시서 기본값 |

### 구성 요소 (docker compose)

기존 `simulator/docker-compose.yml`에 서비스를 추가한다. **프로필 `cdc`** 로 묶어서, 기존처럼 `docker compose up -d`만 하면 Postgres만 뜬다.

| 서비스 | 이미지 (예시, 태그는 실제 존재 확인) | 역할 |
|---|---|---|
| `kafka` | `apache/kafka:3.9.x` (KRaft, 단일 노드) | 토픽 저장 |
| `connect` | `quay.io/debezium/connect:3.x` (Kafka Connect + Debezium Postgres 커넥터 포함) | Postgres WAL을 읽어 Kafka로 |

필수 설정 (세부 환경 변수 이름은 사용하는 이미지의 문서로 확인한다):

- **리스너를 둘로 나눈다.** 컨테이너끼리는 `kafka:9092`, WSL(파이썬 CLI)에서는 `localhost:29092`. 이걸 안 나누면 컨테이너 안에서는 되는데 밖에서 접속이 안 되거나 그 반대가 된다.
- 복제 계수를 쓰는 모든 설정을 **1**로 (Kafka 내부 토픽, Connect의 `config/offset/status` 저장 토픽 포함). 노드가 하나라서 기본값(3)이면 시작하지 못한다.
- 메모리를 제한한다 (Kafka·Connect 각각 힙 최대 512MB 안팎). WSL Docker 메모리를 많이 먹지 않게.
- 포트는 `127.0.0.1`에만 연다: Kafka `29092`, Connect REST `8083`. (Connect REST는 인증이 없다.)
- `kafka` 데이터는 **이름 있는 볼륨** `simulator_kafkadata`. 
- Connect의 DB 비밀번호는 **커넥터 JSON에 쓰지 않는다.** Connect 컨테이너 환경 변수 `CDC_DB_PASSWORD`로 주고, 커넥터 JSON에는 `${env:CDC_DB_PASSWORD}`로 적는다 (Kafka의 환경 변수 설정 제공자 `EnvVarConfigProvider`를 Connect에 켠다). 이 방식이 이 이미지에서 안 되면 대안을 정하지 말고 알린다. (나중에 RDS용 비밀번호도 파일에 안 적는 방식으로 가기 위한 연습이다.)
- `connect`는 `kafka`와 `postgres`가 준비된 뒤에 뜬다 (`depends_on` + 상태 확인).
- Postgres 서비스의 `command`에 `-c max_slot_wal_keep_size=1GB`를 **추가**한다. 기존 `-c wal_level=logical`은 그대로. 변경 후 Postgres 컨테이너가 다시 뜨는데 **데이터 볼륨은 그대로다** (10만 명은 남는다. 다시 뜬 뒤 행 수로 확인한다).

> 로컬 Postgres의 `sim` 사용자는 기본 슈퍼유저라 복제 권한이 이미 있다. 그래서 로컬에서는 Debezium 전용 계정을 따로 만들지 않는다. RDS에서는 `rds_replication` 권한을 가진 전용 계정을 쓰게 된다 (인프라 작업, 이번 범위 밖).

## 만드는 것

### 1. 커넥터 설정 (`connectors/member-source.json`)

Kafka Connect REST에 그대로 보낼 **설정 값 묶음**이다 (`name` 키 포함, 평평한 JSON). 아래 값이 **결정사항**이다. 프로퍼티 이름이 사용하는 Debezium 버전과 다르면(예: 삭제 처리 옵션 이름) 버전 문서에 맞게 고치고 **무엇을 어떻게 바꿨는지 알린다.**

| 키 | 값 | 이유 |
|---|---|---|
| `name` | `member-source` | |
| `connector.class` | `io.debezium.connector.postgresql.PostgresConnector` | |
| `plugin.name` | `pgoutput` | Postgres 기본 논리 복제 방식 |
| `database.hostname` / `port` / `dbname` / `user` | `postgres` / `5432` / `clothes` / `sim` | 컨테이너 네트워크 안의 서비스 이름 |
| `database.password` | `${env:CDC_DB_PASSWORD}` | 파일에 비밀번호를 적지 않는다 |
| `topic.prefix` | `cdc` | |
| `schema.include.list` / `table.include.list` | `public` / `public.members` | `members_archive` 제외 |
| `column.include.list` | 위 10개 컬럼을 `public.members.<컬럼>` 형태로 쉼표로 나열 | **PII를 처음부터 내보내지 않는다.** 스냅샷 전에 반드시 있어야 한다 |
| `slot.name` / `publication.name` | `member_slot` / `member_pub` | |
| `publication.autocreate.mode` | `filtered` | publication에 `members`만 들어간다 |
| `snapshot.mode` | `initial` | |
| `tombstones.on.delete` | `false` | 삭제는 없다 |
| `heartbeat.interval.ms` | `10000` | 트래픽이 적을 때 슬롯이 밀리지 않게 |
| `key.converter` / `value.converter` | `JsonConverter`, 둘 다 `schemas.enable=false` | 값만 있는 JSON |
| `transforms` | `unwrap,route` | |
| `transforms.unwrap.type` | `io.debezium.transforms.ExtractNewRecordState` | 봉투를 벗겨 `after`를 펼침 |
| `transforms.unwrap.add.fields` | `op,source.ts_ms,source.snapshot` | 관리 컬럼 3개 |
| `transforms.unwrap.add.fields.prefix` | `__` | |
| `transforms.unwrap.predicate` | 데이터 토픽(`cdc.public.members`)에만 적용 | 하트비트 메시지는 건드리지 않는다 |
| `transforms.route.type` | `org.apache.kafka.connect.transforms.RegexRouter` | |
| `transforms.route.regex` / `replacement` | `cdc\.public\.members` / `members-events` | 토픽 이름 |
| `topic.creation.default.partitions` / `replication.factor` | `3` / `1` | 토픽 자동 생성. 이 설정이 동작하지 않아 브로커 기본값(1 파티션)으로 만들어지면 그대로 두고 알린다 |

**관리 컬럼 이름:** 설계 문서의 `__op`, `__source_ts_ms`, `__snapshot`은 "설명용 이름"이다. 위 설정이면 Debezium은 `__op`, `__source_ts_ms`, **`__source_snapshot`** 처럼 만들 가능성이 높다. **실제로 나온 이름을 확인해서 `params.py`에 그 이름으로 두고 보고한다.** SMT로 이름을 억지로 바꾸지 않는다. (S3 Sink·Silver 쪽과 이름을 맞춰야 하므로 팀에 알릴 사항이다.) 스냅샷 값은 문자열 `true` / `last` / `false`로 나온다 (`last`는 스냅샷의 마지막 행).

`connectors/README.md`도 만든다: 파일 설명, 값 하나하나의 이유(위 표), "컬럼을 바꾸려면 스냅샷 전에, 이미 스냅샷 했다면 `sim cdc reset` 후", RDS로 옮길 때 바뀌는 값(호스트, 계정, 비밀번호 제공 방식, 슬롯·publication은 인프라가 만들 수 있음).

### 2. 파이썬 (`src/sim/cdc/`)

| 파일 | 내용 |
|---|---|
| `params.py` | 커넥터 이름, 토픽, 슬롯, publication, **Bronze 컬럼 10개**, 관리 컬럼 이름, **금지 필드 이름**(`name, email, phone, birth_date, password_hash`), 허용 값 집합(성별·채널·상태·나이대), 기본 주소 |
| `connect.py` | Kafka Connect REST 호출 (표준 라이브러리 `urllib`만 쓴다. 새 의존성 없음): 설정 등록, 상태 조회, 정지, offset 삭제, 삭제. **설정 파일 검사 함수** (아래 "안전장치") |
| `checks.py` | **검증 로직 순수 함수**: 이벤트를 하나씩 받아 집계하고 항목별 통과/실패를 돌려준다. Kafka·DB를 부르지 않는다 (그래서 단위 테스트가 가능) |
| `consume.py` | Kafka에서 읽기 (`confluent-kafka`). 아래 "읽는 방식" |
| `dbcheck.py` | DB 쪽 확인: 슬롯, publication, `member_id` 집합, 샘플 대조 |
| `cli.py` | `typer` 하위 앱 `cdc` (`setup`, `status`, `verify`, `reset`). `sim/cli.py`에서 `app.add_typer(cdc_app, name="cdc")`로 연결 |

**의존성 추가:** `confluent-kafka`를 실행용 의존성에 추가한다. 이 지시서가 허용한 **유일한** 추가다. `pyproject.toml`과 `simulator/CLAUDE.md`의 의존성 줄을 함께 고친다.

**설정 추가** (`common/config.py`, `.env.example`에는 더미 값):

```
CONNECT_URL=http://localhost:8083
KAFKA_BOOTSTRAP=localhost:29092
```

**안전장치 (`connect.py`의 설정 파일 검사)** — `setup`이 등록 **전에** 반드시 통과시킨다. 어긋나면 등록하지 않고 이유를 알린다.

- `column.include.list`가 있고, 정확히 `params.py`의 10개 컬럼과 같다 (순서 무관, 하나라도 더 있거나 모자라면 실패)
- `column.exclude.list`가 **없다**
- `table.include.list`가 `public.members` 하나다
- 비밀번호 값이 `${env:...}` 형태다 (평문이면 실패)

이 검사는 DB·Connect 없이 도는 단위 테스트로도 돌린다 (레포의 실제 `connectors/member-source.json`을 읽어서).

### 3. CLI

```
sim cdc setup   [--config ../connectors/member-source.json]
sim cdc status
sim cdc verify  [--snapshot-expected 100000] [--live-expected N]
sim cdc reset   [--yes]
```

**`setup`**

1. 설정 파일을 읽고 위 "안전장치" 검사를 한다.
2. 대상 DB를 `호스트:포트/DB이름`으로만 출력한다. Connect에 닿는지 확인한다.
3. `members` 행이 **0이면 멈춘다** ("베이스라인을 먼저 적재"). 설계 순서는 베이스라인 → 커넥터다.
4. 같은 이름의 커넥터가 **이미 있으면 아무것도 바꾸지 않고** 현재 상태만 보여 준다. (설정을 덮어쓰면 이미 스냅샷한 뒤 컬럼 목록만 바뀌는 사고가 생길 수 있다. 바꾸려면 `reset` 후 다시 `setup`.)
5. 없으면 등록하고, 커넥터와 task가 `RUNNING`이 될 때까지 최대 60초 기다린다. 스냅샷은 그 뒤 백그라운드로 진행되므로 "`sim cdc status`로 진행을 보세요"라고 안내한다.

**`status`** (읽기 전용): 커넥터·task 상태, 슬롯(있는지, 활성인지, **밀린 WAL 크기**: `pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn)`), publication에 들어 있는 테이블, `members-events` 파티션별 끝 offset과 합계.

**`verify`** — 아래 "verify" 절.

**`reset`** (**로컬 전용**, `DATABASE_URL` 호스트가 `localhost`/`127.0.0.1`이 아니면 거부, `--yes`가 없으면 `[y/N]`): 스냅샷을 다시 하고 싶거나 설정을 잘못 넣었을 때 쓴다. 순서는 아래와 같다.

1. 커넥터 정지 → **커넥터 offset 삭제** → 커넥터 삭제 (Kafka Connect의 offsets API, Kafka 3.6 이상)
2. 복제 슬롯 삭제 (커넥터가 풀려날 때까지 몇 초 걸리면 재시도), publication 삭제
3. 토픽 `members-events`와 하트비트 토픽 삭제

> offset을 지우지 않으면 같은 이름으로 다시 만들어도 "이미 스냅샷함"으로 보고 **스냅샷을 건너뛴다.** (설계 4-5절 "스냅샷 반복") 이 명령이 있는 이유다.
> `reset`은 `members` 테이블의 행을 건드리지 않는다.

### 읽는 방식 (`consume.py`)

- 토픽을 **처음부터** 읽는다. 매번 새 소비자 그룹 이름(임시)을 쓰고 offset은 커밋하지 않는다 (읽어도 아무 흔적이 남지 않는다).
- 시작할 때 파티션별 **끝 offset을 한 번 기록**하고, 거기까지 읽으면 멈춘다 (흐르는 중인 새 메시지를 기다리지 않는다).
- 메시지를 **하나씩 집계**하고 원문을 쌓아 두지 않는다 (10만 건 이상으로 커져도 메모리가 늘지 않게). 남기는 것은 집계값과 `member_id` 집합뿐이다.
- 60초 동안 새 메시지가 하나도 없고 끝 offset에 못 닿으면 실패로 보고한다.

### verify

토픽과 DB를 읽어 항목별 **통과/실패** 표를 보여 주고, 하나라도 실패하면 종료 코드 1이다. `--snapshot-expected`(기본 100,000)은 `r` 이벤트의 기대 건수, `--live-expected`는 `c` 이벤트의 기대 건수(주어졌을 때만 확인).

| # | 확인 | 기준 |
|---|---|---|
| 1 | 커넥터 | 커넥터·task `RUNNING`. 실제 등록된 설정의 `column.include.list`가 정확히 10개, `exclude.list` 없음, 테이블은 `public.members` 하나 |
| 2 | DB 쪽 | 슬롯 `member_slot`(pgoutput)이 있고 활성. publication의 테이블이 `public.members` 하나뿐 (`members_archive` 없음) |
| 3 | 이벤트 종류 | `__op`가 `r`/`c`/`u`만. `d` 0건. `r` 건수 = `--snapshot-expected` |
| 4 | 필드 | **모든 메시지의 키 집합이 정확히** 10개 + 관리 컬럼 3개. 하나라도 더 있거나 모자라면 실패 |
| 5 | **PII 없음** | 메시지 **원문**에서 금지 필드 이름(`"name"`, `"email"`, `"phone"`, `"birth_date"`, `"password_hash"`), `@example\.com`, `010-\d{4}-\d{4}`, `\$2b\$12\$` 모두 0건 |
| 6 | 시각 | `signup_at`/`created_at`/`withdrawn_at`(값이 있을 때)이 모두 `Z`로 끝나는 UTC 문자열. `r` 이벤트의 `signup_at`은 [UTC 2026-07-31 15:00, 2026-09-30 15:00) 안 |
| 7 | 값 모양 | `member_id`는 uuid, 성별 F/M, 채널 web/app, 나이대 7개 중 하나, 상태 ACTIVE/WITHDRAWN, `marketing_consent`는 참/거짓, 지역은 지역 파일 256개 안, `__source_ts_ms`는 정수 |
| 8 | 키 | 메시지 키의 `member_id` = 값의 `member_id` (전부) |
| 9 | 관리 컬럼 | `r`은 스냅샷 값 `true`/`last`, `c`는 `false` |
| 10 | 중복 | `r` 이벤트의 `member_id` 중복 0, `c` 이벤트의 `member_id` 중복 0 |
| 11 | DB와 일치 (전체) | 이벤트에 나온 `member_id` 집합 = DB `members`의 `member_id` 집합 |
| 12 | DB와 일치 (샘플) | DB에서 무작위 1,000명을 골라 `signup_at`, `created_at`, `region_sigungu`, `age_band`, `status`가 이벤트 값과 **같다** (시각은 같은 순간인지 비교. UTC 변환이 맞는지 확인하는 항목) |
| 13 | 신규 가입 | `--live-expected`가 있으면 `c` 건수 = 그 값 |

**출력 규칙 (PII 안전):** 실패했을 때도 **값을 출력하지 않는다.** 필드 *이름*, 건수, 최대 5개의 `member_id`(가명 ID)만 보여 준다. 이메일처럼 보이는 문자열이 걸렸다면 "원문에서 N건 발견"까지만 말한다. 메시지 원문을 파일로 저장하지 않는다.

## PII 안전 (중요)

| 규칙 | 구현 |
|---|---|
| PII가 Kafka에 **한 번도** 들어가지 않는다 | `column.include.list`를 스냅샷 **전에** 둔다. `setup`의 안전장치와 `verify` 1번이 이를 지킨다 |
| `include.list`를 잘못 넣고 스냅샷했다면 | 토픽에 PII가 이미 들어갔다. 고치는 방법은 `reset`(토픽 삭제)뿐이다. 이런 일이 생기면 사용자에게 바로 알린다 |
| 출력에 회원 값이 없다 | `verify`/`status`/`setup`의 출력 모두 (위 출력 규칙). Postgres 오류는 `common/db.py`의 오류 가리기를 그대로 쓴다 |
| 커넥터 설정에 비밀이 없다 | 비밀번호는 `${env:...}`. 레포에 평문 비밀번호가 들어간 파일이 없다 |
| Connect REST가 밖에 열리지 않는다 | `127.0.0.1`에만 바인딩 |

## 테스트

**단위 테스트 (Kafka·DB 없이 돈다, 기본 `pytest`에 포함):**

- **커넥터 설정 파일**(레포의 실제 `connectors/member-source.json`): `column.include.list`가 정확히 10컬럼, `exclude.list` 없음, 테이블이 `public.members` 하나, 비밀번호가 `${env:...}`, 토픽 변환 결과가 `members-events`
- 설정 검사 함수: 컬럼이 하나 더 있음(예: `email`) / 하나 모자람 / `exclude.list` 사용 / 평문 비밀번호 / 테이블 2개 → 각각 실패
- `checks.py`에 **가짜 이벤트**를 넣어 항목별로 확인:
  - 정상 이벤트 모음은 전부 통과
  - 값에 `email` 필드가 하나 섞이면 4번·5번 실패
  - `010-1234-5678` 모양 문자열이 값 안에 있으면 5번 실패
  - `Z`가 없는 시각(`+09:00` 형식이나 시간대 없음)이 있으면 6번 실패
  - `__op=d`가 있으면 3번 실패
  - 같은 `member_id`의 `r`이 두 번이면 10번 실패
  - 키와 값의 `member_id`가 다르면 8번 실패
  - `r`인데 스냅샷 값이 `false`면 9번 실패
- **출력 안전:** 실패한 검증의 출력 문자열에 가짜 이벤트에 넣은 PII 문자열이 없다
- `reset`/`setup`의 로컬 전용 거부: `DATABASE_URL` 호스트가 `localhost`가 아니면 `reset`은 아무것도 부르지 않고 거부한다 (Connect 호출을 가짜로 바꿔 확인)

**통합 테스트는 만들지 않는다.** 슬롯과 커넥터는 실제 `members` 테이블에 붙는 것이라 임시 스키마로 대체할 수 없다. 대신 아래 "완료 확인"의 실제 실행이 통합 검증이다.

## 만들지 않는 것

- S3 Sink, Bronze 파일 쓰기, `dt=` 파티션, Silver 이후 (→ 이후)
- 탈퇴(`u` 이벤트) 생성, `members_archive` 이동, 커넥터 대상에 `members_archive` 넣기 (→ 탈퇴 작업)
- 장애 주입 자동화 (이번에는 사람이 컨테이너를 멈췄다 켜는 **한 번의 확인**만 한다, 아래 완료 확인)
- Coupon Worker, Metrics Consumer 같은 다른 소비자 (설계의 fan-out 예시일 뿐)
- RDS, MSK, EKS, Terraform, Secrets Manager, ECR
- `db/schema/` 변경, `REPLICA IDENTITY FULL` 설정 (Bronze에 `before`를 저장하지 않으므로 필요 없다)
- Kafka UI, 스키마 레지스트리, Avro
- 설계 문서(`docs/design/*`) 수정

## 작업 순서

**커밋하지 않는다.** 각 단계가 끝나면 그 단계의 테스트를 돌려 확인하고 다음 단계로 간다.

1. 시작 전 확인을 하고, **계획을 먼저 제시해 사용자 확인을 받는다.** 계획에 고른 이미지 태그와 위 표에서 바꾼 값이 있으면 함께 적는다
2. compose 서비스 추가 + Postgres `max_slot_wal_keep_size` + `connectors/member-source.json` + `connectors/README.md` + 설정 파일 단위 테스트 → `docker compose --profile cdc up -d`로 Kafka·Connect가 **정상 기동**하는지까지 확인 (아직 커넥터 등록 전)
3. `cdc/params.py`, `connect.py`, 설정 추가, `cli.py`의 `setup`·`status`·`reset` + 단위 테스트
4. `cdc/checks.py` + 가짜 이벤트 단위 테스트
5. `cdc/consume.py`, `dbcheck.py`, `verify` 명령
6. `simulator/README.md`에 `## 로컬 CDC` 절 추가, `simulator/CLAUDE.md` 의존성 줄에 `confluent-kafka` 추가
7. "완료 확인"을 **실제로 실행**해서 결과 보고

## 완료 확인

아래를 **실제로 실행**해서 결과를 보고한다.

- [ ] `pip install -e ".[dev]"` 성공, `ruff check .`, `ruff format --check .`, `pytest`(단위) 통과
- [ ] Postgres 재기동 후에도 `SELECT count(*) FROM members;` → **100000**. `SHOW max_slot_wal_keep_size;` → `1GB`, `SHOW wal_level;` → `logical`
- [ ] `docker compose up -d`만 하면 **Postgres만** 뜬다 (프로필 확인). `docker compose --profile cdc up -d`로 `kafka`, `connect`가 뜨고 `curl localhost:8083/connectors`가 응답한다
- [ ] `sim cdc setup` 성공 → `sim cdc status`로 스냅샷이 진행되고 끝나는 것을 확인. 걸린 시간 보고
- [ ] `sim cdc verify` (live 전) → **`r` 100,000건, `c` 0건, 13개 항목 중 해당되는 것 전부 통과**
- [ ] 실제 Debezium이 만든 **관리 컬럼 이름**을 보고 (`__op`, `__source_ts_ms`, 스냅샷 컬럼 이름)
- [ ] 실제 토픽의 **파티션 수**를 보고 (`status`)
- [ ] **Kafka 데이터 파일을 직접 grep:** `docker compose exec kafka`로 Kafka 데이터 디렉터리 안에서 `grep -rlE "example\.com|010-[0-9]{4}-[0-9]{4}"` → **결과 없음.** 같은 곳에서 `member_id`로 grep하면 파일이 **나온다** (grep이 제대로 동작한다는 확인)
- [ ] `sim member live --mode steady --max-signups 200 ...` (속도 옵션을 크게 해서 몇 분 안에 끝나게 한다. 옵션 의미는 live 문서/README 참고) → `sim cdc verify --live-expected 200` → **`c` 정확히 200건, 중복 0, 전부 통과** (live가 없으면 "보류"로 보고)
- [ ] **커넥터 중단 확인:** `docker compose stop connect` → `sim member live --max-signups 10 ...` → `sim cdc status`에서 슬롯이 **밀린 WAL이 늘어난 것**을 보고 → `docker compose start connect` → 잠시 뒤 `sim cdc verify --live-expected 210` → **`c` 정확히 210건, `r`은 그대로 100,000건** (재시작해도 스냅샷을 다시 하지 않고, 빠뜨리지도 중복하지도 않는다)
- [ ] 위 모든 실행 출력을 파일로 저장해 `grep -E "example\.com|010-"` → **결과 없음**
- [ ] 단위 테스트에서 일부러 PII가 섞인 가짜 이벤트가 `verify` 5번에서 **실패로 잡히는 것**을 확인 (테스트 통과로 갈음)
- [ ] `git status`에 `.env`, 평문 비밀번호가 든 파일이 없다. 줄바꿈만 바뀐 기존 파일을 건드리지 않았다. **커밋하지 않았다**
- [ ] 끝나면 **사용자에게 묻는다:** 커넥터·슬롯·토픽을 남길지(`sim cdc reset`으로 지울지), 가입 테스트로 늘어난 `members` 행(210건 등)을 어떻게 할지. 행을 지울 때는 **커넥터를 먼저 `reset`** 한다 (켜 둔 채 지우면 `d` 이벤트가 토픽에 생긴다). 임의로 지우지 않는다

## README 갱신

- `simulator/README.md`: `## 로컬 CDC` 절 (한 줄 요약, 켜는 순서 `baseline → up --profile cdc → setup → live → verify`, 각 명령 설명, `reset`이 필요한 경우와 이유, 메모리 사용량 주의, 자주 막히는 곳: 리스너 주소 `kafka:9092` vs `localhost:29092`, offset을 안 지우면 스냅샷이 건너뛰어진다)
- `connectors/README.md`: 위 "커넥터 설정" 절 참고
- `simulator/CLAUDE.md`: 의존성 줄에 `confluent-kafka` 추가 (이 한 줄만)

## 참고: 사용자가 나중에 커밋할 때의 제안 메시지

(Claude는 커밋하지 않는다. 사용자가 나눠서 커밋할 때 쓰는 제안이다.)

1. `sim(cdc-local): Kafka와 Connect 로컬 구성, 커넥터 설정 추가`
2. `sim(cdc-local): 커넥터 등록·상태·초기화 명령 추가`
3. `sim(cdc-local): 이벤트 검증 로직 추가`
4. `sim(cdc-local): 토픽 읽기와 DB 대조, verify 명령 추가`
5. `sim(cdc-local): README 갱신, confluent-kafka 의존성 추가`

## 막히면

- 이 지시서의 내용끼리, 또는 설계 문서와 어긋나 보이면 **추측하지 말고 묻는다.**
- 이 지시서에 없는 파일·명령·컬럼이 필요해 보이면 만들지 말고 먼저 이유를 설명한다.
- 이미지의 환경 변수 이름, Debezium 프로퍼티 이름, 변환(SMT)의 결과 필드 이름이 이 지시서의 가정과 다르면 **임의로 대안을 정하지 말고** 실제로 나온 값과 함께 알린다.
- Kafka·Connect가 계속 기동하지 못하면(메모리 부족 등) 설정을 바꿔 가며 반복하지 말고 로그의 핵심 줄과 함께 알린다.
- 어떤 이유로든 **토픽에 PII가 들어간 것이 확인되면** 다른 작업을 멈추고 바로 알린다.