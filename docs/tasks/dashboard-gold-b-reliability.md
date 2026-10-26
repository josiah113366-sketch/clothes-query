# 작업 지시서: dashboard/gold-b-reliability

> 상태: 검토 대기 · 브랜치: `dashboard/gold-b-reliability` (최신 `main` `97d33df`에서 만들고 2026-10-26 `78ae762` 위로 다시 올림) · 담당: 은서 (`dashboard/TODO.md` B3) · 다음 작업: PR (사용자), 배포 (main 자동 배포) (2026-10-25 사용자: "원장 신뢰성 점검 칸을 실제 점검 쿼리로 연결해줘 (TODO B3)")

## 목표

파이프라인 상태 › 지연·점검 탭의 **원장 신뢰성 점검** 칸은 더미라서 원장에 문제가 생겨도 늘 "정상"이 보였다. 실제 점검 쿼리로 연결해서, 빠짐·중복·멈춤이 생기면 화면이 알려 주게 한다.

만들지 않는 것: 점검 결과를 이상 이력이나 알림으로 남기는 것(탐지·조사 담당), 조사 도구(`agent/tools`) 변경.

## 먼저 읽을 것

- `agent/reliability/README.md`, `agent/reliability/reliability_queries.sql` (점검 3종의 정의와 한계)
- `agent/tools/ledger_tools.py`의 `ledger_reliability` (조사 에이전트가 쓰는 같은 질문)
- `dashboard/data.py`의 `get_reliability_checks`(더미), `_athena`, `_hour_partitions`, `dashboard/pages_data/pipeline.py`

## 정한 기본값 (설계에 없는 세부)

1. **질문은 조사 도구와 같다:** ① 오프셋 빈틈(파티션마다 offset 칸 수 - 고유 offset 수), ② 같은 메시지 위치 중복(같은 결제 번호는 Debezium 재전송 등으로 생기고 뷰가 걸러 주므로 참고로만), ③ 적재 잡의 마지막 `loaded_at`과 지연 수집기의 마지막 `collected_at`이 2분(`STALE_SEC`)을 넘었는지.
2. **범위:** 최근 180분(지연·유입 그래프와 같은 길이), Kafka 시각 기준. 적재 잡이 1분 묶음으로 쓰므로 지금 분과 직전 분은 덜 찼을 수 있어 뺀다. 모든 표에 시간 폴더 조건을 준다.
3. **조회 한 번:** 화면이 1분마다 다시 읽으므로 세 점검을 Athena 조회 한 번(스칼라 하위 조회)으로 계산한다.
4. **결과 값:** `정상` / `확인 필요` / `문제`. 빈틈이 없어도 메시지가 보인 파티션 수가 지연 수집기가 재는 파티션 수보다 적으면 `확인 필요`(파티션 통째로 빠진 것은 ①로 못 찾는 한계 보완). 기록이 아예 없으면 멈춤으로 본다(`문제`).
5. **화면:** 정상이 아닌 항목이 있으면 표 위에 경고(그 시간대 탐지 결과를 믿지 말고 Gold B부터 확인)를 띄운다. 탭 아래 더미 안내는 실제로 더미인 칸만 적고, 모두 실데이터면 띄우지 않는다.
6. 칸은 더미와 같다 (`check`, `target`, `result`, `detail`, `checked_at`). 조회가 실패하면 지금처럼 더미로 대체한다.

## 작업 순서

1. 이 지시서, 브랜치 대장, #122 머지 표시
2. `_real_reliability_checks`와 등록, 화면의 경고·더미 안내
3. 시험, 실제 Athena 확인
4. README·TODO와 작업 결과

## 완료 확인

- [x] `python test_gold_b_reliability.py` 통과 (dashboard 폴더에서)
- [x] 기존 시험: `test_gold_b_data.py`, `test_gold_b_scenarios.py`, `test_approval_page.py`, `test_anomaly_rca_data.py`, `python -m pytest -q test_gold_a_io.py`
- [x] 실제 Athena에서 점검 조회가 돈다
- [x] `git diff --check`

