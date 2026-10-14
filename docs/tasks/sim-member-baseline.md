# 작업 지시서: sim/member-baseline

> 상태: 진행 전 · 브랜치: `sim/member-baseline` · 이전 작업: `sim/skeleton` · 다음 작업: `sim/cdc-local`, `sim/member-live`

## 목표

가상 회원 **10만 명**을 만들어 **로컬 PostgreSQL의 `member` 테이블에 한 번에 적재**하는 `sim member baseline` 명령을 만든다. 적재 후 결과를 확인하는 `sim member verify` 명령도 만든다.

이 브랜치가 끝나면 `docker compose up -d` → `sim member baseline` → `sim member verify`로 **10만 행이 설계 분포대로 들어간 로컬 DB**가 생긴다. Kafka·Debezium은 다음 브랜치(`sim/cdc-local`)에서 이 DB를 읽는다.

이 지시서는 **자기 완결형**이다. 필요한 설계 수치와 기본값이 모두 본문에 있다. `docs/design/member.md`, `docs/design/simulator-member.md`가 레포에 있으면 함께 읽되, **이 지시서와 어긋나면 추측하지 말고 묻는다.**

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- 단계마다 **커밋한다** (루트 `CLAUDE.md`의 규칙). 커밋 메시지는 `sim(member-baseline): <한국어 요약>`. **push와 PR은 하지 않는다.** 사용자가 직접 한다.
- 커밋할 때 `git add`에는 **경로를 명시**한다 (`git add -A`, `git add .` 금지). 줄바꿈(CRLF/LF)만 바뀐 기존 파일은 건드리지 않는다.
- Python 3.12 가상환경(`simulator/.venv`, WSL)을 쓴다. Docker는 사용자 컴퓨터의 WSL Docker다. 이 컴퓨터에는 `psql`이 없으므로 DB 확인은 `docker compose exec postgres psql -U sim -d clothes`로 한다.
- 이번에는 **로컬 DB에만** 쓴다. RDS에는 접속하지 않는다.
- 완료 확인이 끝난 뒤 로컬 DB(볼륨)를 **지울지 남길지 사용자에게 묻는다.** 임의로 `down -v` 하지 않는다. (다음 브랜치가 이 10만 명을 쓴다.)

## 시작 전 확인 (Claude가 한다)

- 현재 브랜치가 `sim/member-baseline`이고, `git log --oneline -5`에 `sim/skeleton` 머지가 보이는지, `simulator/`와 `db/schema/001_member.sql`이 있는지 확인한다. 아니면 만들지 말고 알린다.
- **`simulator/data/region_weights_202609.csv`가 있는지** 확인한다. 이 파일은 사용자가 제공한다. 없으면 만들지 말고 알린다. (256행 + 헤더, 컬럼 `region_sigungu,sido,population,weight`)
- 이 지시서가 저장소 루트에 있으면 `docs/tasks/sim-member-baseline.md`로 옮긴다.
- `docker compose ps`로 로컬 Postgres 상태를 확인한다. 이미 `member`에 행이 있으면 알린다.

## 이번 작업에서 확정된 값

아래는 설계 문서의 **결정**과, 이 지시서가 정해 주는 **기본값**이다. 값은 코드 곳곳에 흩뿌리지 않고 `src/sim/member/params.py` **한 곳**에 모은다.

