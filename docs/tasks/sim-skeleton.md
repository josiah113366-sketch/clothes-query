# 작업 지시서: sim/skeleton

> 상태: 진행 전 · 브랜치: `sim/skeleton` · 다음 작업: `sim/member-baseline`

## 목표

시뮬레이터 작업 전체가 올라탈 **빈 골격과 규칙**을 만든다. 회원 생성 로직은 만들지 않는다. 이 브랜치가 끝나면 `docker compose up`으로 빈 회원 테이블이 있는 로컬 PostgreSQL이 뜨고, `sim --help`가 동작한다.

이 지시서는 **자기 완결형**이다. 필요한 규칙 문서의 내용이 아래 부록에 들어 있고, DDL 명세가 본문에 있다. 외부 파일(zip 등)은 필요 없다.

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- **커밋하지 않는다.** 파일만 만든다. 사용자가 확인한 뒤 직접 커밋한다. (아래 "작업 순서"의 단계는 커밋 단위가 아니라 작업 순서다.)
- 로컬 가상환경은 **Python 3.12**로 만든다 (`py -3.12 -m venv .venv`).
- 이 컴퓨터에는 `psql`이 없다. DB 확인은 `docker compose exec postgres psql -U sim -d clothes`로 한다.
- 줄바꿈(CRLF/LF)만 바뀐 파일(`.gitignore`, `README.md`, `infra/` 아래 파일 등)은 **건드리지 않는다.** `.gitattributes`도 이번에는 추가하지 않는다.
- 설계 문서(`docs/design/member.md`, `docs/design/simulator-member.md`)는 이 브랜치에서 **만들지 않는다.** 사용자가 따로 추가한다. 없으면 없는 대로 진행하고, DDL은 이 지시서의 표를 기준으로 만든다.

## 시작 전 확인 (Claude가 한다)

- 현재 브랜치가 `sim/skeleton`이고 인프라 머지 커밋(`infra(bootstrap): Terraform state 저장용 S3 버킷 추가`)을 포함하는지 `git log --oneline -3`으로 확인한다. 아니면 만들지 말고 알린다.
- Python 3.12, Docker가 있는지 확인한다.

## 먼저 할 일: 파일 배치 (Claude가 한다)

1. 이 지시서가 저장소 루트에 있으면 `docs/tasks/sim-skeleton.md`로 옮긴다. (`docs/tasks/` 폴더가 없으면 만든다.)
2. `git mv CLAUDE.md infra/CLAUDE.md` — 지금 루트에 있는 인프라 규칙 파일을 옮긴다. **내용은 수정하지 않는다.** 이 이동이 이 브랜치에서 `infra/`를 바꾸는 **유일한** 변경이다.
3. 새 루트 `CLAUDE.md`를 **부록 A의 내용 그대로** 만든다.
4. `simulator/CLAUDE.md`를 **부록 B의 내용 그대로** 만든다.

3, 4번은 한 글자도 바꾸지 말고 그대로 쓴다. 고치고 싶은 부분이 있으면 쓰기 전에 먼저 말한다.

## 만드는 것

### 1. `.gitignore` 추가

루트 `.gitignore` 맨 아래에 다음만 추가한다. (`.env`, `.venv`, `__pycache__`, `.pytest_cache`는 이미 있다.)

```
# Simulator
simulator/.local/
```

### 2. `simulator/` 골격

- `pyproject.toml`: 이름 `clothes-query-simulator`, Python `>=3.12`, 실행용 `faker`, `psycopg[binary]`, `typer` / 개발용 `pytest`, `ruff`. 명령 `sim = "sim.cli:app"`. `ruff` 줄 길이 100.
- `src/sim/__init__.py`: 버전 문자열
- `src/sim/cli.py`: `typer` 앱. 지금은 `version` 명령만 둔다.
- `src/sim/common/`, `controller/`, `member/`, `behavior/`: 각각 빈 `__init__.py`만
- `tests/test_smoke.py`: `sim` 패키지를 import할 수 있고 `version` 명령이 동작하는지만 확인
- `Dockerfile`: `python:3.12-slim`, 의존성 설치, `ENTRYPOINT ["sim"]`
- `.env.example`: `DATABASE_URL=postgresql://sim:sim@localhost:5432/clothes` (로컬 전용 더미 값이라고 주석)

