# 작업 지시서: agent/followups

> 상태: 완료 · 브랜치: `agent/followups` · 다음 작업: 없음 (리뷰 반영)

## 목표

은서 님 리뷰에서 나온 작은 수정 둘을 반영한다.

1. **R4 형식 검사 규칙 버전 기본값 `0.1.0` → `0.2.0`.** 공통 형식 규칙 YAML(`docs/contracts/format_rules.yaml`)의 `version`이 0.2.0이 되었는데 판정 잡 기본값이 옛 값이라, 그대로 두면 R4가 Gold B의 `malformed_events.rule_version`과 달라 **조용히 0건**이 된다. 같은 일이 다시 생기지 않게 **YAML 버전과 기본값이 같은지 확인하는 시험**을 추가했다.
2. `agent.investigation_runs.status`에 `EXPIRED`(조사 기간을 넘겨 조사하지 못한 이상의 표시) 설명을 DDL 주석에 추가한다. 코드는 PR #54에 있다.

## 만드는 것

- `agent/detect/rules.py`, `agent/detect/README.md`, `agent/detect/test_job.py`
- `agent/ddl/investigation_runs.sql`(주석만), `docs/design/agent/anomaly-answer-key.md`(R4 규칙 버전 행)

## 완료 확인

- [x] `test_job.py`, `test_r6.py`, `test_athena_io.py`, `agent/ddl/test_ddl.py`가 모두 통과한다
- [x] 시험이 YAML의 `version`과 `Config().format_rule_version`이 같은지 확인한다

## 작업 결과

R4 기본 규칙 버전을 `0.2.0`으로 올리고, YAML과 어긋나면 시험이 실패하게 했다. DDL 주석에 `EXPIRED`를 적었다(표 구조는 바뀌지 않는다).
