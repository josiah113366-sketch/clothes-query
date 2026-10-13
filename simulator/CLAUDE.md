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
- 의존성: 실행용 `faker`, `psycopg[binary]`(v3), `python-dotenv`, `typer` / 개발용 `pytest`, `ruff`

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
