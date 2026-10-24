# agent/eval

**채점 스크립트**다. 장애를 심은 기록(정답표)과 탐지·조사 결과를 비교해 점수를 낸다. 정답표는 시뮬레이터 컨트롤러가 쓰는 **실제 형식**(사건 하나 = start·end 파일 둘)을 읽는다.

## 쉬운 설명: 시험 채점

- **정답표(`incident_log`)**는 출제자가 쓴 답안지다: "15시 정각에 PG_A에 장애를 심었다."
- **이상 이력(`anomaly`)**은 순찰 학생이 낸 1차 답이다: "15시 10분에 PG_A가 이상하다고 기록했다."
- **원인 리포트**는 조사 학생이 쓴 서술형 답이다: "원인은 결제 층이고, 근거는 이렇다."

채점관(이 스크립트)이 답안지와 학생 답을 비교해서 네 가지를 매긴다.

| 항목 | 묻는 것 | 점수 |
|---|---|---|
| 탐지 적발 | 사건 시작 뒤 **허용 시간 안에** 같은 종류의 이상을 기록했나 | 맞게 잡음 / 늦게 잡음 / 못 잡음 |
| 오탐 | 사건과 상관없는 이상을 기록했나 | 건수, 이어진 것을 합친 덩어리 수 |
| 층 판별 | 리포트가 말한 원인 층이 정답 층과 같은가 | 맞음 / 틀림 / 리포트 없음 |
| 근거 연결 | 리포트의 주장마다 근거가 붙었나 | 근거 있는 주장 비율 |

## 사건별 정답 (`score.py`의 `SCENARIOS`)

| 정답표의 사건 | 정답 이상 종류 | 정답 층 | 허용 지연 | 비고 |
|---|---|---|---|---|
| `PG_OUTAGE` | `PG_FAILURE_SPIKE` | `PAYMENT` | 15분 | 장애를 건 PG(`params.pg`)의 이상만 맞는 것으로 봄 |
| `SINK_PAUSE` | `BRONZE_LAG_SPIKE` | `INGEST` | 30분 | 파일 전환 15분이라 최악 약 26분(지연 1200초 도달 20분 + 수집 1분 + 판정 5분) |
| `DATA_POLLUTION` / `DUPLICATE_SUCCESS_PAYMENT` | `DUPLICATE_SUCCESS_PAYMENT` | `DATA_QUALITY` | 10분 | 측정하지 않은 값 |
| `DATA_POLLUTION` / `ORDER_TOTAL_MISMATCH` | `ORDER_TOTAL_MISMATCH` | `DATA_QUALITY` | 30분(임시) | **기본으로 채점하지 않음.** Silver 정기 실행이 정해지면 `--include ORDER_TOTAL_MISMATCH` |
| `INGEST_LAG`(burst), `TRAFFIC_SURGE`, `OPERATOR_PAUSE` | - | - | - | 채점하지 않음. burst는 S3 Sink가 모두 소화해 소비 지연이 생기지 않는다 |

채점하지 않는 사건(제외 목록, 기본 끔, 미채점 종류)의 시작부터 끝 뒤 30분(또는 허용 지연의 2배) 안에 울린 이상은 **오탐으로 세지 않는다.**

## 예시 (`sample/` 파일로 돌린 결과)

```
탐지 적발: 2/3개 사건을 허용 시간 안에 잡았습니다.
  - INC-PG PG 장애: 맞게 잡음 (10.0분 만에, 허용 15분)
  - INC-SINK S3 Sink 정지(소비 지연): 맞게 잡음 (24.0분 만에, 허용 30분)
  - INC-DUP 성공 결제 중복: 잡았지만 늦음 (14.0분 만에, 허용 10분)
오탐: 사건과 상관없는 이상이 2건(이어진 것을 합치면 1덩어리)입니다.
채점하지 않은 사건 3건 (앞뒤에 울린 이상은 오탐으로 세지 않음): ...
층 판별: 2/3개 사건의 원인 층을 맞혔습니다.
근거 연결: 주장 6개 중 4개에 근거가 있습니다 (67%).
```

## 실행

