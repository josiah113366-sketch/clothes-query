# 작업 지시서: agent/r6-per-order

> 상태: 진행 중 · 브랜치: `agent/r6-per-order` · 다음 작업: 현지 님 확인 후 머지, 재영 님이 이미지 digest 반영

## 목표

R6 이상 해소를 **실행 전체 품질이 아니라 대상 주문별**로 판정한다. 현지 님이 확인한 실제 Silver 결과에는 오염 대상 30건 외에 `PENDING_REFERENCE` 1건(주문상품 누락)이 있어서, 이전 방식(실행 전체 `quality_status=PASS`일 때만 해소)이면 30건이 모두 복구돼도 실행이 계속 `INCOMPLETE`라 해소가 영원히 막힌다.

## 바뀌는 규칙

- `silver_runs.status = COMPLETED`인 실행만 쓴다(그대로).
- 기존 R6 이상의 대상 주문이 가장 최근 완료 실행의 금액 검사에서 `PASS`이면 그 주문만 해소한다.
- `MISMATCH`면 유지한다. `UNVERIFIED`·`PENDING_REFERENCE`·`ITEM_ERROR`이거나 행이 없으면 해소하지 않는다.
- 일부 주문만 PASS면 그 주문만 해소하고 나머지는 유지한다.
- 실행 전체 `quality_status`와 격리 기록은 판정이 바꾸지 않는다.
- 재처리 요청의 `VERIFIED`는 이 규칙과 별개다(`SUCCESS`·보류 없음·대상 주문 PASS). 이 브랜치는 만들지 않는다.

## 만드는 것

- `agent/detect/job.py`(`_r6`), `agent/detect/rules.py`(주석), `agent/detect/test_r6.py`, `agent/dags/README.md`(설명 한 줄)

## 완료 확인

- [x] `test_r6.py`, `test_job.py`, `test_athena_io.py` 통과 (INCOMPLETE 실행에서도 주문별 판정, 일부 PASS, 행 없음 유지)
- [ ] 은서 님 리뷰, 머지 뒤 재영 님이 새 이미지 digest 반영
