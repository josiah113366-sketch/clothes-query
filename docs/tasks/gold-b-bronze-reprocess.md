# 작업 지시서: pipelines/gold-b-bronze-reprocess

> 상태: 검토 대기 · 브랜치: `pipelines/gold-b-bronze-reprocess` (최신 `main` `6c00ddc` 위의 `pipelines/gold-b-dags` 끝에서 만듦. DAG에 Bronze 위치 설정을 더해야 해서 DAG PR 다음에 머지) · 다음 작업: PR (사용자, DAG PR 머지 뒤), `bronze_v2/` 읽기 권한·실행 설정 (재영 님)

## 목표

Kafka 보관 기간(7일)이 지난 시간대도 재처리할 수 있게 한다. 그 시간 폴더는 Bronze v2 파일(`connectors/bronze-s3-sink-v2.yaml`, #89)에서 메시지를 다시 만들어 지금의 메시지 단위 재처리(#99)에 넣는다. 설계 결정은 "재처리는 Kafka 보관 기간 안이면 Kafka, 넘으면 Bronze"다 (설계 문서 맨 위 표의 입력 줄). 지금은 보관 기간 밖 요청을 "Bronze 재처리는 아직 없음"으로 거부한다.

## 먼저 읽을 것

- `connectors/bronze-s3-sink-v2.yaml`, `connectors/README.md` 「Bronze v2」: 파일 경로, 줄 모양(메시지 값 + `kafka_topic`·`kafka_partition`·`kafka_offset`·`kafka_timestamp`·`kafka_timestamp_type`), 같은 메시지가 두 번 들어갈 수 있음
- `pipelines/gold_b/jobs/reprocess.py`, `pipelines/gold_b/jobs/README.md` (메시지 단위 재처리)
- `docs/design/gold-b/README.md` 「재실행·재처리 설계와 검증」, 「⑤ reprocess_events」의 `source`

## 정한 기본값 (설계에 없는 세부, 2026-10-24 사용자 "3번 해줘")

1. **원본 고르기:** 승인 범위의 시간 폴더마다 정한다. 폴더 시작 - 여유 10분이 지금 - 7일보다 앞이면 Bronze, 아니면 Kafka (지금 거부하는 조건과 같은 경계). 한 요청에 둘이 섞여도 된다. 승인 화면은 바꾸지 않는다 (R1·R4·R5 요청의 `source`는 그대로 `KAFKA`).
2. **Bronze 위치:** 환경변수 `GOLD_B_BRONZE_ROOT` (예: `s3://<버킷>/bronze_v2`). 없으면 지금처럼 보관 기간 밖 요청을 시작 전에 거부한다.
3. **읽기:** 시간 폴더 날짜(UTC)의 `<토픽>/year=YYYY/month=MM/day=dd/` 폴더에서 `.json` 파일을 다 읽고, `kafka_timestamp`가 그 시간 폴더 안인 줄만 쓴다. Bronze v2 토픽은 5개다. `reviews.raw`는 Bronze에 없어서 그 폴더의 `missing_topics`로 남긴다.
4. **메시지 되돌리기:** 줄에서 `kafka_*` 5칸을 떼어 값을 다시 JSON으로 만들고, 위치·시각은 그 칸에서 읽는다. 값의 칸 이름은 Kafka와 같다 (`__op`·`__source_ts_ms`, Sink는 이름을 바꾸지 않음). 키는 Bronze에 없어 비운다 (형식 검사기는 키를 보지 않음).
5. **같은 메시지 두 번:** Sink가 다시 켜지면 같은 메시지가 두 파일에 있을 수 있다. 위치(토픽, 파티션, offset)로 하나만 남긴다.
6. **Bronze에 없는 메시지:** 빈 값과 JSON 객체가 아닌 값은 Sink가 쓰지 않는다. 그 메시지는 대상이 아니어서 옛 줄이 그대로 남는다 (메시지 단위 재처리라 지우지 않음).
7. **원본이 없을 때:** 필요한 날짜에 Bronze 토픽 5개 모두 파일이 없으면 재시도 없이 `FAILED`. Kafka 위치·시각 칸이 없거나 틀린 줄(예: 옛 `bronze/` 형식)도 재시도 없이 `FAILED`.
8. **기록:** `LEDGER_REPLACED`의 `source`는 그 폴더를 다시 읽은 곳(`BRONZE`·`KAFKA`)이다. 승인 범위 밖 결제 시각 폴더와 `STARTED`·`FAILED`는 승인 범위가 모두 Bronze면 `BRONZE`, 아니면 `KAFKA`. `STARTED` detail에 Bronze로 읽은 폴더 목록(`bronze_folders`)을 남긴다.
9. **DAG:** 실행 설정에 선택 키 `bronze_root`를 더해 재처리 Pod에 `GOLD_B_BRONZE_ROOT`로 준다. `s3://<버킷>/<경로>`가 아니면 확인 태스크에서 멈춘다.
10. **시험:** Bronze v2 형식의 샘플 파일을 만들어 Bronze만 읽기, Kafka·Bronze 섞기, 같은 줄 두 번, 날짜 폴더 없음, 옛 형식 줄, Bronze 위치 없음을 본다. 실제 형식 검사기로 Kafka로 다시 만든 결과와 Bronze로 다시 만든 결과가 같은지 본다.

## 만들지 않는 것

- 재처리 실행 신원의 `bronze_v2/` 읽기 권한, 실행 설정 공급 (재영 님)
- 승인 화면의 보관 기간 경고 바꾸기 (주현 님)
- 옛 `bronze/` 파일 읽기 (줄마다 Kafka 위치·시각이 없어서 원장 줄을 찾을 수 없음)
- 실제 S3 Bronze로 돌려 보기 (배포 뒤)

## 작업 순서

1. 지시서와 브랜치 대장 (2026-10-24)
2. Bronze 읽기, 폴더마다 원본 고르기, 기록
3. 시험
4. DAG 설정과 문서
5. "완료 확인" 실행과 작업 결과 기록

## 완료 확인

- [x] `python -m pytest -q pipelines/gold_b/tests` 통과 (237개, 로컬 Python 3.12)
- [x] Bronze 시험 (Bronze v2 형식 샘플 파일, 9개)
- [x] `git diff --check`

## 작업 결과 (머지 전에 작성한다)

### 만든 것

- `pipelines/gold_b/jobs/reprocess.py`
  - `from_bronze`: 승인 범위의 시간 폴더 중 Kafka 보관 기간이 지난 폴더 (폴더 시작 - 10분 < 지금 - 7일). `check_request`는 Bronze 위치가 없을 때만 이런 요청을 거부한다.
  - `BronzeReader`: Bronze v2의 날짜 폴더 `.json` 파일을 읽어 `kafka_*` 5칸을 떼고 메시지를 되돌린다. `kafka_timestamp`로 시간 폴더를 거르고, 위치마다 하나만 남긴다. 그 날 파일이 하나도 없거나 위치·시각 칸이 없는 줄은 재시도 없이 멈춘다 (줄 내용은 로그에 남기지 않음).
  - `read_messages`: 보관 기간이 지난 폴더는 Bronze, 나머지는 Kafka에서 읽고 합친다. 두 곳에 다 든 메시지(시각이 위치 순서와 다른 것)는 하나만.
  - `run(bronze=...)`: `LEDGER_REPLACED`의 `source`는 그 폴더를 다시 읽은 곳, 범위 밖 폴더·`STARTED`·`FAILED`는 승인 폴더가 모두 Bronze면 `BRONZE`, 아니면 `KAFKA`. `STARTED` detail에 `bronze_folders`. 원본에 없는 토픽(`missing_topics`)은 폴더마다 (Bronze 폴더는 `reviews.raw`).
  - 실행 입구: `GOLD_B_BRONZE_ROOT`가 있으면 `BronzeReader`를 만든다.
- `pipelines/gold_b/ledger.py`: 저장소에 `read_bytes` (원장이 아닌 파일을 그대로 읽기, 로컬·S3)
- `infra/platform/airflow/dags/gold_b.py`: 실행 설정 선택 키 `bronze_root` → 재처리 Pod의 `GOLD_B_BRONZE_ROOT`. `s3://<버킷>/<경로>`가 아니면 재처리 확인 태스크만 멈춘다. 재처리용 인자 이름을 `kafka`에서 `reprocess`로 바꿨다 (Kafka·Bronze 설정 모두 재처리만 씀).
- 시험: `tests/test_bronze_reprocess.py` 9개, `tests/test_dags.py`에 2개 더함 (Bronze 위치 전달, 재처리만 확인)
- 문서: 잡 설명 「Bronze에서 읽기」와 `reprocess_events` 표의 `source`, 환경변수 표, DAG 설명의 실행 설정·준비할 것, Gold B README 표, 설계 문서(Bronze에서 읽기·다시 만들 수 없는 것, 성철 님 확인 완료, 재영 님 배포 항목, 7단계 체크리스트)
- DAG 브랜치에 설계 문서 「자동 재시도」 줄 수정을 커밋하고 이 브랜치에 병합했다 (DAG PR에 들어갈 내용이라).

### 왜

- 설계 결정 "보관 기간 안이면 Kafka, 넘으면 Bronze"의 Bronze 쪽이 없어서, 늦게 발견한 구간(7일 넘음)은 재처리할 수 없었다. Bronze v2(#89)가 줄마다 Kafka 위치·시각을 남기게 되어 원장의 같은 줄을 찾아 바꿀 수 있다.
- 폴더마다 원본을 고르면 승인 화면을 바꾸지 않아도 된다 (요청 `source`는 그대로 `KAFKA`, 잡이 고름).
- 메시지 단위 재처리라 Bronze에 없는 메시지(깨진 원본, `reviews.raw`)는 대상이 아니어서 지워지지 않는다.

### 확인한 결과

- `python -m pytest -q pipelines/gold_b/tests`: 237개 통과 (로컬 Python 3.12)
- Bronze 시험 9개: Bronze만으로 06시 폴더 교체(놓친 줄 채움, 두 번 쌓인 줄 하나로, Bronze에 없는 메시지의 옛 줄 남음, Kafka 안 읽음), 보관 기간 경계에서 05시 Bronze·06시 Kafka와 두 곳에 다 든 메시지 하나만, 실제 형식 검사기로 Kafka·Bronze 결과가 같음(값의 칸 순서를 거꾸로 써도 같음), Sink 재시작으로 같은 줄 두 번, 그 날 파일 없음·옛 형식 줄은 원장을 건드리지 않고 재시도 없이 멈춤, 경계 시각, 실행 입구의 `GOLD_B_BRONZE_ROOT` 있음·없음, S3 경로(`bronze_v2/<토픽>/year=/month=/day=/`)
- 코드를 일부러 틀리게 바꾼 12가지(Bronze 안 중복 제거 빠짐, Kafka·Bronze 사이 중복 제거 빠짐, `kafka_*` 칸 안 뗌, 경계 `<`를 `<=`로, 폴더 `source` 고정, 시간 거르기 빠짐, 원본 없음 확인 빠짐, Bronze가 있어도 거부, 실행 `source` 고정, `bronze_folders` 빠짐, `missing_topics` 빠짐, 실행 입구가 Bronze 위치 무시)를 모두 시험이 잡았다.
- `git diff --check`: 문제 없음
- 실제 S3 Bronze v2로는 돌려 보지 못했다 (권한·실행 설정 뒤).

### 다음 할 일

- PR 순서: DAG PR(`pipelines/gold-b-dags`)을 먼저 머지한 뒤 이 PR. 이 브랜치는 DAG 브랜치 위에서 만들어서, DAG PR이 머지되면 이 PR에는 Bronze 변경만 보인다.
- 재영 님: 재처리 실행 신원에 S3 `bronze_v2/` 읽기(목록 포함), 실행 설정 `bronze_root`. 그 뒤 7일이 지난 시간대 하나로 실제 재처리를 확인한다.
- 주현 님 (선택): 승인 화면의 `OUTSIDE_KAFKA_RETENTION` 경고는 "Kafka로 다시 만들 수 없을 수 있다"는 뜻이라 그대로 맞지만, 이제 Gold B는 Bronze로 다시 만든다는 안내를 더할 수 있다.