```
cd agent/eval
python3 test_score.py                                    # 시험 (표준 라이브러리만 사용)

# 실제 정답표는 S3에서 폴더로 내려받는다 (버킷 이름은 공개 문서에 쓰지 않는다)
aws s3 sync s3://<버킷>/ground_truth/incident_log/ ./incident_log

python3 score.py --incidents ./incident_log --anomalies anomalies.csv \
                 --runs detection_runs.csv --reports reports.json
python3 score.py ... --allow PG_OUTAGE=15,SINK_PAUSE=30,DATA_POLLUTION/DUPLICATE_SUCCESS_PAYMENT=10   # 허용 지연 바꾸기
python3 score.py ... --exclude <사건id>,<사건id>         # 채점에서 더 빼기
python3 score.py ... --include ORDER_TOTAL_MISMATCH      # 주문 총액 불일치도 채점
python3 score.py ... --json                              # 요약을 JSON으로
```

이상 이력은 Athena에서 `SELECT * FROM gold_b.anomaly` 결과를 CSV로 받으면 된다(순찰 기록은 `gold_b.detection_runs`).

## 어느 부분이 어느 코드인가

| 하는 일 | 코드 (`score.py`) |
|---|---|
| 정답표 읽기(start·end 파일을 사건 하나로 합침) | `load_incidents()` |
| 채점에서 뺄 사건 id 읽기 | `load_excluded()` ← `excluded_incidents.txt` |
| 이상 이력·순찰 기록 읽기(JSON, JSON Lines, CSV) | `load_rows()` |
| 채점할 사건/안 할 사건 나누기 | `split_incidents()` |
| 처음 판정한 줄만 고르기(재판정 줄 제외) | `regular_rows()` |
| 탐지 적발 | `score_detection()` |
| 오탐(안 하는 사건 시간대는 뺌) | `score_false_alarms()`, `muted_windows()` |
| 층 판별, 근거 연결 | `score_reports()` |
| 사건 종류별 정답(이상 종류, 층, 허용 지연) | `SCENARIOS`, `NOT_GRADED` |

## 입력 형식

- **정답표**: 시뮬레이터 `simulator/src/sim/controller/log.py`가 쓴다. 파일 이름 `YYYYMMDDTHHMMSSZ_<incident_id>_<start|end>.json`. start에는 `type`, `params`, 시작 시각(`at`), end에는 `ended_by`, `result`, 끝 시각이 있다. 시각은 UTC. 데이터 오염은 `params.kind`로 종류를 구분한다.
- **이상 이력**: `agent/detect`가 쌓는 `anomaly` 줄(`run_id`, `anomaly_id`, `anomaly_type`, `scope_type`, `scope_key`, `window_*`, `detected_at`).
- **원인 리포트**: `agent/investigator`가 쓰는 `investigation_reports`와 같은 이름(`anomaly_id`, `cause_layer`, `claims`)이다. 주장마다 `evidence`가 있으면 근거가 있는 것으로 센다.

## 채점에서 뺀 시험 기록 (`excluded_incidents.txt`)

2026-10-23 성철 님이 형식 확인용으로 짧게 건 시험 사건 4건(S3 Sink 정지, 데이터 오염, PG 장애, burst)이다. **이 id는 정답표 화면의 값을 옮겨 적은 것이라 실제 파일과 대조해야 한다.** 목록에 있는데 정답표에 없는 id가 있으면 실행 결과에 경고가 나온다.

## 알아야 할 것 (한계)

- **허용 지연은 팀 공지로 확정했다**(PG 장애 15분, 성공 결제 중복 10분). S3 Sink 정지 30분은 파일 전환이 15분이라는 가정의 계산값이고 아직 실측하지 않았다. 5분 전환이 적용되면 바뀐다.
- 사건 끝 뒤 허용 지연의 2배까지 울린 이상은 그 사건의 것으로 본다. 오염처럼 순간에 끝나는 사건에서 "늦음"을 구별하려는 것이다(임의 값).
- 층 판별은 "층 이름이 같은가"만 본다. 근거 연결은 "근거가 붙어 있나"만 본다. 그 근거가 진짜로 주장을 뒷받침하는지는 확인하지 않는다.
- **채점은 정답표를 읽는다.** 조사 에이전트는 정답표를 읽을 수 없게 권한을 분리해 두었으므로(재영 님 적용), 채점은 에이전트 밖에서 사람이 돌린다.
- 오탐의 "덩어리"는 같은 종류·같은 대상의 이상이 15분 안에 이어지면 하나로 센 값이다(임의 값).
- 오염 복구(UPDATE로 되돌림)는 정답표에 남지 않는다. 복구 뒤 해소 여부는 이 스크립트가 아니라 재판정(`VERIFIED`)이 보여 준다.
- 예시 파일(`sample/`)은 가짜 값이다. **실제 정답표와 이상 이력으로는 아직 돌려 보지 않았다.**
