# 작업 지시서: sim/modes

> 상태: 진행 전 · 브랜치: `sim/modes` · 이전 작업: `sim/member-live` · 다음 작업: `sim/behavior-core`

## 목표

모드를 **`normal` / `medium` / `burst` 세 개**로 늘리고, 신규 가입 속도가 **하루 시간대 곡선**과 모드를 따르게 한다. 방문(`behavior`)과 가입(`member`)이 같은 곡선·모드 규칙을 쓰도록 **공통 함수**(`common/curve.py`)로 뺀다. 이 브랜치가 끝나면 `sim member live`가 `normal`에서는 요일·시간대 곡선대로, `medium`/`burst`에서는 시간대와 무관한 고정 속도로 가입을 만든다.

`behavior`(방문·주문)는 이 브랜치에서 만들지 않는다. 이 브랜치는 `sim/behavior-core`의 **선행 작업**이다.

이 지시서는 **자기 완결형**이다. 설계 문서(`docs/design/*`)가 레포에 있으면 함께 읽되, **이 지시서와 어긋나면 추측하지 말고 묻는다.**

## 먼저 읽을 것

- 루트 `CLAUDE.md`, `simulator/CLAUDE.md`, `simulator/README.md`
- `docs/tasks/sim-member-live.md` (지금의 신규 가입 실행기 설계)
- 코드: `common/clock.py`, `common/control.py`, `member/schedule.py`, `member/live.py`, `member/cli.py`, `member/params.py`, 그리고 `tests/test_live_*.py`

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- 루트 `CLAUDE.md`의 Git 규칙을 그대로 따른다 (작은 커밋, **push와 PR은 사용자 확인 후**). 커밋 메시지: `sim(modes): <한국어 요약>`
- **로컬 DB에만** 쓴다. RDS에는 접속하지 않는다. (RDS는 이미 배포되어 있지만 이 브랜치의 검증은 로컬 DB로만 한다.)
- 최신 `main`의 새 규칙을 따른다: 브랜치를 만들면 `docs/BRANCHES.md`의 `sim` 구역에 한 줄을 추가하고(같은 PR), 머지 전에 이 지시서 맨 아래 `작업 결과` 절을 채운다. 이 지시서 파일은 `docs/tasks/sim-modes.md`로 둔다.
- 이 브랜치는 기존 `member` 동작을 **바꾼다**(아래 "결정" 참고). 기존 테스트 중 `surge`·4.6배·균등 속도를 전제한 것은 **새 규칙에 맞게 고친다.** 그 외 동작(재시작 인덱스, 전화 재시도, 재연결, 종료)은 바꾸지 않는다.

## 결정된 사항 (사용자가 확정)

| 항목 | 결정 |
|---|---|
| 모드 | `normal`(일상), `medium`(중간), `burst`(폭주). 기존 `surge`는 `burst`로 바꾼다 |
| 가입도 모드를 따른다 | 폭주 때 방문이 느는 것처럼 가입도 늘어난다 |
| 일상 모드의 속도 | **요일 곡선 × 시간대 곡선** (아래 표). 하루 평균은 `--daily`(기본 5,000) |
| medium/burst의 속도 | 시간대와 요일에 **상관없이 고정**. 일상 **피크 시간대 속도**의 3배(medium), 10배(burst). 밤에 눌러도 폭주가 되도록 하루 곡선을 **대체**한다 |
| 자동 복귀(medium 60분, burst 15분) | **이 브랜치에서 만들지 않는다** (`controller` 몫) |

## 곡선 정의

H&M 요일 비율과 시간대 비율(시간 정보가 없어 우리가 정한 `[가정]`)을 **하루 평균 대비 배율**로 바꾼 값이다. 값은 `common/curve.py` 한 곳에만 둔다.

**요일** (`datetime.weekday()` 월=0 ... 일=6, 날짜 경계는 **KST 00:00**):

| 월 | 화 | 수 | 목 | 금 | 토 | 일 |
|---|---|---|---|---|---|---|
| 0.128 | 0.132 | 0.152 | 0.153 | 0.149 | 0.159 | 0.127 |

`weekday_factor = 7 × 비율` (월 0.896 ... 토 1.113). 비율 합이 1이므로 한 주의 평균 배율은 1이다.

