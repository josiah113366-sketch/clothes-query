# 작업 지시서: pipelines/gold-b-reprocess

> 상태: 진행 중 · 브랜치: `pipelines/gold-b-reprocess` (`pipelines/gold-b` 위에서 갈라짐) · 다음 작업: 형식 검사(2단계) 뒤 실행 진입점과 DAG

## 목표

승인된 시간대의 원장 ①②④를 Kafka에서 다시 읽어 시간 폴더 단위로 교체하는 **재처리 잡**(7단계, 필수 ②)의 본체를 만든다. 단계마다 `reprocess_events`에 기록을 남긴다. 메시지를 원장 줄로 바꾸는 형식 검사는 아직 없으므로 끼워 넣는 자리로 두고, 시험은 샘플의 기대 결과로 한다.

## 먼저 읽을 것

- `docs/design/gold-b/README.md` 「재실행·재처리 설계와 검증」, 「⑤ `reprocess_events`」, 7단계 체크리스트
- `pipelines/gold_b/ddl/*.sql` (원장 컬럼, 시간 폴더)
- `agent/detect/job.py` (`main`): 판정 잡이 `LEDGER_REPLACED` 줄의 `window_start`, `window_end`, `at`을 읽는 방식, 재처리로 다시 쌓인 줄을 `loaded_at <= at`으로 거르는 방식

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- #36이 머지 전이라 `pipelines/gold-b` 위에서 갈라졌다. push는 #36 머지 뒤 이 브랜치의 커밋만 `main` 위로 옮긴 다음에 한다.
- 커밋 메시지에 Claude 공동 작성자 줄을 넣지 않는다.

## 정한 기본값 (설계에 없는 세부, 2026-10-21 사용자에게 알리고 진행)

1. **시간 폴더:** 승인 범위를 UTC 1시간 폴더로 넓힌다. 끝은 포함하지 않는다 (14:40~16:20 → 14·15·16시, 15:00~16:00 → 15시).
2. **원본:** 폴더 시작 − 여유 시간이 Kafka 보관 기간(72시간) 안이면 Kafka에서 읽는다. 아니면 원본 없음으로 `FAILED`, 재시도하지 않는다. Bronze에서 다시 읽기는 만들지 않는다 (Bronze에 행별 Kafka 위치·시각이 없음, 성철 님 확인 대기).
3. **읽기 여유:** 폴더 앞뒤로 10분씩 더 읽고 이벤트 시각(결제는 `completed_at`, 나머지는 `kafka_timestamp`)으로 걸러 그 폴더에 쓴다.
4. **아직 안 끝난 폴더는 거부:** 폴더 끝 + 여유 시간이 지금보다 늦으면 `FAILED`, 재시도하지 않는다.
5. **바꾸는 줄:** 이번에 다시 읽은 메시지의 줄만 새로 만든 줄로 바꾼다. 다시 읽지 못한 메시지(여유 시간보다 늦게 온 결제, 대상이 아닌 토픽, 그 사이 지워진 메시지)의 옛 줄은 그대로 남긴다. `malformed_events`는 다른 `rule_version` 줄도 남긴다.
6. **교체 순서:** 폴더마다 새 파일을 먼저 쓰고 옛 파일을 지운다. 중간에 멈추면 잠깐 같은 줄이 두 번 있을 수 있지만(뷰가 거름) 줄이 사라지지는 않는다. 다시 돌리면 정리된다.
7. **형식 검사 자리:** 메시지 하나를 받아 결제 줄과 오류 목록만 돌려주는 함수를 넣는다. Kafka 위치·`loaded_at`·`rule_version`은 잡이 붙인다. 그 함수의 규칙 버전이 승인된 `rule_version`과 다르면 `FAILED`, 재시도하지 않는다.
8. **실행 방식:** Spark 없이 파이썬 한 프로세스로 돈다 (한 시간 폴더는 수천 줄). 한 번에 하나씩 돌리기와 재시도 2번은 Airflow DAG가 맡는다.

## 시작 전 확인 (Claude가 한다)

- 브랜치 `pipelines/gold-b-reprocess`가 `615563c`(#36 최신) 위인지
- Gold B 가상환경 `pipelines/gold_b/.venv`에 `confluent-kafka`, `pyarrow`가 있는지

## 만드는 것

- `pipelines/gold_b/ledger.py`: 원장 공통 도구. 표별 Parquet 스키마(DDL과 같음), 시간 폴더 경로, 메시지 하나의 원장 줄 만들기, 파일 저장소(로컬 폴더·S3)
- `pipelines/gold_b/jobs/reprocess.py`: 재처리 잡 (`run()`), Kafka 다시 읽기
- `pipelines/gold_b/jobs/README.md`: 동작, 기본값, 부르는 방법
- `pipelines/gold_b/tests/test_reprocess.py`: 가짜 Kafka와 샘플 메시지로 시험
- `pipelines/gold_b/requirements.txt`: 수집기 브랜치와 같은 내용
- `pipelines/gold_b/README.md`에 줄 추가

## 만들지 않는 것

- 형식 검사 코드 (2단계), 결제 지문 (`pipelines/payment_fingerprint.py`, 현지 님과)
- 실행 진입점(명령줄)과 `dags/gold_b_reprocess.py` (형식 검사가 생긴 뒤, 재영 님과)
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

- [ ] `python -m pytest -q pipelines/gold_b/tests` 통과 (Gold B 가상환경)
- [ ] 같은 입력으로 두 번 돌려 원장이 같은지 (`loaded_at` 제외), 폴더 밖 줄이 그대로인지
- [ ] 로컬 Kafka에서 시간으로 위치를 찾아 다시 읽고 폴더가 교체되는지
- [ ] 코드·README에 비밀값·실제 주소·버킷 이름이 없는지 (`git grep`)

## README 갱신

- `pipelines/gold_b/jobs/README.md` 새로 만듦
- `pipelines/gold_b/README.md`에 재처리 잡 줄 추가

## 작업 결과 (머지 전에 작성한다)
