# 작업 지시서: pipelines/gold-b-bronze-reprocess

> 상태: 진행 중 · 브랜치: `pipelines/gold-b-bronze-reprocess` (최신 `main` `6c00ddc` 위의 `pipelines/gold-b-dags` 끝에서 만듦. DAG에 Bronze 위치 설정을 더해야 해서 DAG PR 다음에 머지) · 다음 작업: 구현 (2026-10-24 사용자: "3번 해줘")

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

- [ ] `python -m pytest -q pipelines/gold_b/tests` 통과
- [ ] Bronze 시험 (Bronze v2 형식 샘플 파일)
- [ ] `git diff --check`

## 작업 결과 (머지 전에 작성한다)
