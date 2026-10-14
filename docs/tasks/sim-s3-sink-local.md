# 작업 지시서: sim/s3-sink-local

> 상태: 진행 전 · 브랜치: `sim/s3-sink-local` · 이전 작업: `sim/cdc-local` · 다음 작업: 탈퇴(`u`)·장애 주입·클라우드 이전

## 목표

Kafka 토픽(회원 이벤트)을 **S3 버킷 `sim-cdc-test`에 Bronze 파일로 쌓는 S3 Sink 커넥터**를 로컬 Connect에 붙이고, **S3에 쌓인 파일이 설계대로인지 확인하는 `sim sink` 명령**을 만든다.

이 브랜치가 끝나면 이 흐름이 돈다.

```
시뮬레이터 → Postgres → Debezium → Kafka 토픽 → S3 Sink → S3 (sim-cdc-test)
                                                   └ bronze/<토픽>/dt=YYYY-MM-DD/*.json
```

이 지시서는 **자기 완결형**이다. `docs/design/member.md`(4-3, 4-5절)가 레포에 있으면 함께 읽되, **이 지시서와 어긋나면 추측하지 말고 묻는다.** 앞 브랜치에서 실제로 정해진 이름(토픽, 테이블, 관리 컬럼)은 **지시서가 아니라 레포의 실제 값**을 따른다 (아래 "시작 전 확인").

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- **커밋하지 않는다.** 파일만 만들고 테스트까지 진행한다. 커밋, push, PR은 사용자가 확인한 뒤 직접 한다.
- **AWS 리소스를 만들거나 바꾸지 않는다.** 버킷 `sim-cdc-test`는 사용자가 이미 만들었다. IAM 사용자·정책, Terraform, 버킷 설정, 수명 주기 규칙은 건드리지 않는다. 필요한 IAM 정책은 문서(`connectors/README.md`)로만 적어 두고, 사용자가 만든다.
- **AWS 자격 증명은 파일에 쓰지 않는다.** 커넥터 JSON, compose, 코드, 로그, 출력 어디에도 키 값이 없어야 한다 (아래 "자격 증명").
- **S3에서 객체를 지우지 않는다.** 코드로도, 명령으로도. 정리가 필요하면 사용자가 실행할 `aws s3 rm ...` 명령을 **출력만** 한다.
- Python 3.12 가상환경(`simulator/.venv`, WSL)과 사용자 컴퓨터의 WSL Docker를 쓴다. 줄바꿈(CRLF/LF)만 바뀐 기존 파일은 건드리지 않고, 필요한 파일만 git 기준(LF)으로 편집한다.
- 로컬 DB와 이미 쌓인 Kafka 토픽을 그대로 쓴다. 지우거나 `sim cdc reset`을 하지 않는다.
- 끝난 뒤 **S3에 올라간 테스트 파일을 어떻게 할지 사용자에게 묻는다.**

## 시작 전 확인 (Claude가 한다)