| 항목 | 값 | 출처 |
|---|---|---|
| 인원 | 100,000 (옵션으로 변경 가능) | 설계 결정 |
| 가입 시각 | **KST 2026-08-01 00:00:00 이상 ~ 2026-10-01 00:00:00 미만** (61일). 날짜·하루 안의 시각 모두 **균등** (구간 전체에서 초 단위로 균등 추출) | 설계 결정 |
| 시간대 | 고정 오프셋 `+09:00` (`timezone(timedelta(hours=9))`). `zoneinfo`를 쓰지 않는다 (slim 이미지에 tzdata가 없을 수 있다) | 지시서 기본값 |
| 나이대 가중치 (H&M 회원 수) | `~19`: 71,583 · `20s`: 528,358 · `30s`: 234,068 · `40s`: 204,118 · `50s`: 226,242 · `60s`: 72,623 · `70+`: 19,127 (합계로 나눠 확률로 쓴다) | 설계 결정 |
| 나이대 → 나이 범위 | `~19`: 16~19 · `20s`: 20~29 · `30s`: 30~39 · `40s`: 40~49 · `50s`: 50~59 · `60s`: 60~69 · `70+`: 70~99. 범위 안에서 **균등** | 설계 결정 |
| 생년월일 | 출생 연도 = **가입 시각(KST)의 연도 − 나이**, 월·일은 그 연도에 실제로 있는 날짜 중 무작위 | 설계 결정 |
| `age_band` | 위 출생 연도로 다시 계산한 값 (`가입 연도 − 출생 연도`를 나이대로 변환). 뽑은 나이대와 항상 같아야 한다 | 설계 결정 |
| `gender` | `F` 55% : `M` 45%, 회원마다 독립 추출 (H&M 근거 없는 **우리의 가정**) | 설계 결정 (비율은 제안) |
| `name` | Faker `ko_KR`. 성별에 맞게 `name_female()` / `name_male()` | 설계 결정 |
| `member_id` | 시드 고정 Faker의 `uuid4` | 설계 결정 |
| `email` | `user_<member_id의 하이픈 뺀 32자리 소문자 hex>@example.com` (member_id가 유일하므로 항상 유일) | 지시서 기본값 |
| `phone` | `010-XXXX-XXXX` (8자리를 0~99,999,999에서 **중복 없이** 추출해 형식에 맞춤) | 설계 결정 |
| `signup_channel` | `web` / `app` 50:50 무작위 | 설계 결정 (가정) |
| `marketing_consent` | `true` 70% | 설계 결정 (가정) |
| `password_hash` | bcrypt 모양의 무작위 가짜 값: `$2b$12$` + `./A-Za-z0-9`에서 뽑은 53자 (총 60자). 회원마다 다르고 **실제 해싱은 하지 않는다** | 설계 결정 (가정) |
| `status` / `withdrawn_at` | 모두 `ACTIVE` / `NULL` | 설계 결정 |
| `created_at` | **시뮬레이터가 넣지 않는다.** INSERT 컬럼 목록에서 뺀다 (DB 기본값) | 설계 결정 |
| `region_sigungu` | `region_weights_202609.csv`의 `weight`로 **가중 추출** (256개) | 설계 결정 |
| 기본 시드 | 42 (환경 변수 `SIM_SEED`로 변경) | 지시서 기본값 |
| 적재 단위 | 한 번에 **5,000행씩 COPY**, 배치마다 커밋 (옵션 1,000~5,000) | 설계 결정 (COPY는 지시서 기본값) |

## 만드는 것

### 1. 설정과 공통 도구 (`src/sim/common/`)

| 파일 | 내용 |
|---|---|
| `config.py` | 환경 변수 읽기: `DATABASE_URL`(필수), `SIM_SEED`(기본 42), `SIM_REGION_FILE`(기본 `data/region_weights_202609.csv`, `simulator/` 기준 상대 경로). `simulator/.env`가 있으면 읽는다 (환경 변수가 우선) |
| `rng.py` | 시드 고정 난수 도구. `random.Random(seed)`와 `Faker("ko_KR")`(시드 고정)를 하나로 묶은 클래스. **회원 모듈은 이것만 쓴다** (전역 `random`, 시드 없는 `Faker()` 금지) |
| `regions.py` | 지역 CSV 로더. 아래 "지역 로더" 참고 |
| `db.py` | PostgreSQL 연결(psycopg3), **오류 메시지 가리기**(아래 "PII 안전" 참고) |

**의존성 추가:** `python-dotenv`를 실행용 의존성에 추가한다. 이 지시서가 허용한 **유일한** 추가다. `pyproject.toml`과 `simulator/CLAUDE.md`의 의존성 줄을 함께 고친다.

**`.env.example`에 추가** (더미 값):

```
SIM_SEED=42
SIM_REGION_FILE=data/region_weights_202609.csv
```

**지역 로더 (`regions.py`)**

