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
│   ├── common/            # 설정, 시드·난수, DB 연결, 로깅, 지역 로더
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

가상 회원 10만 명을 만들어 로컬 `member` 테이블에 한 번에 적재하고, 결과를 확인한다. 이 명령은 로컬 DB용이다 (RDS 접속은 이후 작업).

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

- `member` 테이블에 행이 하나라도 있으면 아무것도 넣지 않고 멈춘다. 로컬에서 다시 하려면 `docker compose down -v` 후 `up -d`.
- 적재가 끝나면 PII 없는 집계값 요약을 출력하고 `.local/baseline_run.json`에 쓴다.
- 직접 확인: `docker compose exec postgres psql -U sim -d clothes -c "SELECT count(*), count(DISTINCT email), count(DISTINCT phone) FROM member;"`
- **재현성 해시**는 생성한 모든 행의 SHA-256 앞 12자리다. 시드·인원·지역 파일이 같으면 배치 크기와 상관없이 같다. 다르면 다른 조건으로 만든 데이터다.
- **지역 파일** `data/region_weights_202609.csv`의 이름에 기준월(2026-09)이 들어 있다. 파일을 바꾸면 같은 시드라도 결과(해시)가 달라지므로, 어느 파일로 만들었는지 요약에 남긴다. 다른 파일은 `SIM_REGION_FILE`로 지정한다.
- 환경 변수: `DATABASE_URL`(필수), `SIM_SEED`, `SIM_REGION_FILE`. 상대 경로와 `.env`는 현재 작업 폴더(`simulator/`) 기준이다.
- PII(이름·이메일·전화·생년월일·해시)는 출력하지 않는다. DB 오류도 예외 종류, sqlstate, 제약 이름만 보여 준다.

통합 테스트는 로컬 DB가 필요하며 기본 `pytest`에서는 제외된다 (임시 스키마를 만들었다 지운다).

```bash
pytest -m integration
```