- 현재 브랜치가 `sim/s3-sink-local`이고, 최신 `main`에서 만들어졌는지 확인한다. `git log`에 `sim/cdc-local` 머지가 보이는지 본다. 아니면 알리고 멈춘다.
- **레포의 실제 값을 읽어서 이 지시서의 `<...>` 자리에 쓴다.** `connectors/member-source.json`, `simulator/src/sim/cdc/params.py`에서 다음을 확인하고 **계획에 적는다**: 토픽 이름(`transforms.route.replacement`, 예: `members-events`), 테이블 이름, 관리 컬럼 이름(`__op`, `__source_ts_ms`, 스냅샷 컬럼).
- Kafka·Connect가 떠 있는지 (`docker compose --profile cdc ps`), `sim cdc status`가 정상인지, 토픽에 메시지가 있는지 확인한다. 없으면 알리고 멈춘다.
- 이 지시서가 저장소 루트에 있으면 `docs/tasks/sim-s3-sink-local.md`로 옮긴다.
- `simulator/.env`에 `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `S3_BUCKET`이 있는지 **있는지 여부만** 확인한다 (값은 출력하지 않는다). 없으면 만들지 말고 어떤 키가 필요한지 알린다. 값은 사용자가 넣는다.
- S3 Sink 플러그인 배포본을 받을 수 있는지(네트워크)와 **라이선스**(Confluent Community License)를 확인해서 계획에 한 줄로 적는다. 받을 수 없으면 대안(Aiven S3 Sink, Apache 2.0)을 **정하지 말고** 알린다.

## 이번 작업에서 확정된 값

값은 파이썬은 `src/sim/sink/params.py`, 커넥터는 `connectors/member-s3-sink.json` **한 곳**에 둔다.

| 항목 | 값 | 출처 |
|---|---|---|
| 대상 버킷 | `sim-cdc-test` (환경 변수 `S3_BUCKET`) | 사용자 결정 |
| 읽는 토픽 | `<실제 토픽>` 하나. **source 커넥터가 내보내는 토픽과 같아야 한다** | 설계 결정 |
| 파일 형식 | **JSON Lines** (한 줄에 JSON 하나, `[ ]`로 감싸지 않음). 확장자 `.json` | 지시서 기본값 |
| 파티션 | **`dt=YYYY-MM-DD` 하나, 일별, UTC** | 설계 결정 (4-3절) |
| `dt`의 기준 | **Kafka 레코드 시각(수집 시각)**, UTC. 가입일이 아니다 | 설계 결정 (수집 시각 UTC) |
| 객체 경로 | `bronze/<토픽>/dt=YYYY-MM-DD/<토픽>+<파티션>+<시작offset>.json` (커넥터 기본 규칙, `topics.dir=bronze`) | 지시서 기본값 |
| 파일을 끊는 조건 | 건수 `flush.size=1000` **또는** 시간 `rotate.schedule.interval.ms=30000`(30초). **로컬 테스트 값이다.** 실제 값은 팀에서 정한 뒤 바꾼다 | 지시서 기본값 (정해진 적 없음) |
| 값 변환 | `JsonConverter`, `schemas.enable=false` (source와 같은 방식) | 지시서 기본값 |
| 압축 | 없음 | 지시서 기본값 |
| 전달 보장 | **at-least-once.** 재시작·오류 뒤에 같은 메시지가 파일에 두 번 들어갈 수 있다. Silver에서 중복 제거 | 설계 결정 (Silver에서 `member_id` 기준 중복 제거) |
| 읽는 시작 위치 | 처음부터 (이미 쌓인 10만 건 스냅샷 포함) | 지시서 기본값 |
| 새 필드 이름 | 만들지 않는다. 토픽 메시지의 13개 필드를 그대로 쓴다 | 설계 결정 |

### 구성 요소

**1) Connect 이미지에 S3 Sink 플러그인 추가.** Debezium 이미지에는 S3 Sink가 없다.

- `simulator/connect/Dockerfile`(새 파일)을 만든다: 지금 쓰는 `quay.io/debezium/connect:<태그>`를 그대로 `FROM`으로 쓰고, **버전을 고정한** S3 Sink 플러그인 배포본을 받아 Connect 플러그인 경로에 풀어 넣는다 (`latest` 금지, 받은 파일의 체크섬 확인이 가능하면 한다).
- `docker-compose.yml`의 `connect` 서비스가 이 Dockerfile로 빌드되게 바꾼다. 다른 설정(리스너, 메모리, 포트 `127.0.0.1` 바인딩, 비밀번호 환경 변수)은 **그대로** 둔다.
- 플러그인이 올라왔는지는 `curl localhost:8083/connector-plugins`에 `S3SinkConnector`가 있는지로 확인한다.

**2) 자격 증명.** 키는 코드·JSON에 없다.

- `simulator/.env`(gitignore 대상)에 `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `S3_BUCKET`을 둔다. `.env.example`에는 **더미 값**만 추가한다.
- compose의 `connect` 서비스에 이 환경 변수들을 **이름만** 전달한다 (`environment:`에 `AWS_ACCESS_KEY_ID`처럼 값 없이 적어 `.env`에서 가져오게). 커넥터는 환경 변수 자격 증명(기본 자격 증명 체인)을 쓰므로 JSON에는 키 설정이 없다.
- **`docker compose config`나 `env` 출력에는 키 값이 나온다.** 이 출력을 보고·로그·화면 공유에 쓰지 않는다. 지시서의 모든 확인은 키 값을 출력하지 않는 방식으로 한다.
- 필요한 IAM 권한은 **버킷 `sim-cdc-test`의 `bronze/*` 경로로만** 제한한다 (목록 조회, 객체 쓰기·읽기, 멀티파트 업로드 중단·조회). 정확한 액션 목록은 사용하는 커넥터 버전 문서에서 확인해 `connectors/README.md`에 정책 예시(JSON)로 적는다. 이 정책은 사용자가 만든다.

