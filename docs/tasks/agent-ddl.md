# 작업 지시서: agent/ddl

> 상태: 완료 · 브랜치: `agent/ddl` · 다음 작업: 진짜 Athena에서 표 만들기와 첫 쓰기 시험(인프라 담당과), 조사 에이전트 쓰기 코드

## 목표

판정 잡과 조사 에이전트가 쓰는 표 4개의 Athena DDL과 "현재 보기" 뷰를 정의하고, 코드(`TABLE_SPECS`)와 같은지 확인하는 시험을 만든다. 진짜 Athena에서 표를 만드는 일과 조사 에이전트의 쓰기 코드는 만들지 않는다.

## 먼저 읽을 것

- `docs/design/agent/anomaly-answer-key.md` 5절(이상 이력 컬럼), `agent/detect/athena_io.py`
- Gold B DDL 예시: `pipelines/gold_b/ddl/` (PR #36, Gold B 담당)

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- 조사 리포트와 실행 기록은 `gold_b` 밖(`agent` 데이터베이스)에 둔다 (Gold B 담당 권장, 인프라 담당이 데이터베이스와 권한을 이미 준비).

## 만드는 것

- `agent/ddl/`: `database_agent.sql`, `anomaly.sql`, `detection_runs.sql`, `investigation_reports.sql`, `investigation_runs.sql`, `views/anomaly_current.sql`, `test_ddl.py`, `README.md`
- `agent/detect/athena_io.py`: `TABLE_SPECS`에 표별 데이터베이스와 파티션을 넣고, 조사 에이전트 표 2개를 추가. `reprocess_events`는 은서 님 DDL대로 파티션 없이 씀
- `agent/detect/test_athena_io.py`: 위 변경 시험
- `agent/detect/README.md` 갱신

## 만들지 않는 것

- 진짜 Athena에서 표 만들기, 첫 쓰기 시험 (인프라 담당과 함께)
- 조사 에이전트가 두 표에 쓰는 코드 (Bedrock 호출 코드와 함께)
- `reprocess_events` DDL (Gold B 담당)

## 완료 확인

- [x] `python3 agent/ddl/test_ddl.py` 가 "모두 통과"를 출력한다 (시험 34건)
- [x] `python3 agent/detect/test_athena_io.py` 와 `test_job.py` 가 "모두 통과"를 출력한다
- [x] 계정 번호, 비밀값, 개인정보가 없다 (버킷 이름은 Gold B DDL과 같은 값)

## README 갱신

- `agent/ddl/README.md` 신규, `agent/detect/README.md`의 쓰기 방식 설명

## 작업 결과

- **한 줄 요약:** 판정 잡과 조사 에이전트가 쓰는 표 4개와 이상 "현재 보기" 뷰의 DDL을 만들고, 코드와 같은지 확인하는 시험을 더했다.
- **무엇을 만들었나:** `agent/ddl/` 파일들과 `TABLE_SPECS` 개선(데이터베이스·파티션을 표별로).
- **왜 그렇게 했나:** 인프라 담당이 표 정의와 INSERT를 기다리고 있었다. 이상 이력과 순찰 기록은 양이 적어 날짜 폴더만 두고, 은서 님의 `reprocess_events` DDL에 파티션이 없는 것을 확인해 코드가 거기에 쓸 때 `dt`·`hour`를 붙이던 것을 고쳤다(그대로면 INSERT가 실패했을 것). 리포트의 중첩 구조는 JSON 문자열로 두어 `INSERT`를 단순하게 했다.
- **입력과 출력:** DDL은 Athena에서 실행하는 SQL. 시험은 파일을 읽어 코드와 비교한다.
- **확인한 결과:** 시험 34건, `athena_io` 시험 22건이 모두 통과했다. DDL과 코드의 컬럼·타입·순서·파티션·저장 위치 일치, INSERT 문의 컬럼 순서와 표 이름 일치, 뷰가 이상별 최근 줄만 고르는지를 확인했다.
- **알려진 한계·남은 일:** 진짜 Athena에서 표를 만들거나 `INSERT`를 해 보지 않았다. 파티션 프로젝션 표에 `INSERT INTO`가 되는지는 첫 쓰기 시험에서 확인해야 하고, 안 되면 README의 대안으로 간다. 조사 에이전트의 쓰기 코드는 아직 없다.
