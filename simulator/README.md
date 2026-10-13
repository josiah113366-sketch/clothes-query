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
