# 작업 지시서: agent/r6-enable

> 상태: 진행 중 · 브랜치: `agent/r6-enable` · 다음 작업: 현지 님 `silver.order_amount_checks` 열 이름 확인 → 재영 님이 판정 DAG 환경 변수 추가

## 목표

판정 작업이 R6(Silver 주문 총액 불일치)을 실제로 돌 수 있게 한다. 지금은 설정 객체가 환경 변수를 읽지 않아 표 이름을 줄 방법이 없었다.

- `SILVER_CHECKS_TABLE`(예: `silver.order_amount_checks`), `SILVER_RUNS_TABLE`(예: `silver.silver_runs`), `R6_CHECK_NAME`을 환경 변수로 받는다.
- `SILVER_RUNS_TABLE`을 주면 `status = 'COMPLETED'`인 Silver 실행만 `(completed_at, run_id)` 순서로 가장 최근 것을 읽는다(현지 님 합의). `quality_status`가 `PASS`가 아닌 실행(예: `INCOMPLETE`)에서는 PASS 줄이 있어도 해소하지 않는다. 불일치는 품질과 상관없이 이상으로 기록한다. 비어 있으면 R6은 돌지 않는다(기본, 지금과 같음).

## 만드는 것

- `agent/detect/run_job.py`(`config_from_env`), `agent/detect/rules.py`(`silver_runs_table`), `agent/detect/job.py`(`_r6`), `agent/detect/test_athena_io.py`, `agent/detect/test_r6.py`

## 완료 확인

- [x] `test_athena_io.py`, `test_job.py`, `test_r6.py` 통과
- [x] 현지 님 표(`silver.order_amount_checks`)에 R6이 읽는 열(`run_id, check_name, checked_at, order_id, status, order_total_amount, item_total_amount, amount_difference, check_version, source_manifest`)이 모두 있음 (DESCRIBE로 확인, 10/24)
- [x] 표의 `check_name` 실제 값은 `order_item_total_match`로 R6 기본값과 같음 (`R6_CHECK_NAME` 불필요)
- [ ] 재영 님이 판정 DAG 설정(ConfigMap)에 `SILVER_CHECKS_TABLE`, `SILVER_RUNS_TABLE`과 `silver` 데이터베이스 읽기 권한을 추가
