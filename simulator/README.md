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

## 신규 가입 (live)

베이스라인 뒤에 신규 가입을 계속 만들어 `member`에 **한 건씩(건당 트랜잭션 하나)** 넣는다. 로컬 DB 전용이다 (호스트가 `localhost`/`127.0.0.1`이 아니면 실행을 거부한다). **베이스라인(10만 명)을 먼저 적재한 뒤에 켠다.**

```bash
sim member live                                   # 평상시, 실시간, 하루 평균 1,500명
sim member live --speed 1440 --duration 30        # 시뮬레이터 하루 = 실제 1분으로 30초 실행
sim member live --daily 86400 --max-signups 20    # 초당 약 1건, 20건 만들고 종료
```

| 옵션 | 환경 변수 | 기본값 | 설명 |
|---|---|---|---|
| `--mode` | `SIM_LIVE_MODE` | `normal` | 시작 모드 (`normal` \| `surge`) |
| `--daily` | `SIM_LIVE_DAILY` | 1500 | 평상시 하루 평균 가입 수 |
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
- **껐다 켜도 이어진다:** k번째 신규 회원은 `derive_seed(시드, "live", k)`로 난수를 다시 심어 만들어 값이 시드와 k만으로 정해진다. 시작할 때 k는 `member`에서 `signup_at >= 2026-10-01 00:00 KST`인 행 수로 센다(탈퇴는 행을 지우지 않으므로 줄지 않는다). 그래서 껐다 켜도 같은 순서로 이어지고 `member_id`가 겹치지 않는다. 시뮬레이터 시각이 10/1 KST보다 이르면 이 기준이 깨지므로 오류로 멈춘다.
- **전화번호:** 무작위로 뽑아 넣고, `member_phone_key` 위반이면 같은 난수 줄기에서 새 번호로 최대 10번 다시 시도한다(전화번호만 바뀐다). 다른 제약 위반은 재시도하지 않고 오류로 처리한다. 번호를 확인하려고 DB에서 읽어 오지 않는다.
- **종료:** `Ctrl+C`(SIGINT)나 SIGTERM이면 하던 INSERT를 끝내고 요약을 출력한 뒤 종료 코드 0으로 끝난다. DB 연결이 끊기면 1, 2, 4, … 최대 30초 간격으로 다시 연결한다.
- 실제 시간 10초마다 진행 한 줄(모드, 구간 건수와 초당 건수, 누적, 시뮬레이터 시각)을 출력한다. 회원 값(PII)은 출력하지 않는다.
- 이 명령으로 `member`에 신규 가입이 섞이면 `sim member verify`의 가입 기간·일별·시간대별 항목은 베이스라인 기준이라 실패할 수 있다.
- 확인 후 로컬에서 신규 가입만 지우려면: `DELETE FROM member WHERE signup_at >= '2026-10-01 00:00:00+09';`
