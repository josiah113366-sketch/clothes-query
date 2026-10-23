# 작업 지시서: pipelines/gold-b-format-check

> 상태: 진행 중 · 브랜치: `pipelines/gold-b-format-check` (`pipelines/gold-b-reprocess` 위에서 갈라짐) · 다음 작업: 적재 잡 연결 (`pipelines/gold-b-ingest`)

## 목표

Kafka 메시지 하나를 공통 형식 규칙(`docs/contracts/format_rules.yaml`, 소비 경로 `gold_b`)으로 검사해 원장 ①②④의 재료(`ledger.Judgement`)를 돌려주는 **형식 검사기**를 만든다 (2단계). 적재 잡과 재처리 잡이 같은 검사기를 쓴다. 재처리 잡의 실행 입구(명령줄)도 이 검사기와 함께 만든다.

## 먼저 읽을 것

- `docs/design/gold-b/README.md` 「처리 규칙」, 「④ `malformed_events`」, 2단계 체크리스트
- `docs/contracts/format_rules.yaml`, `pipelines/format_rules.py` (`FormatRules(consumer="gold_b")`, `errors()`)
- `pipelines/payment_fingerprint.py`
- `pipelines/gold_b/ledger.py` (`Checker`, `Judgement`, `message_rows`)
- `pipelines/gold_b/tests/samples/` (샘플과 기대 결과)

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- 검사기가 `ledger.py`(`pipelines/gold-b-reprocess`)를 쓰므로 그 브랜치 위에서 갈라졌다. PR은 `pipelines/gold-b-reprocess`가 머지된 뒤에 머지한다.
- 커밋 메시지에 Claude 공동 작성자 줄을 넣지 않는다.

## 정한 것 (2026-10-23 사용자 결정)

1. **모르는 실패 코드:** 규칙표 0.2.0대로 `INVALID_VALUE`로 ④에 남기고 ①에서 뺀다. 샘플 `unknown_failure_code`의 기대값을 바꾼다. ①에 넣고 `UNKNOWN`으로 나누는 확장안은 보류한다 (현지 님 합의, 규칙 버전, 판정 규칙이 먼저 필요).
2. **`raw_sample`:** 필드 이름은 모두 남긴다. 개인정보가 아닌 업무 값(상태, PG, 결제수단, 실패 코드, 시도 번호, 금액, 수량, 단가, 이벤트 종류, `__op`)만 그대로 두고, ID·시각·회원 속성·자유 문자열은 `***`로 가린다.
3. **`rule_id` 칸:** `malformed_events`에 더하지 않는다. 위 2번으로 원인을 구분할 수 있다.
4. **`reviews.raw`:** 형식 검사하지 않는다. ② `topic_messages`에만 남는다.

## 정한 기본값 (설계에 없는 세부)

1. 토픽 → 규칙 이름: `payments`→`payments`, `orders`→`orders`, `order-items`→`order_items`, `members-events`→`members`, `clickstream`→`clickstream`. 목록에 없는 토픽은 검사하지 않는다.
2. 값이 없거나, UTF-8·JSON이 아니거나, JSON 객체가 아니면 `PARSE_ERROR` 한 줄(`field = __message__`)이다. 필드를 알 수 없어서 가릴 수 없으므로 `raw_sample`은 비운다.
3. 결제 원장 ①에는 오류가 없고 `__op`가 `c`·`r`인 결제만 넣는다. 그 밖의 `__op`(`u` 등)나 `__op`가 없는 결제는 ②에만 남고 오류로 남기지 않는다 (설계: `c`·`r`만 ①).
4. 지문(`payment_fingerprint`)을 만들 수 없으면(예: 소수초 7자리) 그 필드의 `INVALID_VALUE` 한 줄을 남긴다. Silver와 같다.
5. `raw_sample`은 메시지의 첫 오류 줄에만 넣고 최대 1000자다. 그대로 두는 값도 40자를 넘으면 가린다.
6. 규칙표에 Gold B가 쓰는 규칙이 없으면 검사기를 만들 때 실패한다 (조용히 통과하지 않음).
7. 재처리 실행 입구: `python -m pipelines.gold_b.jobs.reprocess`가 poller로 요청 하나를 골라 돌린다. 설정은 환경변수(원장 위치, Kafka 접속, 규칙 파일 경로)다. 할 일이 없거나 성공하면 0, 실패하면 1로 끝낸다.

## 만드는 것

- `pipelines/gold_b/format_check.py`: `FormatChecker`, `mask_sample`
- `pipelines/gold_b/tests/test_format_check.py`: 샘플 전부의 기대 결과, 결제 줄과 지문, 마스킹, 지문 오류, 규칙 버전
- 샘플 기대값 3개(`unknown_failure_code`, `member_with_pii_column`, `review_bad_rating`)와 `test_ddl.py`의 토픽별 샘플 시험
- `pipelines/gold_b/jobs/reprocess.py`: 실행 입구 `main()`
- `pipelines/gold_b/requirements.txt`: `PyYAML` (규칙표 읽기)
- 설계 문서의 처리 규칙·2단계 체크, `pipelines/gold_b/README.md`, `jobs/README.md`, `docs/BRANCHES.md` 한 줄

## 만들지 않는 것

- 적재 잡 연결 (`pipelines/gold-b-ingest`)
- Airflow DAG, 이미지 (재영 님)
- 규칙표 변경 (모르는 실패 코드 확장안, `rule_id` 칸)

## 완료 확인

- [ ] `python -m pytest -q pipelines/gold_b/tests` 통과
- [ ] `python -m pytest -q pipelines` 통과
- [ ] 샘플 31개가 모두 기대 결과와 같은지 (형식 검사기 + `message_rows`)
- [ ] `raw_sample`에 개인정보 값·ID·시각이 남지 않는지
- [ ] 코드·README에 비밀값·실제 주소·버킷 이름이 없는지 (`git grep`)

## 작업 결과 (머지 전에 작성한다)

(작업 뒤에 쓴다)