**시간대** (KST, 구간 안에서는 일정한 계단 함수. 부드럽게 잇지 않는다):

| 구간 | 비율 | `hour_factor` = 비율 ÷ (구간 시간 ÷ 24) |
|---|---|---|
| 0~6시 | 0.05 | 0.20 |
| 6~9시 | 0.08 | 0.64 |
| 9~12시 | 0.14 | 1.12 |
| 12~14시 | 0.11 | 1.32 |
| 14~18시 | 0.17 | 1.02 |
| 18~22시 | 0.30 | 1.80 |
| 22~24시 | 0.15 | 1.80 |

`PEAK_HOUR_FACTOR`는 `hour_factor`의 최댓값(1.80)이다. 코드에서 표로부터 **계산**한다(1.8을 따로 적지 않는다).

**모드별 속도 배율** (`rate_factor(mode, sim_time)`, 평균 속도 대비):

| 모드 | 배율 |
|---|---|
| `normal` | `weekday_factor(t) × hour_factor(t)` |
| `medium` | `PEAK_HOUR_FACTOR × 3` (= 5.4, 고정) |
| `burst` | `PEAK_HOUR_FACTOR × 10` (= 18, 고정) |

`MODE_PEAK_MULTIPLE = {"medium": 3.0, "burst": 10.0}`도 같은 파일에 둔다.

가입 속도 λ(초당) = `daily ÷ 86,400 × rate_factor(mode, 시뮬레이터 시각)`. 방문 속도도 같은 함수를 `visits_daily`로 쓴다(`sim/behavior-core`에서). 예: 일상 하루 방문 111,000이면 medium은 분당 약 416(≈420), burst는 분당 약 1,387(≈1,400)이다.

## 시작 전 확인 (Claude가 한다)

- 현재 브랜치가 `sim/modes`이고 **최신 `main`**(`sim/member-live`가 머지된 상태)에서 만든 것인지 확인한다. 아니면 최신 `main`에서 새로 만든다.
- `docs/BRANCHES.md`의 `sim` 구역 형식을 읽고, 아래 "작업 순서" 2번에서 한 줄을 추가할 준비를 한다.
- `pytest`(단위)와 `ruff check .`가 **변경 전에 통과**하는지 먼저 본다 (실패하면 알린다).
- `common/clock.py`가 `KST`를 `sim.member.params`에서 가져오는지 확인한다 (아래 1번).

## 만드는 것

### 1. `common/timezone.py` (새) — KST 이동

- `KST = timezone(timedelta(hours=9))` 한 줄과 설명을 둔다. (`zoneinfo`는 slim 이미지에 tzdata가 없을 수 있어 쓰지 않는다 — 기존 주석을 옮긴다.)
- `member/params.py`는 `from sim.common.timezone import KST`로 바꾼다 (이름 `KST`는 `member.params`에서도 계속 쓸 수 있어야 한다).
- `common/clock.py`는 `from sim.common.timezone import KST`로 바꾼다. **`common`이 `member`를 import하지 않게 된다.** (`behavior`가 `member`를 import하지 않고 시계를 쓰기 위한 정리다.)

### 2. `common/curve.py` (새) — 곡선과 모드 배율

순수 함수. 난수, DB, 현재 시각을 안에서 부르지 않는다.

```python
WEEKDAY_RATIO: tuple[float, ...]          # 월~일
HOUR_SHARE: tuple[tuple[int, int, float], ...]   # (시작시, 끝시, 비율)
MODE_PEAK_MULTIPLE: dict[str, float]      # {"medium": 3.0, "burst": 10.0}
PEAK_HOUR_FACTOR: float                   # 표에서 계산

def weekday_factor(sim_time: datetime) -> float: ...
def hour_factor(sim_time: datetime) -> float: ...
def rate_factor(mode: str, sim_time: datetime) -> float: ...
```

- `sim_time`은 시간대 정보가 있어야 한다(없으면 `ValueError`). 내부에서 `KST`로 바꿔 요일·시각을 정한다.
- 모르는 모드는 `ValueError`.
- 모듈을 불러올 때(또는 테스트에서) 검증한다: 요일 비율 합 = 1(±1e-9), 시간대 비율 합 = 1, 구간이 0~24시를 빈틈·겹침 없이 덮는다.

