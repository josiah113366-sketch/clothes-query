# 작업 지시서: agent/test-anomaly

> 상태: 완료 · 브랜치: `agent/test-anomaly` · 다음 작업: 재영 님이 Athena에서 시험 이상 줄을 넣고 조사 DAG 첫 실행을 확인

## 목표

실제 이상이 아직 없어도 조사 에이전트(Bedrock 호출, 검증, 저장)를 EKS에서 한 번 돌려 볼 수 있게, **시험용 이상 줄**을 넣는 SQL을 준비한다.

## 만드는 것

- `agent/investigator/test_anomaly.sql`: `anomaly_id = 'a-test-0001'` 이상 줄 INSERT, 확인 질의, 정리(RESOLVED 추가) 질의

## 구분과 정리 기준

- `anomaly_id`가 `a-test-`로 시작하면 시험 줄이다. 채점(`agent/eval/score.py`, PR #96)은 이 접두어를 건너뛴다.
- 지우지 않는다. 끝나면 같은 id로 `RESOLVED` 줄을 쌓는다.

## 완료 확인

- [x] SQL을 Athena(Trino) 문법으로 파싱해 오류가 없다 (실행은 하지 않음)
- [ ] 조사 DAG가 이 줄을 집어 `agent.investigation_runs`에 기록하고 리포트가 1건 생긴다 (재영 님 시험)
