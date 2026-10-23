# 작업 지시서: pipelines/gold-b-format-check

> 상태: 완료 · 브랜치: `pipelines/gold-b-format-check` (`pipelines/gold-b-reprocess` 위에서 갈라짐, 최신 `main` #78까지 포함) · main 대상 PR 제출 (`pipelines/gold-b-reprocess`는 #84로 머지됨) · 다음 작업: 적재 잡 연결 (`pipelines/gold-b-ingest`)

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

- [x] `python -m pytest -q pipelines/gold_b/tests` 통과 (100개)
- [x] `python -m pytest -q pipelines` 통과 (185개)
- [x] 재처리 브랜치(최신 `main` #78 포함)를 다시 병합한 뒤 `pipelines/gold_b/tests` 123개, `pipelines` 208개 통과 (수집기 시험 23개 포함)
- [x] 샘플 31개가 모두 기대 결과와 같은지 (형식 검사기 + `message_rows`)
- [x] `raw_sample`에 개인정보 값·ID·시각이 남지 않는지
- [x] 코드·README에 비밀값·실제 주소·버킷 이름이 없는지 (`git grep`)

## 작업 결과 (머지 전에 작성한다)

- **한 줄 요약:** Kafka 메시지 하나를 공통 형식 규칙(소비 경로 `gold_b`)으로 검사해 ① 결제 줄(지문 포함)과 ④ 오류 목록을 만드는 형식 검사기를 만들고, 재처리 잡이 이 검사기로 실제로 돌 수 있게 실행 입구를 붙였다.
- **무엇을 만들었나:**
  - `pipelines/gold_b/format_check.py`: `FormatChecker`(토픽 → 규칙 이름, JSON 읽기, `errors()`, `__op` `c`·`r` 결제에 지문, 지문 오류), `mask_sample`(필드 이름 유지, 업무 값만 남김)
  - `pipelines/gold_b/jobs/reprocess.py`: 실행 입구 `main()` (`python -m pipelines.gold_b.jobs.reprocess`, `--dry-run`), `kafka_config_from_env`
  - `pipelines/gold_b/tests/test_format_check.py`(43개), `test_reprocess.py`에 실행 입구 시험 3개
  - 샘플 기대값 3개와 설명 2개, `test_ddl.py`(형식 검사 안 하는 토픽, 결제 줄 수 10 → 9)
  - 설계 문서(형식 검사기 규칙, `raw_sample`, 모르는 실패 코드, `reviews.raw`, 2단계 체크), `pipelines/gold_b/README.md`, `jobs/README.md`(환경변수, DAG 명세), `samples/README.md`, `requirements.txt`(`PyYAML`)
- **왜 그렇게 했나:**
  - 검사는 공통 검사기(`pipelines/format_rules.py`)의 `errors()`를 그대로 쓴다. Silver와 같은 규칙표·같은 함수로 판단해야 같은 메시지를 다르게 판단하는 일이 없다. Silver는 첫 오류만, Gold B는 오류를 전부 쓴다.
  - 결제 지문은 Silver와 같은 `payment_fingerprint`로, 시각을 바꾸기 전의 원문으로 만든다. 규칙표는 통과했는데 지문을 만들 수 없으면 Silver처럼 `INVALID_VALUE`로 남긴다. 지금 규칙표는 지문 함수보다 넓지 않아서 이 경우는 생기지 않지만, 규칙표가 바뀌어도 원장에 이상한 줄이 들어가지 않게 했다.
  - `raw_sample`은 "문제를 알 수 있게, 개인정보는 없게"를 기준으로 했다 (2026-10-23 결정). 예: 모르는 실패 코드 샘플은 `"failure_code":"PG_MAINTENANCE"`가 보이고 ID·시각은 `***`다.
  - 실행 입구에서 규칙표·Kafka 설정 같은 준비 단계가 실패하면 요청을 `FAILED`로 남기지 않는다. 배포 문제이지 요청의 문제가 아니어서, 고친 뒤 다음 5분에 다시 고르게 했다.
- **확인한 결과:**
  - `pipelines/gold_b/tests` 100개 통과 (테이블 정의 22, 재처리·poller·실행 입구 30, 뷰 5, 형식 검사 43). `pipelines` 185개 통과. `git diff --check` 통과.
  - 샘플 31개 전부: ① 결제 줄 여부와 ④ 오류(필드·사유)가 샘플 기대값과 같다. `message_rows`를 거치면 ② 31줄, ① 9줄, ④는 샘플 기대 오류 수와 같다.
  - 실행 입구: 승인 화면이 Athena로 쓴 것 같은 확장자 없는 `APPROVED` 파일을 두고 돌리면, 실제 형식 검사기로 06시 폴더를 교체하고 `STARTED`·`LEDGER_REPLACED`를 남긴다. 다시 부르면 끝난 요청이라 아무것도 하지 않는다.
  - `raw_sample` 14개 모두 ID·시각·개인정보(`<redacted>`, 리뷰 본문)가 보이지 않는다.
  - `git grep`: 새로 넣은 비밀값·계정 ID·엔드포인트 없음. 버킷 이름은 예전부터 있던 DDL·README 줄이다 (공유 배포 설정으로 Git 관리 허용).
- **알려진 한계·남은 일:**
  - 적재 잡에는 아직 붙지 않았다 (`pipelines/gold-b-ingest`에서 연결).
  - 실제 Kafka·S3·Athena로는 돌려 보지 않았다. 배포(이미지, Pod 권한, DAG)는 재영 님과 한다 (`jobs/README.md`의 DAG 명세).
  - 실행 이미지는 Python 3.11 이상이어야 한다 (지문 함수). 재영 님 Spark 이미지는 Python 3.10이라, 재처리 잡은 Spark 없이 Python 3.11+ 이미지로 돌린다.
  - 모르는 실패 코드를 ①에 넣는 확장안, `rule_id` 칸은 하지 않았다 (위 결정).
- **팀원 확인 표 정리 (2026-10-23):** 주현 님 PR이 main에 들어간 것을 확인하고 설계 문서 팀원 확인 표를 고쳤다. #71 판정 설정 `format_rule_version` 0.2.0, #72 판정·조사 쿼리의 시간 폴더 조건, #80 `pending_replacements`의 `source IN ('KAFKA', 'BRONZE')`. 판정 잡의 `reprocess_events` 정의(`TABLE_SPECS`)도 DDL과 같아졌다(폴더 없음, `attempt` int). 남은 것은 `_replaced_filter`(R5 순찰)의 같은 `source` 조건이다. 재처리 브랜치는 이미 올라가 있어서 이 정리는 이 브랜치에 넣었다.
- **#84 머지 정리 (2026-10-23):** 재처리 브랜치가 #84로 머지되어 브랜치 대장의 재처리 줄을 머지됨으로, 재처리 작업 지시서 상태를 바꾸고, 설계 문서 7단계의 실행 입구·PR 항목을 체크했다 (실행 입구 항목은 이 브랜치에서 만들었는데 체크가 빠져 있었다).
