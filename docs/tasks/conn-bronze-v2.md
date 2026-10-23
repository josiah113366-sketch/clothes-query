# 작업 지시서: conn/bronze-v2

> 상태: 진행 중 · 브랜치: `conn/bronze-v2` (최신 `main`) · 요청: Gold B 담당(2026-10-23)

## 목표

Bronze 줄마다 Kafka 위치(토픽·파티션·offset)와 Kafka 시각을 남긴다. 지금 `bronze/`에는 둘 다 없어 Gold B 재처리가 원장의 같은 줄을 찾지 못해 두 번 쌓고(② 메시지 수·④ 오류 수 2배), Kafka 시각의 시간 폴더(dt, hour)도 정하지 못한다. 파일 이름의 첫 offset + 줄 번호로는 계산할 수 없다(빈 값 건너뛰기, 재시작 때 같은 메시지가 두 파일에 들어감).

## 이번 작업의 특례 (사용자 결정, 2026-10-23, 다른 문서보다 우선)

- **한 브랜치에 `connectors/`와 `infra/`를 같이 담는다.** 관련 담당 모두 동의했다(PR 한 영역 규칙의 예외)
- 기존에 쌓인 것도 다시 만든다: **새 Sink로 Kafka에 남은 메시지를 처음부터** 쓴다. 기존 Sink의 offset을 되감지 않는다(옛 파일과 섞임)
- 경로 `bronze_v2/<토픽>/`(최상위). 필드는 `docs/contracts/README.md` 8절 그대로: `kafka_topic`, `kafka_partition`, `kafka_offset`, `kafka_timestamp`(시간대 포함 ISO), `kafka_timestamp_type`(`CreateTime`). Gold B 담당의 처음 안(`__kafka_timestamp`, ms)은 계약·Silver 코드·Gold B 원장 이름과 맞춰 대체했다
- 5개 토픽 모두(clickstream 포함). 파일 전환 15분 → 5분은 이번에 하지 않는다
- 시뮬레이터는 멈추지 않는다

## 만드는 것

- `connectors/bronze-s3-sink-v2.yaml`: 기존 Sink + `topics.dir: bronze_v2` + `InsertField$Value`·`TimestampConverter$Value`·고정값 `InsertField$Value`
- `infra/platform/kafka/cdc-orders-values.yaml`: Connect·Kafka UI의 그룹 ACL `connect-bronze-s3-sink-v2`, lag exporter 정규식
- `infra/stacks/workload-access/deployment.auto.tfvars.json`, `cdc-orders/workload-access.tfvars.example`: Connect 역할에 `bronze_v2/` 쓰기
- `infra/platform/kafka/verify/check.py`: v2가 기존 Sink와 경로·변환만 다른지 확인
- 문서: `connectors/README.md` "Bronze v2", `cdc-orders/README.md` "6. Bronze v2"(적용 순서)

## 만들지 않는 것

- 옛 Sink 삭제, 읽는 쪽(Silver, Gold B, Athena, Spark handoff 예시)의 경로 변경. 각 담당이 v2를 확인한 뒤 옮긴다
- Kafka 보관 기간 변경(values는 72시간 그대로. 적용 전 클러스터 값을 확인한다)

## 완료 확인

- [ ] `infra/platform/kafka/verify/check.py` 통과
- [ ] workload-access plan: 정책 1개 수정만 (사용자)
- [ ] Helm upgrade: 그룹 ACL·UI·lag exporter만 바뀜 (사용자)
- [ ] v2 등록 후 lag가 0 근처, `bronze_v2/` 줄에 칸 4개, 첫 offset이 Kafka 가장 오래된 offset과 같음 (사용자)

## 작업 결과

(머지 전에 채운다)