- CSV는 UTF-8이고 줄바꿈이 CRLF일 수 있다. `csv` 모듈로 `newline=""`, `encoding="utf-8-sig"`로 읽는다.
- 시작할 때 **검증**한다. 하나라도 어긋나면 어떤 검증이 실패했는지 알리고 멈춘다.
  - 컬럼이 정확히 `region_sigungu, sido, population, weight`
  - 행 수 256 (`params.py`의 상수)
  - `region_sigungu` 중복 없음
  - `weight`가 모두 양수이고 합이 1에 가깝다 (오차 1e-6 이내)
- 읽은 결과는 지역 이름 목록과 `weight` 목록을 가진 **불변 객체**로 돌려준다. 가중 추출은 이 객체와 난수 도구를 쓴다.

### 2. 회원 모듈 (`src/sim/member/`)

| 파일 | 내용 |
|---|---|
| `params.py` | 위 "확정된 값" 표의 수치 (나이대 가중치, 나이 범위, 비율, 기간, 지역 개수, 배치 크기 한계) |
| `model.py` | 회원 한 명을 담는 **불변 dataclass** `NewMember` (아래 컬럼 14개, `created_at` 제외). **`__repr__`는 `member_id`만 보여 준다** (PII가 출력에 섞이지 않게) |
| `generate.py` | 회원 생성 **순수 함수**와 전화번호 배정 함수 |
| `baseline.py` | 배치 적재 (생성 → COPY → 커밋) |
| `verify.py` | 적재 결과 확인 (아래 "verify") |
| `cli.py` | `typer` 하위 앱 `member`. `sim/cli.py`에서 `app.add_typer(member_app, name="member")`로 연결 |

`NewMember` 컬럼: `member_id`, `name`, `email`, `phone`, `birth_date`, `password_hash`, `gender`, `signup_at`, `signup_channel`, `marketing_consent`, `status`, `withdrawn_at`, `region_sigungu`, `age_band`.

**회원 생성 함수 (순수 함수):**

```python
def generate_member(rng: SimRandom, signup_at: datetime, regions: RegionTable, phone: str) -> NewMember: ...
def allocate_phones(rng: SimRandom, count: int) -> list[str]: ...   # 중복 없는 010 번호 count개
```

- 함수 안에서 DB, 네트워크, 현재 시각을 부르지 않는다. 필요한 값은 인자로 받는다. (신규 가입 브랜치 `sim/member-live`가 **같은 함수**를 쓴다. 두 경로의 값 모양이 달라질 수 없다.)
- `signup_at`은 **시간대 정보가 있는 값**이어야 한다. 없으면 오류.
- 전화번호는 회원끼리 겹치면 안 되므로 **함수 밖(호출하는 쪽)** 에서 배정해 넘긴다. 베이스라인은 시작할 때 `allocate_phones`로 인원 수만큼 한 번에 뽑는다 (`random.sample(range(10**8), count)` 방식으로 메모리를 아낀다). 이후 신규 가입의 번호 배정은 `sim/member-live`에서 정한다.
- **난수 사용 순서가 배치 크기와 무관해야 한다.** 회원을 앞에서부터 하나씩 순서대로 만들고, 배치 단위로 난수 소비 방식이 달라지면 안 된다. (같은 시드 + 같은 인원이면 배치 크기를 바꿔도 **같은 결과**)

**베이스라인 적재 (`baseline.py`):**

- 회원을 **제너레이터로 하나씩** 만들어 배치 크기만큼 모았다가 적재한다 (나중에 137만 명으로 키워도 메모리가 늘지 않게). 전체 목록을 메모리에 만들지 않는다.
- 배치마다 `COPY member (<컬럼 목록>) FROM STDIN`으로 넣고 **커밋한다.** 컬럼 목록에 `created_at`은 없다.
- 시작 전에 `member` 테이블이 **비어 있는지** 확인한다. 행이 있으면 **아무것도 넣지 않고** 이유를 알리고 멈춘다. (`TRUNCATE`·삭제 옵션은 만들지 않는다. 이 명령은 나중에 RDS에도 쓰므로 지우는 기능을 넣지 않는다.)
- 한 배치가 실패하면 그 배치는 롤백된다. 이미 커밋된 앞 배치는 남는다. 이 경우 다시 실행하면 "테이블이 비어 있지 않음"으로 멈추는 것이 **정상**이다 (메시지에 "로컬이면 `docker compose down -v` 후 다시"를 안내한다).
- 진행 상황은 **1만 건마다** `20,000 / 100,000` 형태로만 출력한다. 회원 값은 출력하지 않는다.