### 3. `db/schema/` DDL

파일은 순서대로 `001_member.sql`, `002_member_archive.sql`이다. 아래 표가 기준이다.

**`member`** (컬럼 15개)

| 컬럼 | 타입 | 제약 |
|---|---|---|
| `member_id` | `uuid` | PK |
| `name` | `text` | NULL 허용 |
| `email` | `text` | NULL 허용, UNIQUE |
| `phone` | `text` | NULL 허용, UNIQUE |
| `birth_date` | `date` | NULL 허용 |
| `gender` | `text` | NOT NULL, `'F'` 또는 `'M'` |
| `signup_at` | `timestamptz` | NOT NULL |
| `signup_channel` | `text` | NOT NULL, `'web'` 또는 `'app'` |
| `marketing_consent` | `boolean` | NOT NULL |
| `status` | `text` | NOT NULL, `'ACTIVE'` 또는 `'WITHDRAWN'` |
| `withdrawn_at` | `timestamptz` | NULL 허용 |
| `created_at` | `timestamptz` | NOT NULL, `DEFAULT now()` |
| `password_hash` | `text` | NULL 허용 |
| `region_sigungu` | `text` | NOT NULL |
| `age_band` | `text` | NOT NULL, `'~19'`, `'20s'`, `'30s'`, `'40s'`, `'50s'`, `'60s'`, `'70+'` 중 하나 |

테이블 CHECK 제약 2개:
- `status = 'ACTIVE'`이면 `withdrawn_at IS NULL`, `status = 'WITHDRAWN'`이면 `withdrawn_at IS NOT NULL`
- `withdrawn_at`이 있으면 `withdrawn_at >= signup_at`

탈퇴하면 `name`, `email`, `phone`, `birth_date`, `password_hash`가 NULL이 되므로 이 다섯 컬럼은 NULL을 허용해야 한다. PostgreSQL의 UNIQUE는 NULL 여러 개를 허용한다.

**`member_archive`**

| 컬럼 | 타입 | 제약 |
|---|---|---|
| `member_id` | `uuid` | PK, `member(member_id)` 참조 |
| `name` | `text` | NOT NULL |
| `email` | `text` | NOT NULL |
| `phone` | `text` | NOT NULL |
| `archived_at` | `timestamptz` | NOT NULL, `DEFAULT now()` |

**이 브랜치에서 만들지 않는 것:** `orders` 등 주문 테이블, 복제 슬롯·publication·Debezium 계정(→ `sim/cdc-local`), 인덱스(필요가 확인되면 이후 브랜치에서).

`db/README.md`에 테이블 목적, 파일 순서, 컬럼 표, 로컬에서 적용하는 방법을 적는다. 회원 설계 문서(`docs/design/member.md`)가 따로 추가될 예정이라는 점도 한 줄 적는다.

### 4. `simulator/docker-compose.yml`

- 서비스 `postgres`: `postgres:16`, 포트 `5432`, DB `clothes`, 사용자 `sim`, 비밀번호 `sim`(로컬 전용)
- 시작 옵션 `-c wal_level=logical` (이후 Debezium용. RDS의 `rds.logical_replication`에 해당)
- `../db/schema`를 `/docker-entrypoint-initdb.d`에 읽기 전용으로 마운트해서 시작할 때 DDL이 적용되게 한다
- `healthcheck` 설정
- 데이터 볼륨은 이름 있는 볼륨 하나
- Kafka·Debezium은 **넣지 않는다** (`sim/cdc-local`)

### 5. `docs/tasks/_template.md`

이 파일(`sim-skeleton.md`)의 절 구성(상태, 목표, 먼저 읽을 것, 특례, 시작 전 확인, 만드는 것, 만들지 않는 것, 작업 순서, 완료 확인, README 갱신)을 그대로 따른 **빈 양식**을 만든다.

### 6. `simulator/README.md`

새로 만든다. 다음 절을 둔다.

