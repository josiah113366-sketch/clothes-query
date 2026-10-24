# 작업 지시서: agent/silver-conf

> 상태: 진행 중 · 브랜치: `agent/silver-conf` · 다음 작업: 현지 님 `silver_gold_a_reprocess` 실제 연결 시험

## 목표

현지 님이 알려 준 Silver 재처리 호출 명세에 승인 화면의 호출 입력(conf)을 맞춘다.

- 시간대(`window_start`, `window_end`)를 UTC ISO(`2026-10-24T00:00:00Z`)로 보낸다. 전에는 `2026-10-24 00:00:00`이었다.
- 재시도 요청이면 `parent_request_id`도 보낸다.
- 나머지 필드(`request_id`, `source`, `rule_version`, `attempt`, `order_ids`, `anomaly_id`, `report_id`)는 이미 명세와 같다.

## 만드는 것

- `agent/approval/approval.py`(`_iso_z`, `start_run`), `agent/approval/test_approval.py`

## 완료 확인

- [x] `test_approval.py`, `dashboard/test_approval_page.py` 통과
- [ ] 승인 화면 → `silver_gold_a_reprocess` 실제 호출 시험 (현지 님 권한 연결 뒤)

## 남은 일 (이 브랜치 밖)

- R6 재판정: 재처리 DAG는 VERIFIED를 쓰지 않으므로, `LEDGER_REPLACED`(source=SILVER, status=SUCCESS)가 오면 판정이 `silver.silver_runs`·`silver.order_amount_checks`로 대상 주문의 후속 PASS를 확인해 해소한다. 표가 Athena에 올라온 뒤 구현한다.
