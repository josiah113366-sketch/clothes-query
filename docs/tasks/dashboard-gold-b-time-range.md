# 작업 지시서: dashboard/gold-b-time-range

> 상태: 진행 중 · 브랜치: `dashboard/gold-b-time-range` (`dashboard/gold-b-reliability` `fb36e64` 위에서 만듦. 같은 파일을 고치므로 그 브랜치가 먼저 머지돼야 한다) · 담당: 은서 (`dashboard/TODO.md` B11) · (2026-10-26 사용자: "파이프라인 상태, 결제 관제, 형식 오류 창에 날짜 선택? 필터링 할 수 있는 부분이 없어서 과거를 조회 못해.")

## 목표

세 화면(파이프라인 상태 › 지연·점검, 결제 관제, 형식 오류)은 최근 몇 시간만 보여 준다. 그래서 시나리오 시험이나 장애가 지나간 뒤에는 그때 모습을 다시 볼 수 없다. 화면 위에서 조회 구간을 골라 과거를 볼 수 있게 한다.

만들지 않는 것: 데이터 흐름 탭(지금 상태판), 재처리 이력(이미 최근 7일을 요청별로 본다), 이상탐지·원인 리포트 화면(탐지 담당), 하루를 넘는 구간.

## 먼저 읽을 것

- `dashboard/data.py`의 Gold B 조회 함수(`get_bronze_lag`, `get_topic_inflow`, `get_payment_attempts`, `get_duplicate_success`, `get_malformed_events`, `get_reliability_checks`)와 `dataset`, `_hour_partitions`
- `dashboard/pages_data/pipeline.py`, `payments.py`, `malformed.py`, `dashboard/ui.py`

## 정한 기본값 (설계에 없는 세부)

1. **고르는 법:** 화면 위 "조회 구간"에서 `최근`(최근 N시간, 지금처럼 실시간) 또는 `날짜 지정`(KST 날짜 + 시간 범위)을 고른다. 기본은 `최근`이고 기본 길이는 지금과 같다 (파이프라인 3시간, 결제 관제 3시간, 형식 오류 6시간).
2. **길이:** 최대 24시간. 날짜는 최근 30일 안. 날짜 지정 구간의 끝이 지금보다 늦으면 지금(분)에서 자른다. 자정을 넘는 구간은 날짜를 나눠 본다.
3. **조회:** Gold B 조회 함수가 모두 같은 꼴 `(분, 끝)`을 받는다. 끝이 없으면 지금(실시간). 시간 폴더 조건은 고른 구간으로 준다. 고른 구간마다 지금처럼 60초 캐시한다.
4. **과거 구간 표시:** 카드는 마지막 측정 대신 구간 안의 최대값과 그 시각을 보여 준다. 지연 표는 구간 중 평소 범위를 넘었거나 RUNNING이 아니었던 토픽이다. 고른 구간에 결제·지연 기록이 없으면 더미로 바꾸지 않고 "기록 없음"을 보여 준다 (조회가 실패할 때만 더미).
5. **성공 결제 중복 칸:** 화면에서 고른 구간에 적재된 성공 결제로 찾는다 (지금은 최근 6시간 고정).
6. **신뢰성 점검 ③ 적재 정지:** "마지막 기록이 2분 넘었나"는 과거 구간에서 뜻이 없다. 그래서 "구간 안에서 적재 잡·지연 수집기가 2분 넘게 쓰지 않은 적이 있나(가장 긴 쉼)"로 바꾼다. 실시간이면 구간 끝이 지금이라, 지금 멈춘 것도 그대로 잡힌다.

## 작업 순서

1. 이 지시서, 브랜치 대장
2. 조회 함수에 구간(분, 끝) 넣기, 신뢰성 점검의 가장 긴 쉼
3. 조회 구간 선택 위젯과 세 화면
4. 시험, 실제 Athena 확인
5. README·TODO와 작업 결과

## 완료 확인

- [ ] `python test_gold_b_time_range.py` 통과 (dashboard 폴더에서)
- [ ] 기존 시험: `test_gold_b_data.py`, `test_gold_b_scenarios.py`, `test_gold_b_reliability.py`, `test_approval_page.py`, `test_anomaly_rca_data.py`, `python -m pytest -q test_gold_a_io.py test_model_io.py`
- [ ] 실제 Athena에서 과거 구간 조회가 돈다 (지연·유입·점검·결제·형식 오류)
- [ ] `git diff --check`

## 작업 결과 (머지 전에 작성한다)