- 한 문단 소개: 가상 쇼핑몰의 회원 데이터를 만들어 RDS(PostgreSQL)에 쓰는 시뮬레이터이고, 설계는 `docs/design/`에 있다
- `## 코드 구조`: 부록 B의 폴더 구조와 각 폴더의 역할 (모듈끼리 import하지 않고 DB와 컨트롤러 신호로만 주고받는다는 점 포함)
- `## 로컬 실행`: 가상환경 만들기, `pip install -e ".[dev]"`, `docker compose up -d`, `sim --help`, `pytest`, `ruff`, 로컬 DB 접속 방법 (`docker compose exec postgres psql -U sim -d clothes`)

## 만들지 않는 것

- 회원 생성 함수, 지역 로더, 베이스라인 적재, 신규 가입, 컨트롤러 동작 (→ 이후 브랜치)
- 지역 CSV (→ `sim/member-baseline`)
- Kafka, Debezium, 커넥터 설정 (→ `sim/cdc-local`)
- `infra/` 변경 (위 `CLAUDE.md` 이동 한 건 제외), Terraform
- 설계 문서(`docs/design/*`)

## 작업 순서

1. 시작 전 확인을 하고, **계획을 먼저 제시해 사용자 확인을 받는다**
2. 파일 배치 (이 지시서 이동, `CLAUDE.md` 이동, 새 `CLAUDE.md` 2개)
3. `.gitignore` 추가
4. `simulator/` 골격
5. `db/schema/` DDL과 `db/README.md`
6. `simulator/docker-compose.yml`
7. `docs/tasks/_template.md`
8. `simulator/README.md`
9. 아래 "완료 확인"을 실행하고 결과 보고

## 완료 확인

아래를 **실제로 실행**해서 결과를 보고한다.

- [ ] `pip install -e ".[dev]"` 성공 (Python 3.12 가상환경)
- [ ] `sim --help`, `sim version` 동작
- [ ] `ruff check .`, `ruff format --check .`, `pytest` 통과
- [ ] `docker compose up -d` 후 `docker compose exec postgres psql -U sim -d clothes`에서 `\d member`, `\d member_archive`가 위 표와 일치
- [ ] `SHOW wal_level;` 결과가 `logical`
- [ ] 아래 제약을 실제로 확인
  - [ ] `status='ACTIVE'`인데 `withdrawn_at`이 있는 행을 넣으면 **실패**
  - [ ] `email`, `phone`이 NULL인 `WITHDRAWN` 행 두 개를 넣으면 **성공** (UNIQUE가 NULL 중복을 허용)
  - [ ] 같은 `email`을 가진 두 행을 넣으면 **실패**
  - [ ] `age_band='25s'`처럼 허용 목록 밖 값을 넣으면 **실패**
  (확인용 행은 확인 후 삭제하거나 볼륨을 지운다.)
- [ ] `docker build -t sim-local ./simulator` 성공
- [ ] `git status`에 `.env`, `simulator/.local/`, 시드 파일이 없다
- [ ] `git diff --ignore-space-at-eol --stat main`에서 `infra/`는 `CLAUDE.md` 이동 외에 바뀐 것이 없다
- [ ] 줄바꿈만 바뀐 기존 파일을 내가 건드리지 않았다

## README 갱신

- `simulator/README.md`: 신규 (위 6번)
- `db/README.md`: 신규

## 막히면

- 이 지시서의 내용끼리 어긋나 보이면 **추측하지 말고 묻는다.**
- 이 지시서에 없는 파일이 필요해 보이면 만들지 말고 먼저 이유를 설명한다.

---

## 부록 A. 루트 `CLAUDE.md` (그대로 만든다)

````markdown
# clothes-query 프로젝트 공통 규칙

폴더별 규칙은 그 폴더의 `CLAUDE.md`가 따로 정한다. **작업하는 폴더의 `CLAUDE.md`를 먼저 읽는다.**

| 폴더 | 규칙 문서 |
|---|---|
| `infra/` | `infra/CLAUDE.md` |
| `simulator/` | `simulator/CLAUDE.md` |
| `db/`, `connectors/`, `docs/` | 별도 규칙 없음. 이 문서와 해당 폴더의 `README.md`를 따른다 |

## 프로젝트 한눈에

H&M 상품 데이터를 바탕으로 한 가상 쇼핑몰 데이터 플랫폼이다. 시뮬레이터(로그 제너레이터)가 만든 회원·행동 데이터가 `RDS(PostgreSQL) → Debezium → Kafka(EKS) → S3 데이터 레이크`로 흐르고, AI 관제 에이전트가 문제의 원인을 찾는다. 리전은 도쿄(`ap-northeast-1`)다.