### 3. CLI

```
sim member baseline [--count 100000] [--seed N] [--batch-size 5000] [--dry-run] [--yes]
sim member verify   [--expected 100000]
```

**`baseline`**

1. 설정과 지역 파일을 읽고 검증한다.
2. 대상 DB를 **`호스트:포트/DB이름` 형태로만** 출력한다 (사용자·비밀번호는 출력하지 않는다). `--yes`가 없으면 `계속할까요? [y/N]`을 묻는다.
3. `--dry-run`이면 DB에 접속하지 않고 **생성만** 한다 (확인 질문도 없다). 아래 요약만 출력한다.
4. 아니면 비어 있는지 확인하고 적재한다.
5. 끝나면 **요약**을 출력하고 `simulator/.local/baseline_run.json`에 같은 내용을 쓴다 (`.local/`은 `.gitignore`에 있다).

요약 내용 (**PII 없는 집계값만**): 인원, 시드, 배치 크기, 지역 파일 이름과 행 수, 가입 기간, 소요 시간, 나이대별·성별·채널별 인원, **재현성 해시**.

**재현성 해시:** 생성한 모든 행(생성 순서대로, `created_at` 제외)을 일정한 형식의 문자열로 만들어 이어 붙인 SHA-256의 **앞 12자리**. 같은 시드·인원·지역 파일이면 항상 같아야 하고 배치 크기와도 무관해야 한다. 지역 파일을 바꾸면 해시가 달라진다는 점이 곧 "어느 파일로 만들었는지 기록해야 하는 이유"다 (설계 6절).

**`verify` (읽기 전용, 설계 문서 7절의 "베이스라인 적재 후" 확인)**

DB에 SQL로 집계해서 항목별 **통과/실패**를 표로 보여 주고, 하나라도 실패하면 종료 코드 1을 돌려준다. **PII는 읽지도 출력하지도 않는다** (집계만).

| # | 확인 | 기준 |
|---|---|---|
| 1 | 행 수 | `--expected`와 같다 |
| 2 | 이메일·전화 중복 | 둘 다 0건 |
| 3 | 필수 PII 채워짐 | `name`, `email`, `phone`, `birth_date`, `password_hash`에 NULL 0건 |
| 4 | 상태 | 전부 `ACTIVE`, `withdrawn_at` 전부 NULL |
| 5 | `signup_at` 범위 | 전부 [KST 8/1 00:00, 10/1 00:00) 안 |
| 6 | 일별 가입 수 | 61일 모두 평균 ± 5σ 안 (σ = √(N·p·(1−p)), p = 1/61) |
| 7 | 시간대별(KST 0~23시) 비율 | 각 시간 비율이 1/24 ± 5σ 안 |
| 8 | 나이대 비율 | 7개 나이대 모두 H&M 가중치 ± 5σ 안 |
| 9 | `age_band` 정합성 | `age_band` = (가입 시각 KST 연도 − `birth_date` 연도)를 나이대로 변환한 값. 불일치 0건. 최소 나이 ≥ 16 |
| 10 | 지역 | 모든 `region_sigungu`가 지역 파일의 256개 안에 있다 (파일에 없는 값 0건) |
| 11 | 시도별 비율 | 시도(= `region_sigungu`의 첫 공백 앞)별 비율이 지역 파일의 시도별 `weight` 합 ± 5σ 안 |
| 12 | 성별·채널·마케팅 동의 비율 | 여성 55%, `app` 50%, 동의 70% 각각 ± 5σ 안 |

