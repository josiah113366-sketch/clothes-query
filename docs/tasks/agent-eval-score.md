# 작업 지시서: agent/eval-score

> 상태: 완료(예시 파일로 시험) · 브랜치: `agent/eval-score` · 다음 작업: 실제 정답표와 이상 이력으로 한 번 돌려 보기

## 목표

정답표(`incident_log`)와 이상 이력(`anomaly`)·원인 리포트를 비교해 점수를 내는 **채점 스크립트**를 머지한다. 예전 초안(`agent/eval-skeleton`, 머지 안 됨)은 옛 사건 이름과 옛 정답표 형식을 썼다. 이번에 **시뮬레이터가 실제로 쓰는 형식**(사건 하나 = start·end 파일 둘)과 최신 사건 이름에 맞춘다.

## 바뀐 것

- 정답표: 사건 하나를 start·end 두 파일에서 합쳐 읽는다. 사건 종류는 `PG_OUTAGE`, `SINK_PAUSE`, `DATA_POLLUTION`(`params.kind`로 `DUPLICATE_SUCCESS_PAYMENT`·`ORDER_TOTAL_MISMATCH` 구분)이다.
- 사건 2: burst(`INGEST_LAG`)는 S3 Sink가 모두 소화해 소비 지연이 안 생기므로 채점하지 않고, **`SINK_PAUSE` → `BRONZE_LAG_SPIKE` / 적재 층 / R3**로 채점한다. 허용 지연 30분.
- 허용 지연: PG 장애 15분, 성공 결제 중복 10분(공지 확정), S3 Sink 정지 30분.
- 주문 총액 불일치(R6)는 Silver 정기 실행이 정해질 때까지 기본으로 채점하지 않는다(`--include`).
- 채점 제외: `excluded_incidents.txt`(10/23 시험 사건 4건)와 `--exclude`. 채점하지 않는 사건 시간대에 울린 이상은 오탐으로 세지 않는다.

## 만드는 것

- `agent/eval/score.py`, `test_score.py`, `README.md`, `excluded_incidents.txt`, `sample/`(실제 형식의 예시)
- `docs/BRANCHES.md` 한 줄

## 완료 확인

- [x] `python3 agent/eval/test_score.py`가 통과한다 (정답표 읽기, 채점 대상 나누기, 점수, 허용 지연 바꾸기, 끝 기록 없는 사건, 모르는 사건, 명령줄 실행)
- [ ] 실제 정답표(S3에서 내려받음)와 실제 `gold_b.anomaly`로 한 번 돌려 본다 (판정 DAG가 정상으로 돈 뒤)
- [ ] `excluded_incidents.txt`의 id를 실제 정답표 파일 이름과 대조한다 (정답표 화면에서 옮긴 값이라 오타가 있을 수 있음. 어긋나면 실행 결과에 경고가 나온다)

## 작업 결과

예전 초안의 채점 방식(적발·오탐·층·근거)은 그대로 두고, 입력을 실제 정답표 형식에 맞췄다. 사건 이름과 허용 지연을 최신으로 바꾸고, 채점하지 않을 사건을 이유와 함께 보여 준다. 진짜 데이터로는 아직 돌려 보지 않았다.