## Git

- 브랜치는 **최신 `main`** 에서 만든다. 이름은 `<영역>/<작업>`이다. (예: `infra/network`, `sim/skeleton`, `db/member-schema`)
- `main`에 직접 커밋하지 않는다.
- 커밋 메시지는 `<영역>(<작업>): <한국어 요약>` 형식이다. (예: `infra(bootstrap): Terraform state 저장용 S3 버킷 추가`)
- PR 하나에는 한 영역만 담는다. 인프라 변경과 앱 코드를 한 PR에 섞지 않는다.
- **push, PR 생성, 머지는 사용자가 확인한 뒤에 한다.** Claude는 브랜치에 커밋까지만 한다.

## 문서

- 폴더마다 `README.md`를 둔다 (목적, 의존하는 것, 실행 방법).
- 설계 문서는 `docs/design/`, 작업 지시서는 `docs/tasks/`에 둔다. 작업 지시서는 브랜치 하나에 하나이고, 머지 후에도 남기며 맨 위에 `상태: 완료`를 적는다.
- 설계 문서의 상태 표현은 **결정 / 제안 / 미정**이다.
  - **결정**만 구현한다.
  - **제안**과 **미정**은 구현 전에 사용자에게 묻는다. 작업 지시서가 기본값을 정해 준 경우만 그 기본값으로 만든다.
  - 설계에 없는 것을 새로 만들어 넣지 않는다.

## 보안

- 이 레포는 **공개**다. 비밀값(키, 비밀번호), AWS 계정 ID, 엔드포인트를 커밋하지 않는다.
- `.env`는 커밋하지 않는다. 더미 값만 담은 `.env.example`만 커밋한다.
- 개인정보(PII)는 가짜 데이터여도 **평문 파일(시드 파일 등)을 커밋하지 않는다.** 로그와 콘솔에도 PII를 출력하지 않는다.

## 작업 방식

1. 시작하기 전에 작업 지시서와 관련 문서를 읽고 **계획을 먼저 제시**한다.
2. 단계마다 작은 커밋으로 나눈다.
3. 문서끼리 어긋나거나 막히면 추측하지 말고 묻는다.
4. 끝나면 작업 지시서의 "완료 확인"을 **실제로 실행**해서 결과를 보고한다.
````

---

## 부록 B. `simulator/CLAUDE.md` (그대로 만든다)

````markdown
# simulator/ 작업 규칙

이 문서는 `simulator/` 폴더 작업에 적용된다. 프로젝트 공통 규칙(Git, 문서, 보안)은 루트 `CLAUDE.md`를 따른다.

## 먼저 읽을 것

1. `docs/tasks/` 에서 지금 작업하는 브랜치의 지시서
2. `docs/design/simulator-member.md` — 시뮬레이터 설계 (모듈 구성, 흐름, 확정 사항). 파일이 있을 때만
3. `docs/design/member.md` — 회원 데이터 설계 (컬럼, PII, 탈퇴, Bronze 모양). 파일이 있을 때만
4. `simulator/README.md` — 코드 구조와 실행 방법

**설계 문서의 "결정"만 구현한다.** "제안"과 "미정"은 작업 지시서가 기본값을 정해 준 경우만 만들고, 아니면 묻는다.

## 시뮬레이터가 하는 일

가상 쇼핑몰의 회원(그리고 이후 행동)을 만들어 **RDS(PostgreSQL)에만 쓴다.** Kafka에는 직접 쓰지 않는다. Debezium이 변경 로그를 읽어 Kafka로 보낸다.

모듈은 셋이다: `member`(가입·탈퇴), `behavior`(쇼핑 행동, 나중에), `controller`(모드 전환·장애 주입·주입 기록).

## 지켜야 할 규칙