## 만드는 것

### 1. 커넥터 설정 (`connectors/member-s3-sink.json`)

평평한 JSON이다 (`name` 포함). 프로퍼티 이름이 사용하는 커넥터 버전과 다르면 문서에 맞게 고치고 **무엇을 바꿨는지 알린다.**

| 키 | 값 | 이유 |
|---|---|---|
| `name` | `member-s3-sink` | |
| `connector.class` | `io.confluent.connect.s3.S3SinkConnector` | |
| `tasks.max` | `1` | 로컬은 하나로 충분 |
| `topics` | `<실제 토픽>` | source와 같은 토픽 |
| `s3.bucket.name` | `sim-cdc-test` | 사용자가 만든 버킷 |
| `s3.region` | 사용자의 리전 (`.env`의 `AWS_REGION`과 같아야 함) | |
| `topics.dir` | `bronze` | 경로 접두사 |
| `storage.class` | `io.confluent.connect.s3.storage.S3Storage` | |
| `format.class` | `io.confluent.connect.s3.format.json.JsonFormat` | JSON Lines |
| `key.converter` / `value.converter` | `JsonConverter`, 둘 다 `schemas.enable=false` | 토픽 메시지가 값만 있는 JSON이다 |
| `schema.compatibility` | `NONE` | 스키마 없는 JSON |
| `partitioner.class` | `io.confluent.connect.storage.partitioner.TimeBasedPartitioner` | |
| `path.format` | `'dt'=YYYY-MM-dd` | Hive 방식 폴더 이름 |
| `partition.duration.ms` | `86400000` | 하루 |
| `timezone` | `UTC` | |
| `locale` | `en-US` | 이 파티셔너가 요구하는 설정 |
| `timestamp.extractor` | `Record` | Kafka 레코드 시각. 다시 읽어도 같은 폴더에 들어간다 |
| `flush.size` | `1000` | 로컬 테스트 값 |
| `rotate.schedule.interval.ms` | `30000` | 트래픽이 적어도 30초마다 파일을 끊는다. 로컬 테스트 값 |
| `s3.compression.type` | `none` | |

**주의:**
- JSON에 **키 이름이나 값이 들어가는 설정(`aws.access.key.id` 등)을 쓰지 않는다.**
- 이 커넥터를 등록하기 전에 source 커넥터 JSON의 컬럼 목록·토픽이 그대로인지 확인한다. S3에 PII가 들어가지 않는 것은 **source의 `column.include.list`가 지킨다.** 이 커넥터에는 컬럼을 거르는 설정이 없고, 들어온 것을 그대로 쓴다.
- `Record` 시각 추출이 이 이미지에서 기대대로 동작하지 않으면 (폴더 날짜가 수집 시각과 다르면) 다른 값(`Wallclock`)으로 바꾸지 말고 **실제 결과와 함께 알린다.**
- 실제 출력이 **JSON 줄 단위가 아니라 `[ ... ]` 배열 하나**라면 설정을 억지로 바꾸지 말고 알린다.

### 2. 파이썬 (`src/sim/sink/`)

| 파일 | 내용 |
|---|---|
| `params.py` | 커넥터 이름, 버킷 환경 변수 이름, 경로 접두사 `bronze`, 파일 이름 정규식, 폴더 이름 정규식(`dt=YYYY-MM-DD`), 기본 주소 |
| `s3.py` | S3 읽기 전용 도우미 (`boto3`): 목록 조회, 객체 읽기, 버킷 접근 확인. **쓰기·삭제 함수를 만들지 않는다** |
| `checks.py` | 검증 로직 **순수 함수**. 객체 목록과 줄 목록을 받아 항목별 통과/실패를 돌려준다. S3·Kafka를 부르지 않는다 (그래서 단위 테스트 가능). **`sim/cdc/checks.py`의 필드·PII 검사를 가져다 쓴다** (같은 기준) |
| `cli.py` | `typer` 하위 앱 `sink` (`setup`, `status`, `verify`, `reset`). `sim/cli.py`에서 `app.add_typer(sink_app, name="sink")`로 연결 |

