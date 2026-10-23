# 작업 지시서: dashboard/approval-page

> 상태: 완료(가짜 저장소로 시험) · 브랜치: `dashboard/approval-page` · 남은 일: 실제 연결(재영 님), 개인 계정으로 승인하는 방식 결정

## 목표

재처리 승인 백엔드(`agent/approval/approval.py`, PR #66)를 대시보드 화면에 연결한다. 사람이 이상과 조사 리포트를 보고 **요청 · 승인 · 거절**을 누를 수 있게 한다. 규칙(승인자 확인, 상태 확인, 중복 승인 방지, 재시도 횟수)은 백엔드가 지키고 화면은 그 함수를 부르기만 한다.

## 만드는 것

- `dashboard/pages_data/approval.py`: 화면 (승인 대기 → 리포트 읽기 → 승인·거절, 재처리 요청, 최근 24시간 요청 현황)
- `dashboard/approval_io.py`: 연결과 조회. `REAL`(Athena + Airflow API)과 `PRACTICE`(가짜 저장소, 내 PC 연습용)
- `dashboard/test_approval_page.py`: 연결·화면 시험
- `dashboard/app.py`: 메뉴에 "재처리 승인" 한 줄, `dashboard/requirements.txt`에 `boto3`

## 정한 것

1. **승인자는 로그인한 사용자 이메일**이어야 한다(백엔드 규칙). 공용 계정(`data_user` 등)·`dev` 로그인은 거절하고 화면에 이유를 보인다. 연습 모드만 가짜 이메일을 쓴다.
2. **승인하려면 "원인을 고쳤음을 확인했습니다"를 체크**해야 한다(설계 문서: 원인을 고친 뒤 승인).
3. **경고를 보인다.** R5·R6는 원본이 그대로면 재처리해도 해소되지 않을 수 있고, Kafka 보관 기간(3일)을 넘긴 구간은 다시 만들 수 없을 수 있다.
4. 검증을 통과하지 못한 조사 리포트(`problems` 있음)는 빨간 안내를 띄운다.
5. 같은 승인을 두 번 눌러도 승인 줄은 한 줄이다(백엔드가 막는다).

## 실제 연결에 필요한 것 (재영 님·민혁 님과)

| 항목 | 내용 |
|---|---|
| 이미지 | 대시보드 이미지에 `agent/approval/approval.py`와 `agent/detect/athena_io.py`를 넣고 `AGENT_CODE_DIR`로 가리킨다(기본은 저장소의 `agent/`). `boto3` 설치 |
| Athena | 환경변수 `APPROVAL_ATHENA_WORKGROUP`(대시보드 전용 workgroup), `AWS_REGION`. 읽기: `gold_b.anomaly_current`, `gold_b.reprocess_events`, `agent.investigation_reports`. 쓰기: `gold_b.reprocess_events` |
| Airflow | `AIRFLOW_API_URL`(클러스터 내부 주소), `AIRFLOW_API_USER`, `AIRFLOW_API_PASSWORD`를 Secret에서 주입. 접속 정보가 없으면 승인 줄만 쓰고 호출은 실패로 돌려 같은 승인으로 다시 시도할 수 있다 |
| 로그인 | **개인별 식별이 필요하다.** `AUTH_MODE=oidc`이거나, local 계정 아이디를 이메일 형식으로 사람마다 만든다(공용 3계정은 승인할 수 없음) |

## 만들지 않는 것

- 재처리 DAG 자체(은서 님·현지 님), 승인 이력의 단계별 상세(기존 "재처리 이력" 화면)
- 슬랙 알림, 승인 취소

## 완료 확인

- [x] `python test_approval_page.py`가 통과한다 (연결 21개 + 화면 7개, 연습 모드)
- [x] 코드·문서에 계정 ID·비밀번호·주소·키가 없다
- [ ] 진짜 Athena에서 목록이 읽히는지, 진짜 Airflow로 R6 DAG가 시작되는지 (재영 님 연결 뒤)
- [ ] 실제 로그인(oidc 또는 이메일 형식 local 계정)으로 승인이 되는지

## 작업 결과

가짜 저장소(sqlite)로 요청 → 승인 → 거절 → 만료, 중복 승인, 이메일이 아닌 승인자 거절, R1(poller)·R6(Airflow 호출) 차이를 시험했고, Streamlit `AppTest`로 화면이 열리고 버튼이 동작하는 것까지 확인했다. 진짜 Athena·Airflow·로그인은 아직 돌려 보지 않았다.
