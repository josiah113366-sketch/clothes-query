# 작업 지시서: dashboard/anomaly-rca-real

> 상태: 진행 중 · 브랜치: `dashboard/anomaly-rca-real` · 다음 작업: 재영 님이 대시보드 역할에 `gold_b.anomaly`·`agent.investigation_reports` Glue·Athena 읽기 권한 추가, main 머지되면 CI/CD(#113)가 자동 배포

## 목표

대시보드 "데이터 관리 > 이상탐지"·"원인 리포트" 화면이 아직 더미인 상태였다(민혁 님 미착수). 탐지 담당(주현)이 표 정의를 가장 잘 아는 사람이라 직접 실데이터로 연결한다. 은서 님이 결제 관제·형식 오류·재처리 이력을 연결한 방식(PR #110·#117, `dashboard/data.py`의 `_athena`·`dataset()` 패턴)을 그대로 따른다.

## 바뀐 것

- `dashboard/data.py`
  - `RULE_LABELS`: 탐지 규칙 한글 이름(R1~R6), `ANOMALY_HOURS`(48시간), `RCA_DAYS`(7일)
  - `get_anomalies()`, `get_rca_reports()` 더미 데이터를 실제 DDL 컬럼(`gold_b.anomaly` / `agent.investigation_reports`)에 맞춤. `allow_empty=True`로 바꿈: 이상·리포트가 없는 것이 정상 상태라 더미로 대체하지 않는다.
  - `_real_anomalies()`: `gold_b.anomaly_current`의 최근 48시간 조회
  - `_real_rca_reports()`: `agent.investigation_reports`를 `gold_b.anomaly_current`와 `anomaly_id`로 합친 최근 7일 조회. `claims`·`problems`는 JSON 배열 문자열이라 `approval_io.load_report`와 같은 방식으로 파이썬 목록으로 바꾼다.
  - `if ATHENA_WORKGROUP:` 등록 블록에 두 함수 추가
- `dashboard/pages_data/anomaly.py`: 규칙·상태 필터, 실제 컬럼(관측값·기준값) 표시. 이상이 없으면 "현재 열린 이상이 없습니다" 안내
- `dashboard/pages_data/rca_report.py`: `claims`를 FACT(확인된 사실)/ASSUMPTION(추정)으로 나눠 표시, `cause_layer` 뱃지, `problems`가 있으면 "검증 미통과" 경고. 실제 스키마에 없던 `impact`·`evidence`·조치 진행 막대(가짜 데이터였음)는 뺐다.
- `dashboard/test_anomaly_rca_data.py`: `test_gold_b_data.py`와 같은 방식(가짜 Athena 조회, 화면 열기 시험)

## 완료 확인

- [x] `test_anomaly_rca_data.py` 18개 통과 (등록, SQL·칸, UTC 시각, 빈 결과는 정상 처리, 조회 실패 시 더미 대체, 더미/빈 결과/실데이터 모양 3가지로 화면이 열림)
- [x] `python3 -m py_compile`로 문법 확인
- [x] `test_gold_b_data.py`, `test_approval_page.py`로 기존 화면 회귀 없음 확인 (단, `test_gold_b_data.py`의 UTC 시각 시험 3개는 이 PR과 무관하게 로컬 환경의 pandas 3.x 때문에 실패함 — `is_utc()`가 `"datetime64[ns, UTC]"` 문자열을 그대로 비교해서 생기는 환경 차이. 내 새 시험은 `pd.DatetimeTZDtype` 비교로 고쳐서 영향받지 않는다)
- [ ] 재영 님 권한 반영 후 실제 Athena 조회 확인

## 작업 결과

이상탐지 화면은 `gold_b.anomaly_current`를, 원인 리포트 화면은 `agent.investigation_reports`를 읽는다. 둘 다 결과가 비어도(이상 없음, 아직 조사 전) 더미로 바뀌지 않고 "정상" 안내를 보여준다. 민혁 님이 별도로 만들 필요가 없어졌다.