**의존성 추가:** `boto3`를 실행용 의존성에 추가한다. 이 지시서가 허용한 **유일한** 추가다 (`confluent-kafka`는 이미 있다). `pyproject.toml`과 `simulator/CLAUDE.md`의 의존성 줄을 함께 고친다.

**설정 추가** (`common/config.py`, `.env.example`에는 더미 값): `S3_BUCKET`, `AWS_REGION`. (`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`는 코드가 읽지 않는다. `boto3`가 환경 변수에서 직접 가져간다.)

### 3. CLI

```
sim sink setup  [--config ../connectors/member-s3-sink.json]
sim sink status
sim sink verify
sim sink reset  [--yes]
```

**`setup`**

1. 설정 파일을 읽고 **안전장치 검사**를 한다 (아래). 어긋나면 등록하지 않는다.
2. **S3 접근 확인**: 버킷이 존재하고 `bronze/` 경로를 조회할 수 있는지 확인한다. 실패하면 이유(권한 없음 / 버킷 없음 / 리전 다름 / 키 없음)를 **키 값 없이** 알리고 멈춘다.
3. Connect에 S3 Sink 플러그인이 올라와 있는지 확인한다. 없으면 이미지를 다시 빌드하라고 안내한다.
4. 같은 이름의 커넥터가 있으면 **아무것도 바꾸지 않고** 상태만 보여 준다.
5. 없으면 등록하고 `RUNNING`이 될 때까지 최대 60초 기다린다. "`sim sink status`로 S3에 파일이 생기는지 보세요"라고 안내한다.

**안전장치 (등록 전 설정 검사)**
- `topics`가 source 커넥터 JSON이 내보내는 토픽(`transforms.route.replacement`)과 같다
- 키 이름·시크릿 값이 JSON에 **없다** (`aws.access.key.id`, `aws.secret.access.key`, 또는 `AKIA`로 시작하는 문자열)
- `partitioner.class`가 시간 기반이고 `timezone`이 `UTC`, `path.format`이 `'dt'=YYYY-MM-dd`
- `format.class`가 JSON 형식, `s3.bucket.name`이 `.env`의 `S3_BUCKET`과 같다

**`status`** (읽기 전용): 커넥터·task 상태, **소비자 그룹이 얼마나 밀렸는지**(토픽 끝 offset − 커넥터가 읽은 offset), S3의 `bronze/<토픽>/` 아래 **날짜별 파일 수·총 크기·가장 최근 파일 시각**. 객체 내용은 읽지 않는다.

**`verify`** — 아래 "verify".

**`reset`** (`--yes`가 없으면 `[y/N]`): 커넥터 정지 → 소비자 그룹 offset 삭제 → 커넥터 삭제. **S3 객체는 건드리지 않는다.** 대신 아래를 **출력만** 한다: "S3에는 파일이 그대로 남아 있습니다. 지우려면 직접 실행: `aws s3 rm s3://<버킷>/bronze/<토픽>/ --recursive`". 이 명령을 실행하지 않는다.

> reset 뒤에 다시 `setup`하면 토픽을 처음부터 다시 읽어 **같은 데이터가 S3에 한 번 더 쌓인다** (파일 이름의 offset 구간이 겹치지 않으면 중복 파일이 생긴다). 이 경고를 reset 출력과 README에 적는다.

### verify

S3의 `bronze/<토픽>/`을 읽어 항목별 **통과/실패** 표를 보여 주고, 하나라도 실패하면 종료 코드 1이다. **토픽 끝 offset**(Kafka)과 S3 내용을 대조하는 항목이 있어서 Kafka도 읽는다. S3 Sink는 파일을 모았다가 쓰므로, `verify`는 시작할 때 **"밀린 양이 0이고 마지막 파일 이후 30초 이상 지났는지"** 를 먼저 확인하고, 아니면 "아직 쓰는 중입니다. 잠시 뒤 다시 실행하세요"라고 알리고 종료 코드 2로 멈춘다 (실패가 아니다).

