# 작업 지시서: agent/detect-r6

> 상태: 완료 · 브랜치: `agent/detect-r6` (`agent/detect-athena`(PR #46) 위에 쌓음) · 다음 작업: Silver 결과가 Athena 표로 제공되면 연결 확인

## 목표

Silver가 남기는 주문 총액 검사 결과를 읽어 이상 이력으로 잇는 규칙 **R6**의 초안을 만든다(Silver 담당과 합의한 기준). 실제 Silver 결과 연결과 정기 실행은 만들지 않는다.

## 먼저 읽을 것

- `agent/detect/README.md`, `docs/design/agent/anomaly-answer-key.md`
- Silver 담당의 "R6 Silver검사 결과 제공안"(노션): 컬럼, 상태값, 판정 기준

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- 읽는 방식은 합의대로 **최신 실행만**, 계속 불일치는 **지속**, 후속 `PASS`는 **해소**, 결과에서 사라졌거나 보류 상태는 **해소가 아님**.

## 만드는 것

- `agent/detect/rules.py`: `r6_order_total()`, `open_orders()`, 설정 `silver_checks_table`, `r6_check_name`
- `agent/detect/job.py`: `_r6()`(최신 실행 읽기), 재판정 비교에서 R6 제외
- `agent/detect/test_r6.py`: 시험
- `agent/detect/README.md` 갱신

## 만들지 않는 것

- Silver 결과의 Athena 표, S3 경로, 권한 (Silver·인프라 담당과 확정)
- 실행별 순차 소비(중간 실행의 발생·해소 보존). 필요해지면 추가 협의
- 채점에서 이 사건을 점수에 넣는 것 (정기 실행이 정해진 뒤)

## 완료 확인

- [x] `python3 agent/detect/test_r6.py` 가 "모두 통과"를 출력한다 (시험 17건)
- [x] `python3 agent/detect/test_job.py`, `test_athena_io.py` 가 "모두 통과"를 출력한다
- [x] 비밀값, 계정 번호, 개인정보가 없다

## README 갱신

- `agent/detect/README.md`의 규칙 설명과 "알아야 할 것"

## 작업 결과

- **한 줄 요약:** Silver 주문 총액 검사의 최신 실행을 읽어 새 불일치는 이상으로, 후속 PASS는 해소로 기록하는 규칙 R6을 만들었다.
- **무엇을 만들었나:** `rules.py`의 R6 규칙과 상태 복원 함수, `job.py`의 최신 실행 읽기, `test_r6.py`.
- **왜 그렇게 했나:** Silver가 수동 배치로 실행별 결과를 남기고 최신 묶음을 교체하므로, 같은 주문의 과거 실행을 새 오류로 또 세지 않게 "열려 있는 주문" 집합을 이전 R6 이상 줄의 근거에서 되살려 새 불일치·지속·해소를 구별한다. 에이전트는 이상 이력만 읽으므로 근거(Silver 실행 번호, 검사 버전, 실행 참조, 주문 번호, 금액 차이)를 이상 줄에 싣는다.
- **입력과 출력:** 입력은 Silver 검사 결과(`run_id`, `checked_at`, `order_id`, `check_name`, `status`, 금액 컬럼, `source_manifest`). 출력은 이상 줄(`OPEN` 또는 `RESOLVED`).
- **확인한 결과:** 가짜 Silver 표 시험 17건과 기존 시험이 모두 통과했다. 새 불일치만 기록, 같은 실행은 새 줄 없음(지속), 해소(PASS), 사라진 주문은 해소 아님, 보류 상태는 무시, 최신 실행만 읽음, 다른 검사 이름 무시, 재판정에서 제외, 잘못된 표 이름 거절을 확인했다.
- **알려진 한계·남은 일:** Silver 결과가 아직 로컬 파일이라 진짜 연결은 못 했다. 표 이름·컬럼은 제공안을 가정했다. 근거에 못 담는 500개 초과 주문, 새 `status` 값 `RESOLVED`(설계 문서에 추가 필요), 실행별 순차 소비는 남은 일이다.
