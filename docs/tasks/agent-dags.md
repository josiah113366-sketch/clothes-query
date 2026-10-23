# 작업 지시서: agent/dags

> 상태: 완료(실제 클러스터 실행은 아직) · 브랜치: `agent/dags` · 다음 작업: 이미지 빌드·ECR push, 업무용 ConfigMap 공급, 실제 실행 확인(인프라 담당과)

## 목표

판정 잡과 조사 에이전트를 **5분마다 Airflow가 실행**하게 연결하는 DAG를 `agent/dags/`에 만든다. 인프라 담당이 정한 방식(DAG는 `agent/dags/`에 PR, Airflow가 Git 경로를 가져옴, 이미지 digest·설정은 업무용 ConfigMap)을 따른다.

## 만드는 것

- `agent/dags/agent_common.py`, `agent_detection.py`, `agent_investigation.py`, `test_dags.py`, `.airflowignore`, `README.md`
- `docs/BRANCHES.md`: agent 구역에 이 브랜치 행

## 만들지 않는 것

- 이미지 빌드·push, ConfigMap 공급, 배포(인프라 담당)
- 재처리 DAG, 승인 화면의 Airflow 호출

## 완료 확인

- [x] `python3 agent/dags/test_dags.py` 모두 통과(설정 읽기, Pod 설정, DAG 파일 주요 값)
- [x] `python3 agent/dags/test_dags.py --airflow`: Airflow 3.3.2의 DagBag으로 DAG 2개가 오류 없이 불러와짐
- [x] 순찰 시각 템플릿이 예약 실행과 수동 실행 모두에서 풀림
- [x] 코드에 이미지 주소·계정 ID·비밀값이 없음
- [ ] 실제 클러스터에서 Pod 실행 — 아직(이미지와 ConfigMap이 공급돼야 함)

## 작업 결과

판정 DAG(`agent_detection_5min`)와 조사 DAG(`agent_investigation_5min`)를 만들었다. 처음엔 paused로 등록된다. 자원과 제한 시간은 측정 전의 임의 값이다.