| # | 확인 | 기준 |
|---|---|---|
| 1 | 커넥터 | `RUNNING`(커넥터·task), 설정의 `topics`가 source 토픽과 같다 |
| 2 | 경로 | 모든 객체 키가 `bronze/<토픽>/dt=YYYY-MM-DD/<토픽>+<파티션>+<offset>.json` 형식 |
| 3 | 형식 | 모든 파일이 **한 줄에 JSON 하나**. `[`로 시작하는 배열 파일 0개, 빈 줄·깨진 줄 0개 |
| 4 | 필드 | 모든 행의 키 집합이 정확히 **10개 + 관리 컬럼 3개** (cdc의 검사와 같은 기준) |
| 5 | **PII 없음** | 파일 원문에서 금지 필드 이름, `@example\.com`, `010-\d{4}-\d{4}`, `\$2b\$12\$` 모두 0건. **객체 키(경로)에도** 같은 패턴 0건 |
| 6 | 시각 | `signup_at`/`created_at`/`withdrawn_at`(값이 있을 때)이 모두 `Z`로 끝나는 UTC 문자열 |
| 7 | `dt` 폴더 | `dt`가 실제 날짜이고(`2026-10-14` 같은 형식), 파일에 든 행의 `created_at`/`__source_ts_ms`보다 **너무 이르지 않다** (수집일 ≥ 데이터 생성일(UTC)). 폴더 날짜가 **오늘(UTC) 기준 +1일을 넘지 않는다** |
| 8 | offset 연속성 | 파티션별로 파일 이름의 offset 구간을 이어 보면 **빈 구간 0개** (누락 없음). 겹치는 구간은 **중복 후보로 개수만 보고**한다 (실패 아님) |
| 9 | 행 수 | S3의 전체 행 수 ≥ 토픽의 끝 offset 합계(= 토픽에 들어간 메시지 수). **부족하면 실패, 초과분은 "중복 N건"으로 보고** (at-least-once) |
| 10 | 회원 대조 | S3에 나온 `member_id` 집합 = Kafka 토픽에 나온 `member_id` 집합. (이미 `sim cdc verify`가 통과한 토픽 기준) |
| 11 | 파일 크기 | 가장 작은 파일·평균 크기·파일 수를 **보고만** 한다 (작은 파일이 많으면 경고. 통과/실패 아님) |

**출력 규칙 (PII 안전):** 실패했을 때도 값을 출력하지 않는다. 필드 이름, 건수, 객체 키(경로), 최대 5개의 `member_id`만 보여 준다. 파일 원문을 로컬에 저장하지 않는다 (메모리에서 한 줄씩 처리하고 버린다). 자격 증명 값은 어떤 출력에도 없다.

## PII 안전 (중요)

| 규칙 | 구현 |
|---|---|
| S3에는 **이미 거른 13개 필드만** 간다 | source 커넥터의 `column.include.list`가 지킨다. sink는 거르지 않는다. 그래서 `verify` 4·5번이 S3에서 **다시 확인**한다 |
| 자격 증명이 **어디에도 없다** | 커넥터 JSON, compose 파일, 코드, 테스트, 로그, 출력. 단위 테스트로 `AKIA` 패턴·`aws.secret` 문자열이 레포 파일에 없는지 확인한다 |
| S3 쓰기·삭제 코드가 없다 | `s3.py`는 읽기 전용 |
| 객체 키에 값이 없다 | 경로는 토픽 이름과 날짜·파티션·offset만 쓴다 |
| 버킷이 공개되지 않는다 | (확인만, 변경 안 함) `status`에서 버킷의 공개 차단 설정을 **조회 가능하면** 보고하고, 조회 권한이 없으면 "확인 못 함"이라고만 한다 |

## 테스트

**단위 테스트 (S3·Kafka·Docker 없이 돈다, 기본 `pytest`에 포함):**

