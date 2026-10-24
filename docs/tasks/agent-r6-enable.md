# 작업 지시서: agent/r6-enable

> 상태: 진행 중 · 브랜치: `agent/r6-enable` · 다음 작업: 현지 님 `silver.order_amount_checks` 열 이름 확인 → 재영 님이 판정 DAG 환경 변수 추가

## 목표

판정 작업이 R6(Silver 주문 총액 불일치)을 실제로 돌 수 있게 한다. 지금은 설정 객체가 환경 변수를 읽지 않아 표 이름을 줄 방법이 없었다.

- `SILVER_CHECKS_TABLE`(예: `silver.order_amount_checks`)과 `R6_CHECK_NAME`을 환경 변수로 받는다. 비어 있으면 R6은 돌지 않는다(기본, 지금과 같음).

## 만드는 것

- `agent/detect/run_job.py`(`config_from_env`), `agent/detect/test_athena_io.py`

## 완료 확인

- [x] `test_athena_io.py`, `test_job.py`, `test_r6.py` 통과
- [ ] 현지 님 표의 열 이름이 R6이 읽는 열(`run_id, check_name, checked_at, order_id, status, order_total_amount, item_total_amount, amount_difference, check_version, source_manifest`)과 같은지 확인
- [ ] 재영 님이 판정 DAG 설정(ConfigMap)에 환경 변수와 `silver` 데이터베이스 읽기 권한을 추가
