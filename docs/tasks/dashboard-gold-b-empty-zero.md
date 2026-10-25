# 작업 지시서: dashboard/gold-b-empty-zero

> 상태: 완료 (#122, 2026-10-25 머지) · 브랜치: `dashboard/gold-b-empty-zero` (최신 `main` `df12e7f`) · 담당: 은서 (`dashboard/TODO.md` B1·B10) · 다음 작업: PR (사용자), 배포 (main 자동 배포) (2026-10-25 사용자: "없으면 0건으로 보이게 하는게 나은것 같아")

## 목표

형식 오류·재처리 이력 화면은 실데이터에 연결돼 있지만, 결과가 0건이면 "비면 더미" 규칙 때문에 더미가 보였다 (2026-10-25 확인: `malformed_events` 0건, `reprocess_events` 0건, 대시보드 조회 실패 기록 없음). 두 화면은 평소 0건이 정상이라 **결과가 비면 0건으로 보이게** 한다.

만들지 않는 것: 결제 관제의 빈 결과 처리(지금처럼 더미), 다른 화면의 규칙 변경.

## 먼저 읽을 것

- `dashboard/data.py` (`dataset`의 `allow_empty`, `get_malformed_events`, `get_reprocess_events`)
- `dashboard/pages_data/malformed.py`, `dashboard/pages_data/reprocess.py`

## 정한 기본값

1. `get_malformed_events`, `get_reprocess_events`에 `allow_empty=True`를 붙인다 (`dashboard/gold-b-scenarios`에서 만든 선택지). 조회가 **실패**하면 지금처럼 더미로 대체한다.
2. 형식 오류 화면: 비면 지표 세 개를 0·0·"-"로 보이고 "최근 6시간 동안 형식 오류가 없습니다 (0건)"을 띄운 뒤 그래프·목록은 그리지 않는다 (빈 표로는 그래프를 만들 수 없음).
3. 재처리 이력 화면: 비면 "최근 7일 동안 재처리 기록이 없습니다 (0건)"을 띄운다.
4. 형식 오류 화면 설명의 "시나리오 3(스키마 오염)"을 고친다. 2026-10-23부터 시나리오 3은 형식이 맞는 업무 규칙 위반이라 결제 관제에서 보고, 이 화면은 형식 오류(판정 R4)를 본다.

## 작업 순서

1. 이 지시서, 브랜치 대장, #117 머지 표시
2. 두 함수의 `allow_empty`, 두 화면의 0건 표시와 시험
3. README·TODO와 작업 결과

## 완료 확인

- [x] `python test_gold_b_data.py`, `python test_gold_b_scenarios.py`, `python test_approval_page.py`, `python -m pytest -q test_gold_a_io.py` (dashboard 폴더에서)
- [x] 실제 Athena에 붙여 두 함수가 더미 없이 0건을 돌려준다
- [x] `git diff --check`

## 작업 결과 (머지 전에 작성한다)

### 만든 것

- `dashboard/data.py`: `get_malformed_events`, `get_reprocess_events`에 `allow_empty=True`. 등록 설명을 "결과가 없으면 결제 관제는 더미, 형식 오류·재처리 이력은 0건"으로 고쳤다.
- `dashboard/pages_data/malformed.py`: 비면 0건 지표와 "형식 오류가 없습니다 (0건)" 안내 뒤 멈춤. 맨 위 설명을 판정 R4·바뀐 시나리오 3 정의에 맞췄다.
- `dashboard/pages_data/reprocess.py`: 비면 "재처리 기록이 없습니다 (0건)" 안내 뒤 멈춤.
- 시험: `test_gold_b_data.py`에 6개 (빈 실데이터는 빈 표 그대로·더미 목록에 없음, 형식 오류도 조회 실패면 더미, 두 화면이 빈 실데이터로 오류 없이 열리고 0건 안내가 나오며 더미 안내는 없음). `test_gold_b_scenarios.py`의 "비면 더미" 대조 예시를 형식 오류에서 결제 시도로 바꿨다.
- 문서: `dashboard/README.md` 배포 6번, `dashboard/TODO.md` B10 메모, #117 머지 표시.

### 왜

- 형식 오류는 시뮬레이터가 깨진 형식을 넣지 않아 평소 0건이고(2026-10-25 Bronze v2 원본 161,680건 재검사 오류 0), 재처리 기록은 요청이 없으면 0건이다. 이때 더미가 보이면 실제로는 문제가 없는데 오류·재처리가 있는 것처럼 보인다.

### 확인한 결과

- `python test_gold_b_data.py` 36개, `python test_gold_b_scenarios.py` 28개, `python test_approval_page.py` 28개, `python -m pytest -q test_gold_a_io.py` 19개 통과 (로컬 Python 3.12, streamlit 1.59.2, `streamlit_echarts`는 가짜 모듈).
- 두 함수의 `allow_empty`, 두 화면의 빈 결과 처리를 하나씩 빼면 시험이 모두 실패했다.
- 실제 Athena (은서 님 AWS 자격, 대시보드 workgroup, SELECT만): 형식 오류 0건, 재처리 0건이 더미 없이 그대로 온다.

### 다음 할 일

- 사용자: push, PR (머지하면 main 자동 배포로 대시보드에 반영)