- **커넥터 설정 파일**(레포의 실제 `connectors/member-s3-sink.json`): `topics`가 source 커넥터 JSON의 라우팅 토픽과 같다, 시간 파티셔너·`UTC`·`'dt'=YYYY-MM-dd`, JSON 형식, **시크릿 키·`AKIA` 문자열 없음**
- 안전장치 검사 함수: 토픽이 다름 / 키 이름 포함 / 시간대가 UTC가 아님 / 형식이 다름 → 각각 실패
- `checks.py`에 **가짜 객체 목록과 줄**을 넣어 항목별로 확인:
  - 정상 모음은 전부 통과
  - 경로가 규칙에 안 맞는 키 → 2번 실패
  - `[`로 시작하는 배열 파일, 깨진 줄 → 3번 실패
  - 값에 `email` 필드 → 4·5번 실패
  - 객체 키에 `010-1234-5678` 모양 → 5번 실패
  - `Z`가 없는 시각 → 6번 실패
  - offset 구간에 빈 곳 → 8번 실패, 겹침만 있으면 통과하고 개수 보고
  - 행 수가 토픽보다 적음 → 9번 실패, 많음 → 통과하고 중복 개수 보고
  - `member_id` 집합이 다름 → 10번 실패
- 아직 쓰는 중(밀림 > 0 또는 마지막 파일이 30초 이내)이면 `verify`가 **실패가 아니라 종료 코드 2**
- 출력 안전: 실패한 검증의 출력에 가짜 데이터에 넣은 PII 문자열과 가짜 자격 증명 문자열이 없다
- 레포 파일 중 어디에도 자격 증명으로 보이는 문자열(`AKIA[0-9A-Z]{16}`)이 없다

**S3 통합 테스트는 만들지 않는다.** 실제 AWS를 부르는 테스트는 `pytest`에 넣지 않는다. 아래 "완료 확인"의 실제 실행이 통합 검증이다.

## 만들지 않는 것

- AWS 리소스 생성·변경: IAM, Terraform, 버킷 생성·설정, 수명 주기 규칙, 암호화 설정
- S3 객체 삭제 기능 (명령만 출력)
- Parquet·Avro 같은 스키마 있는 형식, 스키마 레지스트리
- Glue 카탈로그, Athena 테이블, Silver 이후 변환
- 여러 토픽·여러 테이블 (회원 토픽 하나만)
- MSK Connect, EKS 배포, 클라우드 이전
- 탈퇴(`u`) 생성, 장애 주입 자동화
- `sim cdc`의 동작 변경 (재사용만 한다)
- 설계 문서(`docs/design/*`) 수정

## 작업 순서

**커밋하지 않는다.** 각 단계가 끝나면 그 단계의 테스트를 돌려 확인하고 다음 단계로 간다.

1. 시작 전 확인을 하고, **계획을 먼저 제시해 사용자 확인을 받는다.** 계획에 실제 토픽 이름, 고른 플러그인 배포본과 버전, 라이선스, 지시서 값에서 바꾼 것을 적는다
2. `connect/Dockerfile`, compose 수정, `.env.example` 더미 값, 설정 파일 `member-s3-sink.json` + `connectors/README.md`(IAM 정책 예시 포함) + 커넥터 설정 단위 테스트 → 이미지를 빌드하고 `connector-plugins`에 `S3SinkConnector`가 보이는지까지 확인 (아직 등록 전)
3. `sink/params.py`, `s3.py`, `cli.py`의 `setup`·`status`·`reset` + 단위 테스트 (`boto3` 추가)
4. `sink/checks.py` + 가짜 데이터 단위 테스트
5. `verify` 명령 (S3·Kafka 읽기, 밀림 확인)
6. `simulator/README.md`에 `## S3 Sink` 절 추가, `simulator/CLAUDE.md` 의존성 줄에 `boto3` 추가
7. "완료 확인"을 **실제로 실행**해서 결과 보고

## 완료 확인

아래를 **실제로 실행**해서 결과를 보고한다. 모든 출력에 자격 증명 값이 없어야 한다.

