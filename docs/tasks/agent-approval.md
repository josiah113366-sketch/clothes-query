# 작업 지시서: agent/approval

> 상태: 완료(가짜 표·가짜 Airflow 시험까지) · 브랜치: `agent/approval` · 다음 작업: 승인 화면(`dashboard/`), 재처리 DAG ID 확정, 실제 Athena·Airflow 확인

## 목표

재처리 승인의 **백엔드 규칙**을 만든다. 인프라가 IAM으로 막을 수 없는 것(어떤 단계를 쓸 수 있는지, 누가 승인했는지, 중복 승인)을 코드로 막고, 승인 뒤 Airflow DAG를 호출한다.

## 만드는 것

- `agent/approval/approval.py`, `test_approval.py`, `README.md`
- `docs/design/agent/approval-flow.md`: 규칙·상태 흐름·요청 줄 형식·Airflow 호출 계약·확정이 필요한 것
- `docs/BRANCHES.md`: agent 구역에 이 브랜치 행

## 만들지 않는 것

- 승인 화면(Streamlit 페이지), 재처리 DAG, Airflow 접속 Secret 연결

## 완료 확인

- [x] `python3 agent/approval/test_approval.py` 모두 통과(승인자·요청·승인·중복·만료·거절·Airflow 호출기)
- [x] Airflow 3.3.2의 실제 API 모양 확인(`logical_date` 필수·nullable, `/auth/token`의 `username`/`password`)
- [ ] 진짜 Athena·Airflow에서 실행 — 아직(DAG ID 미정, Secret 연결 전)

## 작업 결과

요청·승인·거절·DAG 호출 함수와 Airflow 호출기를 만들었다. 같은 승인을 두 번 눌러도 Airflow `dag_run_id`(=요청 번호)가 막는다.