### 3. `common/control.py` — 모드 3개

- `MODES = ("normal", "medium", "burst")`
- 주석과 오류 메시지(`mode는 ... 여야 합니다`)가 새 값을 보여 준다.
- `ControlState`, `ControlSource`, `FileControlSource`의 동작은 그대로다.

### 4. `member/schedule.py`, `member/live.py`, `member/cli.py`, `member/params.py` — 가입 속도 교체

- `schedule.py`: `rate_multiplier`, `mode_multiplier`를 지우고 `common.curve.rate_factor`를 쓴다.
  - `signups_per_second(daily, mode, sim_time) = daily × rate_factor(mode, sim_time) ÷ SECONDS_PER_DAY`
  - `next_interval(rng, daily, mode, sim_time)` — `surge_multiplier` 인자를 없앤다.
- `live.py`: `LiveRunner`의 `surge_multiplier` 인자와 속성을 없앤다. `_draw_wait`는 새 `next_interval`을 부른다.
- `cli.py`: `--surge-multiplier` 옵션(환경변수 `SIM_LIVE_SURGE_MULTIPLIER`)을 **없앤다.** `--mode`의 도움말은 `MODES`에서 가져오므로 자동으로 바뀐다. 시작 출력의 "폭주 배율" 항목을 지운다.
- `params.py`: `SURGE_MULTIPLIER`를 지운다.
- 속도는 시간대 경계에서 계단으로 바뀐다. 간격은 **간격을 뽑은 시점의 속도**로 뽑는다(경계에서 생기는 오차는 허용한다). 모드가 바뀌면 간격을 다시 뽑는 기존 동작은 그대로다.
- 시작·진행 출력에서 모드 이름이 `burst`, `medium`으로 나온다.

### 5. 테스트 고치기·추가 (DB 없이, 가짜 시계)

**새 테스트 `tests/test_curve.py`:**
- 요일·시간대 합 = 1, 구간 덮음, `PEAK_HOUR_FACTOR == 1.8`
- 한 주(7일)에 걸쳐 `rate_factor("normal", t)`를 초 단위로 평균하면 **1.0 ± 1e-6** (요일×시간대의 평균이 1)
- `rate_factor("medium")`은 요일·시각에 상관없이 5.4, `burst`는 18
- 날짜 경계: KST 23:59:59와 00:00:00에서 요일이 바뀐다. UTC 15:00이 KST 다음 날 00:00으로 계산된다.
- naive datetime, 모르는 모드는 `ValueError`

**기존 테스트 수정** (`tests/test_live_schedule.py`, `test_live_runner.py`, `test_live_cli.py`, `test_live_common.py` 등):
- `surge` → `burst`, `SURGE_MULTIPLIER`/4.6배 전제 삭제
- "10일 → 50,000 ± 5σ"는 시작 요일에 따라 달라지므로 **7의 배수 일수**(14일 → 70,000 ± 5σ)로 바꾸고 시작 시각은 가짜 시계의 고정 월요일 00:00 KST(2026-10-12)로 한다
- burst: 시뮬레이터 1시간 → `daily × 18 ÷ 24` ± 5σ (daily 5,000이면 3,750건)
- medium: 같은 방식으로 5.4배
- 모드 전환 `normal → burst → normal`에서 구간별 건수가 각 속도를 따른다
- 시간대 비율: 일상 모드로 7일을 돌려 시간대 구간별 건수 비율이 표의 비율 ± 5σ 안
- 제어 파일에 `"surge"`를 넣으면 **잘못된 값**으로 처리되어 마지막 상태를 유지한다(경고 한 번)
- **그대로 통과해야 하는 테스트:** 재시작 인덱스, 전화 재시도, 재연결, 종료 신호, 제어 파일 파싱(모드 이름 제외), 출력에 PII 없음

### 6. 문서

- `simulator/README.md`의 `신규 가입 (live)` 절: 모드 3개와 속도 규칙 표, `--surge-multiplier` 삭제, 곡선 설명 한 단락, 제어 파일 예시를 `"mode": "burst"`로
- `simulator/CLAUDE.md` 폴더 구조의 `common/` 설명에 "곡선" 추가 (이 한 줄만)
- `docs/tasks/sim-member-live.md`는 **수정하지 않는다** (완료된 작업의 기록이다)