| 규칙 | 이유 |
|---|---|
| **PII(이름, 이메일, 전화, 생년월일, 비밀번호 해시)를 로그·콘솔·예외 메시지에 출력하지 않는다.** 식별이 필요하면 `member_id`만 쓴다 | 레이크로 PII가 나가지 않는다는 것이 이 프로젝트의 핵심 약속이다 |
| 난수는 `common`에서 만든 **시드 고정 난수 생성기**만 쓴다. 전역 `random`, 시드 없는 `Faker()`를 직접 쓰지 않는다 | 같은 시드면 같은 결과여야 한다 |
| **회원 생성 함수는 순수 함수**로 둔다. DB, 네트워크, 현재 시각을 안에서 직접 부르지 않고 필요한 값(난수 생성기, 가입 시각, 지역 목록)을 인자로 받는다 | 베이스라인과 신규 가입이 같은 함수를 쓰고, DB 없이 테스트하기 위해서다 |
| 시각은 항상 **시간대 정보가 있는 값**으로 만든다. DB 컬럼은 `timestamptz`다 | Bronze는 UTC, Silver 이후 KST로 한 번만 변환한다는 결정 때문이다 |
| `created_at`은 시뮬레이터가 넣지 않는다. DB 기본값이 기록한다 | `signup_at`(업무 시각)과 구분한다 |
| 행동 성향(구매형·구경형 등)은 DB에 넣지 않는다. 시뮬레이터 내부에만 둔다 | 정답이 노출되면 안 된다 |
| 모듈끼리 서로 import하지 않는다. `member`, `behavior`, `controller`는 `common`만 공유하고, **데이터는 DB로, 제어는 컨트롤러 신호로** 주고받는다 | 모듈을 따로 개발하고 따로 실행하기 위해서다 |
| 평문 PII 파일(시드 파일)은 `simulator/.local/`에만 둔다. 커밋하지 않는다 | 보안 |
| 접속 정보는 환경 변수로 받는다. 코드에 넣지 않는다 | 보안 |

## 폴더 구조

```
simulator/
├── CLAUDE.md
├── README.md              # 코드 구조 + 실행 방법
├── pyproject.toml
├── Dockerfile             # 이미지 하나, 실행 명령만 다르게
├── docker-compose.yml     # 로컬 Postgres (이후 Kafka·Debezium 프로필)
├── .env.example           # 더미 값만
├── data/                  # 지역 목록 CSV 등 (필요한 브랜치에서 추가)
├── src/sim/
│   ├── cli.py             # sim 명령 진입점
│   ├── common/            # 설정, 시드·난수, DB 연결, 로깅, 지역 로더
│   ├── controller/        # 모드 전환, 장애 주입, 주입 기록
│   ├── member/            # 회원 생성 함수, 베이스라인 적재, 신규 가입 실행기
│   └── behavior/          # (나중에)
└── tests/
```

- DDL은 `db/schema/`, Debezium 커넥터 설정은 `connectors/`에 있다. `simulator/` 안에 두지 않는다.
- `lib/`, `build/`, `dist/`, `env/`, `var/`, `parts/`라는 이름의 폴더는 만들지 않는다. 루트 `.gitignore`가 무시한다.

## 개발 환경과 명령

- Python 3.12, 로컬 DB는 Docker Compose의 PostgreSQL이다.
- 의존성: 실행용 `faker`, `psycopg[binary]`(v3), `typer` / 개발용 `pytest`, `ruff`

```bash
cd simulator
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

docker compose up -d        # 로컬 Postgres
ruff check . && ruff format --check .
pytest
sim --help
```

## 코드 작성 규칙

- 타입 힌트를 쓴다. `ruff`(check, format)를 통과해야 한다.
- 생성 로직은 **DB 없이 도는 단위 테스트**를 같이 만든다.
- 설계 문서의 수치(비율, 범위)를 코드에 하드코딩하지 않고 한 곳(설정 또는 데이터 파일)에 모은다.
- 설계에 없는 컬럼, 테이블, 명령을 추가하지 않는다.

## 절대 하지 말 것

- `infra/` 파일을 수정하지 않는다. (`sim/skeleton` 작업 지시서가 허용한 `CLAUDE.md` 이동 한 건만 예외다)
- `main`에 직접 커밋하지 않는다. push와 PR은 사용자 확인 후에 한다.
- 비밀값, 계정 ID, 엔드포인트, 평문 PII 파일을 커밋하지 않는다.
- PII를 로그나 Kafka 메시지에 싣지 않는다.
````