`σ`는 비율 p와 인원 N으로 √(p(1−p)/N)을 쓴다. 허용 범위를 고정 숫자가 아니라 이렇게 두는 이유는 **인원이 달라져도**(2,000명 테스트와 10만 명) 같은 기준을 쓰기 위해서다.

## PII 안전 (중요)

| 규칙 | 구현 |
|---|---|
| 이름·이메일·전화·생년월일·해시를 **출력하지 않는다** | 로그, 콘솔, 진행 표시, 예외 메시지, 테스트 출력 모두 |
| `NewMember`를 `print`/로그/assert 메시지에 넣어도 새지 않는다 | `__repr__`이 `member_id`만 보여 준다. 테스트로 확인 |
| **PostgreSQL 오류 메시지에 행 내용이 들어 있다** (예: `Failing row contains (...)`, `Key (email)=(...) already exists`) | `psycopg.Error`는 **잡아서** 예외 종류, `sqlstate`, `diag.constraint_name`만 출력한다. 메시지 본문(`str(e)`)과 `diag.message_detail`은 출력하지 않는다. 이 처리는 `common/db.py`에 한 곳으로 둔다 |
| 시드 파일, 덤프 파일을 만들지 않는다 | 회원 값을 파일로 쓰지 않는다 (`baseline_run.json`에는 집계값만) |

## 테스트

**단위 테스트 (DB 없이 돈다, 기본 `pytest`에 포함):**

- `generate_member`: 한 명이 DDL 제약을 모두 만족한다 (성별·채널·상태 값, 나이 ≥ 16, `age_band` 정합, 전화 형식 `^010-\d{4}-\d{4}$`, 이메일 형식, `password_hash` 형식 `^\$2b\$12\$[./A-Za-z0-9]{53}$`, `signup_at`이 시간대 정보 포함, 지역이 지역 파일 안에 있음)
- `signup_at`에 시간대가 없는 값을 넣으면 오류
- 같은 시드로 두 번 만들면 완전히 같고, 시드가 다르면 다르다
- **배치 크기 1,000과 5,000에서 재현성 해시가 같다**
- 2만 명에서 `member_id`, `email`, `phone` 모두 유일
- 5만 명에서 나이대·성별 비율이 기대값 ± 5σ 안 (시드 고정이라 흔들리지 않는다)
- 생성한 `signup_at`이 모두 기간 안에 있다
- `repr(NewMember)`에 이름·이메일·전화·생년월일·해시가 없다
- 지역 로더: 정상 파일 통과, 행 수 틀림 / 중복 / 가중치 합 틀림 / 컬럼 틀림은 각각 오류. **CRLF 줄바꿈 파일도 읽힌다**
- `db.py`의 오류 가리기: 가짜 `psycopg.Error`에 PII 문자열이 들어 있어도 출력에 나오지 않는다

**통합 테스트 (`@pytest.mark.integration`, 로컬 DB 필요):**

- 기본 `pytest`에서는 제외한다 (`pyproject.toml`에 마커 등록, 기본 옵션 `-m "not integration"`). `pytest -m integration`으로 실행한다.
- `DATABASE_URL`의 호스트가 `localhost`/`127.0.0.1`이 아니면 **건너뛴다.**
- 실제 `member` 테이블을 건드리지 않는다. **임시 스키마**를 만들고 `db/schema/*.sql`을 그 안에 적용한 뒤, 2,000명을 적재하고 `verify`의 항목(행 수 기준은 2,000)이 통과하는지 확인하고, 스키마를 지운다.
- 비어 있지 않은 테이블에는 적재를 거부하는지도 임시 스키마에서 확인한다.

## 만들지 않는 것

- 신규 가입 실행기, 가입 속도·모드·시간 흐름 (→ `sim/member-live`)
- 탈퇴, `member_archive` 적재, 주문 관련 (→ 이후)
- 컨트롤러 동작, 장애 주입 (→ 이후)
- Kafka, Debezium, 복제 슬롯, publication (→ `sim/cdc-local`)
- RDS 접속, Secrets Manager, ECS 실행 (→ 인프라가 준비된 뒤)
- 테이블 삭제·초기화 옵션
- 인덱스 추가, `db/schema/` 변경 (필요해 보이면 만들지 말고 먼저 이유를 설명한다)
- 설계 문서(`docs/design/*`) 수정