## 만들지 않는 것

- `behavior` 코드, 방문·주문 (→ `sim/behavior-core`)
- medium 60분·burst 15분 **자동 복귀**, 모드 전환 이력, `incident_log`, 제어 신호 전달 수단(HTTP 등) (→ `controller`)
- 곡선을 부드럽게 잇는 보간, 날짜별 이벤트(세일 등)
- 탈퇴
- `db/schema/` 변경, `infra/` 변경
- 설계 문서 수정

## 작업 순서

1. 시작 전 확인을 하고, **계획을 먼저 제시해 사용자 확인을 받는다**
2. `docs/BRANCHES.md`에 `sim/modes` 한 줄 추가(상태: 진행 중) + 이 지시서를 `docs/tasks/sim-modes.md`로 추가 → 커밋 `sim(modes): 브랜치 등록과 작업 지시서 추가`
   `common/timezone.py`, KST 이동 + 기존 테스트 통과 확인 → 커밋 `sim(modes): KST를 common으로 옮김`
3. `common/curve.py` + `tests/test_curve.py` → 커밋 `sim(modes): 요일·시간대 곡선과 모드 배율 추가`
4. `common/control.py` 모드 3개 → 커밋 `sim(modes): 모드를 normal, medium, burst로 확장`
5. `member` 속도 교체 + 기존 테스트 수정 → 커밋 `sim(modes): 가입 속도가 곡선과 모드를 따르게 함`
6. 문서 갱신 → 커밋 `sim(modes): README와 CLAUDE.md 갱신`
7. "완료 확인"을 **실제로 실행**해서 결과 보고
8. 이 지시서 맨 아래 `작업 결과` 절을 채우고, 맨 위 상태를 `완료`로 바꾸고, `docs/BRANCHES.md`의 상태를 "머지됨"으로 바꾼다 → 커밋 `sim(modes): 작업 결과 기록`. 그다음 사용자 확인을 기다린다.

## 완료 확인

아래를 **실제로 실행**해서 결과를 보고한다.

- [ ] `ruff check .`, `ruff format --check .`, `pytest`(단위) 통과, `docker compose up -d` 후 `pytest -m integration` 통과
- [ ] baseline 재현성 테스트가 **그대로 통과**
- [ ] `grep -rn "surge" simulator/src simulator/tests simulator/README.md`에 남은 것이 없다 (의도적으로 남긴 곳이 있으면 이유를 적는다)
- [ ] `sim/behavior-core`가 쓸 `common.curve.rate_factor`를 `python -c`로 불러 `normal`(월요일 20시), `medium`, `burst` 값을 출력한다 (각각 0.896×1.8, 5.4, 18)
- [ ] **실제 실행 (로컬 DB, 베이스라인 10만 있는 상태):**
  - `sim member live --mode burst --speed 60 --duration 30` → 약 1,875건 (± 5σ). 신규 가입이 쌓인다
  - `echo '{"running": true, "mode": "medium"}' > simulator/.local/control.json` 후 같은 조건 → 약 563건 (burst의 3/10)
  - 실행 중 `normal`로 바꾸면 속도가 시간대 곡선 값으로 내려가고 `mode: medium → normal` 줄이 나온다
  - `{"mode": "surge"}`를 쓰면 경고 한 번과 함께 마지막 상태를 유지한다
- [ ] 확인 후 신규 가입 행 **삭제:** `DELETE FROM members WHERE signup_at >= '2026-10-01 00:00:00+09';` 실행 후 `SELECT count(*) FROM members;`가 **100000**으로 돌아왔다. 삭제한 건수를 보고한다
- [ ] 출력에 `grep -E "example\.com|010-"` 결과가 없다
- [ ] `git status`에 `.env`, `simulator/.local/`이 없다. push, PR을 하지 않았다 (사용자 확인 대기)

## README 갱신

- `simulator/README.md`, `simulator/CLAUDE.md` (위 "문서")

## 작업 결과

(머지 전에 Claude Code가 채운다: 무엇을 만들었나, 왜, 확인한 결과(완료 확인 실행 결과), 다음 할 일. 다음 작업은 `sim/behavior-core`.)