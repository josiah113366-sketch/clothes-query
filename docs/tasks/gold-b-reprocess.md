# 작업 지시서: pipelines/gold-b-reprocess

> 상태: 완료 · 브랜치: `pipelines/gold-b-reprocess` (최신 `main` `fbc6108` 병합, #78까지) · main 대상 PR 제출 · 남은 일: 실행 입구(형식 검사기와 함께), DAG(재영 님)

## 목표

승인된 시간대의 원장 ①②④를 Kafka에서 다시 읽어 시간 폴더 단위로 교체하는 **재처리 잡**(7단계, 필수 ②)의 본체를 만든다. 단계마다 `reprocess_events`에 기록을 남긴다. 메시지를 원장 줄로 바꾸는 형식 검사는 아직 없으므로 끼워 넣는 자리로 두고, 시험은 샘플의 기대 결과로 한다.

## 먼저 읽을 것

- `docs/design/gold-b/README.md` 「재실행·재처리 설계와 검증」, 「⑤ `reprocess_events`」, 7단계 체크리스트
- `pipelines/gold_b/ddl/*.sql` (원장 컬럼, 시간 폴더)
- `agent/detect/job.py` (`main`): 판정 잡이 `LEDGER_REPLACED` 줄의 `window_start`, `window_end`, `at`을 읽는 방식, 재처리로 다시 쌓인 줄을 `loaded_at <= at`으로 거르는 방식

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- #36이 머지 전이라 `pipelines/gold-b` 위에서 갈라졌다. #36이 병합 커밋으로 들어가서(2026-10-22), 커밋을 옮기지 않고 최신 `main`을 이 브랜치에 병합했다 (2026-10-23, `pipelines/gold_b/README.md`·`docs/BRANCHES.md` 충돌만 정리). PR에는 이 브랜치의 커밋만 보인다.
- 커밋 메시지에 Claude 공동 작성자 줄을 넣지 않는다.

## 정한 기본값 (설계에 없는 세부, 2026-10-21 사용자에게 알리고 진행)

1. **시간 폴더:** 승인 범위를 UTC 1시간 폴더로 넓힌다. 끝은 포함하지 않는다 (14:40~16:20 → 14·15·16시, 15:00~16:00 → 15시).
2. **원본:** 폴더 시작 − 여유 시간이 Kafka 보관 기간(72시간) 안이면 Kafka에서 읽는다. 아니면 원본 없음으로 `FAILED`, 재시도하지 않는다. Bronze에서 다시 읽기는 만들지 않는다 (Bronze에 행별 Kafka 위치·시각이 없음, 성철 님 확인 대기).
3. **읽기 여유:** 폴더 앞뒤로 10분씩 더 읽고 이벤트 시각(결제는 `completed_at`, 나머지는 `kafka_timestamp`)으로 걸러 그 폴더에 쓴다.
4. **아직 안 끝난 폴더는 거부:** 폴더 끝 + 여유 시간이 지금보다 늦으면 `FAILED`, 재시도하지 않는다.
5. **바꾸는 줄:** 이번에 다시 읽은 메시지의 줄만 새로 만든 줄로 바꾼다. 다시 읽지 못한 메시지(여유 시간보다 늦게 온 결제, 대상이 아닌 토픽, 그 사이 지워진 메시지)의 옛 줄은 그대로 남긴다. `malformed_events`는 다른 `rule_version` 줄도 남긴다.
6. **교체 순서:** 폴더마다 새 파일을 먼저 쓰고 옛 파일을 지운다. 중간에 멈추면 잠깐 같은 줄이 두 번 있을 수 있지만(뷰가 거름) 줄이 사라지지는 않는다. 다시 돌리면 정리된다.
7. **형식 검사 자리:** 메시지 하나를 받아 결제 줄과 오류 목록만 돌려주는 함수를 넣는다. Kafka 위치·`loaded_at`·`rule_version`은 잡이 붙인다. 그 함수의 규칙 버전이 승인된 `rule_version`과 다르면 `FAILED`, 재시도하지 않는다.
8. **실행 방식:** Spark 없이 파이썬 한 프로세스로 돈다 (한 시간 폴더는 수천 줄). Airflow DAG는 5분마다 poller를 부르고 한 번에 하나만 돈다. 다시 돌릴지와 몇 번까지 돌릴지는 poller가 `reprocess_events`를 보고 정한다.
9. **poller (2026-10-23, 승인 화면 #66과 맞춤):** `APPROVED` 줄의 `source`가 `KAFKA`·`BRONZE`인 요청만 맡는다. 아직 시작하지 않은 요청은 승인 뒤 60분 안일 때만 시작한다. `FAILED`의 `retryable`이 참이거나 중간에 멈췄으면 다시 돌리고, 한 요청은 최대 3번(처음 1번 + 자동 재시도 2번)까지다. 한 번에 승인이 가장 이른 요청 하나만 돌린다. `attempt`는 승인 화면이 정한 요청 단위 번호를 그대로 쓰고, 몇 번째 실행인지는 `STARTED`의 `detail.run`에 쓴다.
10. **`reprocess_events.source`에 `SILVER` (2026-10-23 팀 결정):** Silver 재처리도 같은 표와 같은 단계 이름을 쓰고 `source = SILVER`로 나눈다. 설계 문서와 DDL 설명을 "재처리 경로"로 넓혔다.

## 시작 전 확인 (Claude가 한다)

- 브랜치 `pipelines/gold-b-reprocess`가 `615563c`(#36 최신) 위인지
- Gold B 가상환경 `pipelines/gold_b/.venv`에 `confluent-kafka`, `pyarrow`가 있는지

## 만드는 것

- `pipelines/gold_b/ledger.py`: 원장 공통 도구. 표별 Parquet 스키마(DDL과 같음), 시간 폴더 경로, 메시지 하나의 원장 줄 만들기, 파일 저장소(로컬 폴더·S3)
- `pipelines/gold_b/jobs/reprocess.py`: 재처리 잡 (`run()`), Kafka 다시 읽기, poller (`read_events`, `next_request`)
- `pipelines/gold_b/jobs/README.md`: 동작, 기본값, 부르는 방법
- `pipelines/gold_b/tests/test_reprocess.py`: 가짜 Kafka와 샘플 메시지로 시험
- `pipelines/gold_b/requirements.txt`: 수집기 브랜치와 같은 내용
- `pipelines/gold_b/README.md`에 줄 추가

## 만들지 않는 것

- 형식 검사 코드 (2단계), 결제 지문 (`pipelines/payment_fingerprint.py`, 현지 님과)
- 실행 입구(명령줄): 형식 검사기와 함께 만든다 (`pipelines/gold-b-format-check`)
- `dags/gold_b_reprocess.py`: 재영 님 (Airflow DAG 공급 경로가 `infra/platform/airflow/dags/`라 인프라 영역)
- Bronze에서 다시 읽기, Silver 재처리 연결 (8단계)
- 재처리 검증 시나리오 전체 (9단계)

## 작업 순서

1. 계획 제시 (2026-10-21, 사용자가 바로 개발 요청)
2. 작업 지시서·브랜치 대장 커밋
3. 원장 공통 도구와 재처리 잡 커밋
4. 시험 커밋
5. 로컬 Kafka로 다시 읽기 확인 (Docker)
6. "완료 확인" 실행과 작업 결과 기록

## 완료 확인

- [x] `python -m pytest -q pipelines/gold_b/tests` 통과 (Gold B 가상환경, 37개)
- [x] 최신 `main` 병합 뒤 `pipelines/gold_b/tests` 54개, `pipelines` 139개 통과 (poller 시험 포함)
- [x] #78(수집기)까지 다시 병합한 뒤 `pipelines/gold_b/tests` 77개, `pipelines` 162개 통과 (수집기 시험 23개 포함)
- [x] 같은 입력으로 두 번 돌려 원장이 같은지 (`loaded_at` 제외), 폴더 밖 줄이 그대로인지
- [x] 로컬 Kafka에서 시간으로 위치를 찾아 다시 읽고 폴더가 교체되는지
- [x] 코드·README에 비밀값·실제 주소·버킷 이름이 없는지 (`git grep`)

## README 갱신

- `pipelines/gold_b/jobs/README.md` 새로 만듦
- `pipelines/gold_b/README.md`에 재처리 잡 줄 추가

## 작업 결과 (머지 전에 작성한다)

- **한 줄 요약:** 승인된 시간대의 원장 ①②④를 Kafka에서 다시 읽어 1시간 폴더 단위로 교체하고, 단계마다 `reprocess_events`를 남기는 재처리 잡 본체를 만들었다. 형식 검사(2단계)가 없어서 단독 실행은 아직 안 된다.
- **무엇을 만들었나:**
  - `pipelines/gold_b/ledger.py`: 표 5개의 Parquet 스키마(DDL과 같음), 시간 폴더 경로, 메시지 하나의 원장 줄(`message_rows`: 형식 검사 결과에 Kafka 위치·`loaded_at`·`rule_version`을 붙임), 저장소(로컬 폴더·S3)
  - `pipelines/gold_b/jobs/reprocess.py`: `run()`(시작 전 확인 → `STARTED` → 폴더마다 교체와 `LEDGER_REPLACED` → 실패 시 `FAILED`), `KafkaReader`(시각으로 위치 찾기, [시작, 끝) 읽기, 커밋 없음), `ReprocessError`(`retryable`)
  - `pipelines/gold_b/jobs/README.md`, `pipelines/gold_b/tests/test_reprocess.py`(14개), `pipelines/gold_b/requirements.txt`·`__init__.py`(수집기 브랜치와 같은 내용), 설계 문서 7단계 체크, `pipelines/gold_b/README.md`, `docs/BRANCHES.md` 한 줄
- **왜 그렇게 했나:**
  - 형식 검사는 판정만 하고(결제 업무 칼럼, 오류 목록) 위치·적재 시각·규칙 버전은 공통 함수가 붙인다. 적재 잡도 같은 함수를 써서 "평소 경로와 재처리 경로가 같은 함수"를 지킨다.
  - 다시 읽은 메시지의 줄만 바꾼다: 1시간 폴더를 통째로 비우면 여유 시간보다 늦게 온 결제나 보관 기간으로 지워진 메시지의 줄이 사라진다. 바꿀 줄을 Kafka 위치로 정하면 줄이 사라지지 않고, 같은 입력이면 결과가 같다.
  - 새 파일을 먼저 쓰고 옛 파일을 지운다: 반대로 하면 지운 뒤 멈췄을 때, 그사이 원본이 보관 기간을 넘으면 되살릴 수 없다. 앞선 시도가 남긴 같은 줄은 다시 돌릴 때 하나로 합친다.
  - 원본 확인은 시각으로 한다 (폴더 시작 − 10분이 지금 − 72시간보다 늦으면 Kafka). Kafka의 시간 보관은 그 안의 메시지를 지우지 않는다.
  - 판정 잡(#29)은 `LEDGER_REPLACED`의 `window_start`·`window_end`·`at`을 읽고, 교체로 쌓인 줄을 `loaded_at <= at`으로 가린다. 그래서 새 줄의 `loaded_at`은 폴더 교체를 시작한 시각이고, `actor`는 판정 잡 시험과 같은 `reprocess_job`이다.
  - Spark 없이 파이썬으로 만들었다. 한 시간 폴더는 수천 줄이고, Airflow에서 부르기 쉽다.
- **입력과 출력:** 입력은 `Request`(`request_id`, `window_start`, `window_end`, `rule_version`, `attempt`, `parent_request_id`), Kafka, 형식 검사 함수다. 출력은 원장 3개의 시간 폴더 파일(`part-reprocess-<시각>-<임의값>.parquet`), `reprocess_events/part-<시각>-<단계>-<임의값>.parquet`, 결과(`replaced`: 교체한 폴더 [시작, 끝) 목록)다.
- **확인한 결과:**
  - Gold B 가상환경에서 `pipelines/gold_b/tests` 37개 통과 (테이블 정의 22 + 재처리 15). `git diff --check` 통과.
  - 시험으로 확인한 것: 놓친 메시지와 두 번 쌓인 메시지가 있는 06시 폴더를 교체하면 Kafka 그대로가 되고 05시 폴더 파일은 그대로다. 두 번 돌려도 같다. 다시 읽지 못한 결제 줄과 옛 규칙의 오류 줄은 남고, 새 규칙(PG_C 허용)으로 PG_C 결제가 들어온다. 안 끝난 폴더·보관 기간 밖·규칙 버전 다름·빈 범위는 `FAILED` 한 줄만 남기고 원장과 Kafka를 건드리지 않는다. 06시 교체 중에 멈추면 05시만 `LEDGER_REPLACED`, 06시는 `FAILED`(재시도 가능)이고, 다시 돌리면 같은 줄 없이 정리된다.
  - 로컬 Kafka 실제 확인 (Docker `apache/kafka:3.7.0`): 샘플 메시지를 원래 Kafka 시각으로 넣고(토픽 5개, `reviews.raw`는 일부러 만들지 않음) 06:10~06:30을 재처리했다. 05:50~07:10의 메시지 30건을 읽어 06시 폴더에 결제 11·메시지 28·오류 16줄을 썼고 기대와 같았다. 07:05에 들어온 06:58 결제는 들어가고, 07:30에 들어온 06:59 결제는 빠졌다. `reviews.raw`는 `missing_topics`로 적히고 새로 생기지 않았다. 소비자 그룹이 남지 않았다(커밋 없음). 같은 연결로 한 번 더 돌려도 같았다. 시험 컨테이너를 지우고 Docker Desktop을 다시 껐다.
  - 처음에는 같은 연결로 두 번째 읽기가 시간 초과로 실패했다. 다 읽고 멈춰 둔 파티션이 다시 assign해도 멈춘 채로 남아서였다. assign 뒤에 다시 풀도록 고쳤다 (수집기는 실행마다 새 연결을 만들어 해당 없음).
  - 다른 시각 형식(나노초, UTC 표시)의 파일을 UTC 마이크로초로 맞춰 읽는 것과 S3 경로 처리(숨김 파일·하위 폴더 제외, 버킷 이름을 남기지 않음)는 가짜 S3 클라이언트로 한 번 확인했다.
  - `git grep`: 새 파일에 키·계정 ID·엔드포인트·버킷 이름 없음.
- **알려진 한계·남은 일:**
  - 형식 검사기가 생겨야 실제로 돌릴 수 있다. 실행 입구(명령줄)는 형식 검사기와 함께 만들고, `dags/gold_b_reprocess.py`(5분마다 poller, 한 번에 하나)는 재영 님과 만든다.
  - Bronze 재처리(3일 넘은 구간)는 없다. Bronze에 Kafka 위치·시각을 남기는 방법을 성철 님과 정해야 한다.
  - 고친 뒤 이벤트 시각이 다른 폴더로 옮겨 가는 줄(예: 코드 버그로 `completed_at`을 잘못 읽었던 결제)은 옆 폴더도 승인 범위에 넣어야 한다. 넣지 않으면 그 줄이 빠진다.
  - 실제 S3 쓰기·지우기와 mTLS Kafka는 돌려 보지 않았다.
  - 판정 잡의 `TABLE_SPECS`는 `reprocess_events`를 시간 폴더로, `attempt`를 BIGINT로 가정한다. 테이블 정의(폴더 없음, INT)와 맞춰 달라고 주현 님께 전한다.
  - 판정 잡이 `LEDGER_REPLACED`를 읽는 두 곳에 `source IN ('KAFKA', 'BRONZE')` 조건이 필요하다 (주현 님께 요청함, 설계 문서 팀원 확인 표).
- **보완 (2026-10-21):** 한 메시지에서 같은 필드의 오류는 한 줄만 남긴다 (설계 「중복 제거」: `(topic, kafka_partition, kafka_offset, rule_version, field)`가 같으면 한 번). `ledger.message_rows`에서 하므로 적재 잡도 같다. 시험 1개를 더했다.
- **보완 (2026-10-23): main 병합과 poller**
  - 최신 `main`(#81까지)을 병합했다. 충돌은 `pipelines/gold_b/README.md`, `docs/BRANCHES.md`의 표 줄뿐이었다.
  - 같은 날 #78(수집기)이 머지되어 다시 병합했다. 충돌은 `docs/BRANCHES.md`, `pipelines/gold_b/README.md`, 설계 문서 팀원 확인 표의 줄뿐이었고 양쪽 줄을 모두 남겼다. 머지된 #78의 브랜치 대장 상태, 작업 지시서 상태, 설계 문서 5단계 진행 표시도 정리했다.
  - poller(`read_events`, `next_request`)를 더했다. 규칙은 「정한 기본값」 9번이다. 승인 화면(#66)이 Gold B 요청을 `source = KAFKA`로 쓰고 승인 만료를 60분으로 보는 것에 맞췄다.
  - 승인 화면·판정 잡은 Athena `INSERT INTO`로 `reprocess_events`에 줄을 써서, 파일 이름에 `.parquet`이 없을 수 있다. 원장 저장소의 `files()`가 `.parquet`만 돌려줘서 그대로면 poller가 `APPROVED` 줄을 못 본다. `files(any_name=True)`를 더해 숨김·임시 파일이 아니면 다 읽게 했다 (원장 3개를 교체할 때는 지금처럼 `.parquet`만).
  - `run()`에 `run_number`를 더해 `STARTED`의 `detail.run`에 남긴다. `attempt`는 승인 화면이 정한 요청 단위 번호 그대로다.
  - 설계 문서: `source`를 "재처리 경로"로 넓히고 `SILVER`를 더했다 (2026-10-23 팀 결정). poller 규칙, Silver 재처리 줄, 복구 판단 기준(줄이 쌓인 것만으로 복구로 보지 않고 `VERIFIED`로 판단)을 적었다. Silver 줄의 세부(실패는 `FAILED`, 범위, manifest 경로)와 Silver 복구 조건은 제안으로 표시했다. DDL의 `source`·`attempt` 설명도 맞췄다 (칸은 그대로).
  - 시험 12개를 더했다: 승인 순서와 `SILVER` 제외, 처음·승인 만료·거절·끝남·다시 돌려도 소용없는 실패·일시 실패·시작 뒤 만료 없음·중간에 멈춤·최대 3번, 확장자 없는 Athena 파일 읽기, `run` 번호와 끝난 요청을 다시 고르지 않음. `pipelines/gold_b/tests` 54개, `pipelines` 139개 통과.