## 작업 순서

각 단계가 **커밋 하나**다.

1. 시작 전 확인을 하고, **계획을 먼저 제시해 사용자 확인을 받는다**
2. `common/` 설정·난수·DB·지역 로더 + `python-dotenv` 추가 + `.env.example` + 관련 단위 테스트 — `sim(member-baseline): 설정, 시드 난수, 지역 로더 추가`
3. `member/` `params.py`, `model.py`, `generate.py` + 단위 테스트 — `sim(member-baseline): 회원 생성 순수 함수 추가`
4. `member/baseline.py`, `cli.py`, `--dry-run`, 재현성 해시, `baseline_run.json` + 테스트 — `sim(member-baseline): 베이스라인 적재 명령 추가`
5. `member/verify.py`, `verify` 명령 + 통합 테스트 — `sim(member-baseline): 적재 결과 확인 명령 추가`
6. `Dockerfile`이 `data/`를 이미지에 포함하는지 확인하고, 없으면 한 줄 추가. `simulator/README.md` 갱신 — `sim(member-baseline): 이미지에 지역 파일 포함, README 갱신`
7. "완료 확인"을 **실제로 실행**해서 결과 보고

## 완료 확인

아래를 **실제로 실행**해서 결과를 보고한다.

- [ ] `pip install -e ".[dev]"` 성공
- [ ] `ruff check .`, `ruff format --check .` 통과
- [ ] `pytest` (단위) 통과
- [ ] `docker compose up -d` 후 `pytest -m integration` 통과
- [ ] `sim member baseline --dry-run`을 **두 번** 실행해 재현성 해시가 같다. `--batch-size 1000`으로 한 번 더 해도 같다
- [ ] `sim member baseline --yes`로 10만 명 적재. 소요 시간 보고
- [ ] `docker compose exec postgres psql -U sim -d clothes`로 확인: `SELECT count(*), count(DISTINCT email), count(DISTINCT phone) FROM member;` → 세 값 모두 100000
- [ ] `sim member verify` → **12개 항목 전부 통과**
- [ ] `sim member baseline --yes`를 한 번 더 실행하면 **아무것도 넣지 않고 멈춘다.** (`SELECT count(*) FROM member;`이 그대로 100000)
- [ ] **PII가 출력에 없다:** 적재 실행 출력을 파일로 저장해 `grep -E "example\.com|010-"`로 찾았을 때 **결과가 없다.** 일부러 실패를 만드는 경우(예: 이미 있는 이메일로 한 건 INSERT 시도)에도 오류 출력에 이메일 값이 없다
- [ ] `simulator/.local/baseline_run.json`이 생겼고 **집계값만** 들어 있다
- [ ] `docker build -t sim-local ./simulator` 성공, 이미지에 지역 파일이 있다 (`docker run --rm --entrypoint ls sim-local data`)
- [ ] `git status`에 `.env`, `simulator/.local/`, 회원 값이 든 파일이 없다
- [ ] 줄바꿈만 바뀐 기존 파일을 내가 건드리지 않았다
- [ ] 끝나면 **로컬 DB를 지울지 남길지 사용자에게 묻는다**

## README 갱신

- `simulator/README.md`: `## 회원 베이스라인` 절 추가 (`baseline`, `verify` 사용법, 옵션, 결과 확인 방법, 재현성 해시 보는 법, 지역 파일 이름에 기준월이 들어 있고 파일을 바꾸면 결과가 달라진다는 점)
- `simulator/CLAUDE.md`: 의존성 줄에 `python-dotenv` 추가 (이 한 줄만)

## 막히면

- 이 지시서의 내용끼리, 또는 설계 문서와 어긋나 보이면 **추측하지 말고 묻는다.**
- 이 지시서에 없는 파일·명령·컬럼이 필요해 보이면 만들지 말고 먼저 이유를 설명한다.
- Faker나 psycopg의 동작이 이 지시서의 가정과 다르면(예: `name_female`이 없음) 대안을 정해 구현하지 말고 먼저 알린다.