- [ ] `pip install -e ".[dev]"`, `ruff check .`, `ruff format --check .`, `pytest`(단위) 통과
- [ ] 레포의 파일에 자격 증명(`AKIA...`, 시크릿 키)이 없다. `git status`에 `.env`가 없다
- [ ] 이미지 빌드 성공, `curl localhost:8083/connector-plugins`에 `S3SinkConnector`가 있고 Debezium 플러그인도 그대로 있다. 기존 `member-source` 커넥터가 계속 `RUNNING`이다
- [ ] `sim sink setup`의 S3 접근 확인이 통과한다 (실패하면 이유를 보고하고 멈춘다)
- [ ] `sim sink status`로 파일이 생기는 것을 확인한다. 걸린 시간과 처음 쌓인 10만 건이 **파일 몇 개**로 나뉘었는지 보고
- [ ] **실제 S3의 폴더·파일 이름을 보고한다** (`bronze/<토픽>/dt=.../...json`). `dt=` 날짜가 오늘(UTC)과 맞는지, 파일이 JSON Lines인지 (샘플은 **키 이름만** 보고, 값은 출력하지 않는다)
- [ ] `sim sink verify` → **11개 항목 전부 통과** (9번 초과분이 있으면 "중복 N건"으로 보고)
- [ ] `sim member live --mode steady --max-signups 200 ...` (속도를 크게) → 몇 분 뒤 새 파일이 생기고 `sim sink verify`가 통과한다. 행 수가 **토픽 끝 offset과 일치**한다
- [ ] **재시작 확인:** `docker compose stop connect` → `sim member live --max-signups 10 ...` → `docker compose start connect` → 잠시 뒤 `sim sink verify`: **누락 0** (8번), 중복이 생겼다면 개수 보고
- [ ] AWS 콘솔 또는 CLI에서 사용자가 직접 확인할 수 있게 **버킷 경로와 파일 수·총 크기**를 알려 준다
- [ ] 모든 실행 출력을 파일로 저장해 `grep -E "example\.com|010-|AKIA"` → **결과 없음**
- [ ] **커밋하지 않았다.** 줄바꿈만 바뀐 기존 파일을 건드리지 않았다
- [ ] 끝나면 **사용자에게 묻는다:** S3 테스트 파일을 남길지 (지운다면 사용자가 실행할 `aws s3 rm` 명령을 알려 준다), 커넥터를 남길지(`sim sink reset`)

## README 갱신

- `simulator/README.md`: `## S3 Sink` 절 (한 줄 요약, 켜는 순서 `.env에 키 → docker compose --profile cdc build → up → sim sink setup → sim sink status → sim sink verify`, S3 경로 규칙과 `dt=`가 수집일이라는 점, at-least-once라서 Silver에서 중복 제거가 필요하다는 점, `reset` 뒤 중복이 생긴다는 점, 자격 증명을 파일에 쓰지 않는 규칙)
- `connectors/README.md`: `member-s3-sink.json` 설명(값마다 이유), **IAM 정책 예시**(버킷 `sim-cdc-test`의 `bronze/*`만), 로컬에서 클라우드로 옮길 때 바뀌는 값(자격 증명 대신 역할 사용, 플러시 값)
- `simulator/CLAUDE.md`: 의존성 줄에 `boto3` 추가 (이 한 줄만)

## 참고: 사용자가 나중에 커밋할 때의 제안 메시지

(Claude는 커밋하지 않는다.)

1. `feat(sink): Connect 이미지에 S3 Sink 플러그인과 커넥터 설정 추가`
2. `feat(sink): S3 Sink 등록·상태·초기화 명령 추가`
3. `feat(sink): S3 파일 검증 로직 추가`
4. `feat(sink): S3와 토픽 대조, verify 명령 추가`
5. `docs(sink): S3 Sink README 갱신`

## 막히면

- 이 지시서의 내용끼리, 또는 설계 문서와 어긋나 보이면 **추측하지 말고 묻는다.**
- 이 지시서에 없는 파일·명령·AWS 리소스가 필요해 보이면 만들지 말고 먼저 이유를 설명한다.
- 플러그인 프로퍼티 이름, 출력 형식, 폴더 날짜 등이 지시서의 가정과 다르면 **임의로 대안을 정하지 말고** 실제로 나온 값과 함께 알린다.
- 권한 오류(`AccessDenied` 등)가 나면 IAM을 고치려 하지 말고, 어떤 동작이 막혔는지만 (키 값 없이) 알린다. 정책은 사용자가 만든다.
- **S3에 PII가 들어간 것이 확인되면** 다른 작업을 멈추고 바로 알린다. 파일을 지우지 말고 어디에 있는지만 알린다.