## 작업 결과 (머지 전에 작성한다)

### 만든 것

- `dashboard/data.py`: `_real_reliability_checks(분)`. 최근 180분 원장(`topic_messages`, `bronze_lag_snapshots`, `payment_events`)을 Athena 조회 한 번으로 읽어 점검 3줄을 만든다. workgroup 환경변수가 있을 때 `_REAL["get_reliability_checks"]`에 등록한다. 상수 `RELIABILITY_MINUTES`(180), `STALE_SEC`(120).
- `dashboard/pages_data/pipeline.py`: 원장 신뢰성 점검 칸에 범위 부제, 정상이 아닌 항목이 있으면 경고. 탭 아래 더미 안내는 실제로 더미인 칸만, 모두 실데이터면 띄우지 않는다.
- `dashboard/test_gold_b_reliability.py` (24개): 등록, SQL(원장 3개, 시간 폴더, 덜 찬 분 빼기, 빈틈·중복 계산식), 판정(정상, 빈틈 → 문제, 빠진 파티션 → 확인 필요, 같은 위치 중복 → 문제, 같은 결제 번호만 → 정상, 2분 넘게 안 씀·기록 없음 → 문제, 119초 → 정상), 화면(더미·정상·문제·모두 실데이터).
- 문서: `dashboard/README.md` 배포 8번, `dashboard/TODO.md` B3, #122 머지 표시.

### 왜

- 더미 칸은 늘 "정상"이라, 원장에 빠짐·중복이 생기거나 적재 잡이 멈춰도 화면으로 알 수 없었다. 이 점검은 탐지 결과를 믿어도 되는지 가르는 기준이다.

### 확인한 결과

- `python test_gold_b_reliability.py` 24개 통과. 기존 `test_gold_b_data.py` 36개, `test_gold_b_scenarios.py` 28개, `test_approval_page.py` 28개, `test_anomaly_rca_data.py` 19개, `test_gold_a_io.py` 19개 통과 (로컬 Python 3.12, streamlit 1.59.2, `streamlit_echarts`는 가짜 모듈).
- 2026-10-26 최신 `main`(`78ae762`, 이상탐지·원인 리포트·감성분석 화면 실데이터 연결 포함) 위로 다시 올린 뒤(충돌 없음) 다시 돌림: `test_gold_b_reliability.py` 24개, `test_gold_b_data.py` 37개, `test_gold_b_scenarios.py` 29개, `test_approval_page.py` 29개, `test_anomaly_rca_data.py` 28개, `python -m pytest -q test_gold_a_io.py test_model_io.py` 33개 모두 통과.
- 코드를 일부러 틀리게 바꾼 7가지(등록 빠짐, 빠진 파티션 판정, 기록 없음 판정, 결제 번호로 중복 판정, 경고 빠짐, 더미 안내 고정, 빈 더미 안내)를 시험이 모두 잡았다.
- 실제 Athena (은서 님 AWS 자격, 대시보드 workgroup, SELECT만, 2026-10-25 17:5x KST): 빈틈 0건(파티션 15개), 같은 위치 중복 0건, 같은 결제 번호 6건(모두 같은 결제의 생성 이벤트가 두 번 온 것: Debezium 재전송, 참고), 마지막 기록 적재 잡 57초 전·지연 수집기 16초 전 → 세 점검 모두 정상.

### 알아 둘 것

- ①은 관측된 처음~끝 offset 사이만 본다. 구간 경계에서 Kafka 시각 순서가 뒤바뀐 메시지가 있으면 빈틈으로 보일 수 있다 (지금까지 실제 원장에서는 없었다).
- ③의 적재 잡 기준은 메시지가 2분 넘게 안 오면 잡이 멀쩡해도 멈춤으로 보일 수 있다 (`agent/reliability/README.md`의 한계와 같음).

### 다음 할 일

- 사용자: push, PR (머지하면 main 자동 배포로 대시보드에 반영)
