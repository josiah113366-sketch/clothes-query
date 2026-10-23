# connectors/

Debezium(Kafka Connect) 커넥터 설정이다. 로컬 구성(`simulator/docker-compose.yml`의 프로필 `cdc`)과 이후 RDS 구성이 같은 파일을 기준으로 한다.

| 파일 | 내용 |
|---|---|
| `member-source.json` | `public.members`를 읽어 토픽 `members-events`로 보내는 커넥터. Kafka Connect REST에 그대로 보내는 **평평한 설정 묶음**(`name` 포함) |

| `member-s3-sink.json` | 토픽 `members-events`를 S3의 `bronze/`에 JSON Lines 파일로 쌓는 S3 Sink 커넥터 (Confluent S3 Sink 12.1.13) |
| `cdc-source.yaml` | **EKS 업무용.** RDS의 `members`·`orders`·`order_items`·`payments`를 토픽 4개로 보내는 Debezium 커넥터 (Strimzi `KafkaConnector`) |
| `bronze-s3-sink.yaml` | **EKS 업무용.** 업무 토픽 5개를 `clothes-query-datalake`의 `bronze/`에 쌓는 S3 Sink (Strimzi `KafkaConnector`) |
| `bronze-s3-sink-v2.yaml` | **EKS 업무용.** 위와 같고 `bronze_v2/`에 쓰며, 줄마다 Kafka 위치·시각을 넣는다. 아래 "Bronze v2" |
| `cdc-prepare.sql` | **EKS 업무용.** RDS에 CDC 전용 계정 `clothes_cdc`와 publication `cdc_pub`을 만드는 SQL. 사용자가 마스터로 실행한다 |

`member-source.json`의 등록과 상태 확인, 초기화는 `sim cdc setup` / `status` / `reset`으로 한다 (`simulator/README.md`의 "로컬 CDC").

## 값과 이유

| 키 | 값 | 이유 |
|---|---|---|
| `table.include.list` | `public.members` | 하나만. `members_archive`는 대상이 아니다 |
| `column.include.list` | 10개 컬럼 | **PII를 처음부터 내보내지 않는다.** `exclude.list`는 쓰지 않는다. 새 컬럼이 생겨도 자동으로 나가지 않게 하려는 것이다 |
| `database.password` | `${env:CDC_DB_PASSWORD}` | 비밀번호를 파일에 쓰지 않는다. Connect 컨테이너 환경 변수에서 읽는다 |
| `plugin.name` | `pgoutput` | Postgres 기본 논리 복제 방식 |
| `slot.name` / `publication.name` | `member_slot` / `member_pub` | `publication.autocreate.mode=filtered`라서 publication에는 `members`만 들어간다 |
| `snapshot.mode` | `initial` | 저장된 offset이 없을 때만 스냅샷한다. 스냅샷 행은 `op=r` |
| `tombstones.on.delete` | `false` | 삭제 이벤트는 없다. `unwrap`의 `delete.handling.mode=drop`으로 `d`는 토픽에 보내지 않는다 |
| `heartbeat.interval.ms` | `10000` | 트래픽이 적을 때도 슬롯이 앞으로 가서 WAL이 쌓이지 않는다 |
| `key/value.converter` | `JsonConverter`, `schemas.enable=false` | 스키마 정보 없이 값만 있는 JSON |
| `transforms.unwrap` | `ExtractNewRecordState` | Debezium 봉투를 벗기고 `after`의 값을 펼친다. `__op`, `__source_ts_ms`, `__source_snapshot`을 붙인다 |
| `predicates.isData` | 데이터 토픽에만 `unwrap` 적용 | 하트비트 메시지는 건드리지 않는다 |
| `transforms.route` | `cdc.public.members` → `members-events` | 토픽 이름 |
| `topic.creation.default.*` | 파티션 3, 복제 1 | 토픽 자동 생성 |

## 바꿀 때 주의

- **컬럼을 바꾸려면 스냅샷 전에** 바꾼다. 이미 스냅샷했다면 `sim cdc reset` 후 다시 `sim cdc setup`을 한다. 설정만 바꿔 다시 등록하면 이미 토픽에 들어간 데이터와 어긋난다.
- 같은 이름의 커넥터가 이미 있으면 `setup`은 설정을 덮어쓰지 않는다.

## RDS로 옮길 때 바뀌는 값

- `database.hostname`, `database.port`: RDS 엔드포인트. **레포에 적지 않고** 배포 때 주입한다.
- `database.user`, 비밀번호: `rds_replication` 권한을 가진 전용 계정. 비밀번호는 지금처럼 파일에 적지 않는 방식(Secrets Manager 등)으로 준다.
- 슬롯과 publication은 인프라가 미리 만들 수 있다.
- `key/value.converter`, `transforms`, `column.include.list`는 그대로 쓴다.

## S3 Sink (`member-s3-sink.json`)

등록과 상태 확인, 검증, 초기화는 `sim sink setup` / `status` / `verify` / `reset`으로 한다 (`simulator/README.md`의 "S3 Sink").

| 키 | 값 | 이유 |
|---|---|---|
| `topics` | `members-events` | source 커넥터가 내보내는 토픽과 같아야 한다 |
| `s3.bucket.name` / `s3.region` | `${env:S3_BUCKET}` / `${env:AWS_REGION}` | **버킷 이름을 레포에 적지 않는다.** Connect 컨테이너 환경 변수에서 읽는다 |
| (자격 증명) | JSON에 없음 | Connect 컨테이너의 `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` 환경 변수(기본 자격 증명 체인)를 쓴다. 키 값은 `simulator/.env`에만 둔다 |
| `topics.dir` | `bronze` | 객체 경로 접두사 |
| `format.class` | `JsonFormat` | JSON Lines (한 줄에 JSON 하나) |
| `key/value.converter` | `JsonConverter`, `schemas.enable=false` | 토픽 메시지가 스키마 없는 JSON이다 |
| `schema.compatibility` | `NONE` | 스키마가 없다 |
| `partitioner.class` / `path.format` | `TimeBasedPartitioner` / `'year'=YYYY/'month'=MM/'day'=dd` | Hive 방식 일별 폴더 (Athena/Glue가 `year`, `month`, `day` 파티션으로 인식한다) |
| `partition.duration.ms` / `timezone` / `locale` | `86400000` / `UTC` / `en-US` | 하루 단위, UTC 기준 |
| `timestamp.extractor` | `Record` | **Kafka 레코드 시각(수집 시각)** 기준이다. 가입일이 아니다. 다시 읽어도 같은 폴더에 들어간다 |
| `flush.size` | `10000` | 파티션 하나의 파일이 이만큼 쌓이면 시간이 안 돼도 끊는다. 안전장치이고 평소에는 시간 기준으로 끊긴다 |
| `rotate.schedule.interval.ms` | `900000` | 트래픽이 적어도 15분(벽시계)마다 파일을 끊는다. 하루 5,000명이면 파티션 3개 기준 하루 약 288개 파일, 파일당 약 17건이다. 로컬에서 바로 확인하려면 임시로 `30000`으로 바꾼다 |
| `s3.compression.type` | `none` | |

객체 경로: `bronze/members-events/year=YYYY/month=MM/day=DD/members-events+<파티션>+<시작offset>.json`

- **at-least-once다.** 재시작이나 오류 뒤에 같은 메시지가 파일에 두 번 들어갈 수 있다. Silver에서 `member_id` 기준으로 중복을 제거한다.
- S3에 PII가 가지 않는 것은 **source의 `column.include.list`가 지킨다.** 이 커넥터에는 컬럼을 거르는 설정이 없다.
- `sim sink reset` 뒤에 다시 `setup`하면 토픽을 처음부터 다시 읽어 **같은 데이터가 S3에 한 번 더 쌓인다.**

### IAM 정책 예시 (사용자가 만든다)

`<버킷>`을 실제 버킷 이름으로 바꾼다. 쓰기는 `bronze/*`로만 제한한다.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListAndLocate",
      "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetBucketLocation", "s3:ListBucketMultipartUploads"],
      "Resource": "arn:aws:s3:::<버킷>"
    },
    {
      "Sid": "WriteBronze",
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"],
      "Resource": "arn:aws:s3:::<버킷>/bronze/*"
    }
  ]
}
```

`sim sink status`가 버킷의 공개 차단 설정을 조회하려면 `s3:GetBucketPublicAccessBlock`이 더 필요하다. 없어도 `status`는 "확인 못 함"이라고만 한다.

### 클라우드로 옮길 때 바뀌는 값

- 자격 증명: 키 대신 역할(IRSA 등)을 쓴다. 환경 변수 키는 쓰지 않는다.
- `flush.size`, `rotate.schedule.interval.ms`: 가입자 수와 지연 허용 시간에 맞춰 다시 정한다 (파일이 너무 작으면 작은 파일이 많아진다).
- `topics`, `format.class`, `path.format`, `timezone`, `timestamp.extractor`는 그대로 쓴다.

## EKS 업무 CDC (`cdc-source.yaml`, `bronze-s3-sink.yaml`, `cdc-prepare.sql`)

실제 RDS에서 EKS Kafka를 거쳐 S3 Bronze로 가는 업무 경로다. 적용 순서와 명령은 `infra/platform/kafka/cdc-orders/README.md`, 결정과 확인 결과는 `docs/tasks/sim-cdc-orders.md`에 있다. 위의 `member-*.json`은 로컬(`sim cdc`, `sim sink`)용으로 그대로 둔다.

### 토픽 계약

| 토픽 | 내용 | 메시지 키 | 이유 |
|---|---|---|---|
| `clickstream` | `view`, `cart_add` (`event_type`으로 구분). 시뮬레이터가 직접 발행 | `session_id` | 같은 방문의 `view` → `cart_add` 순서를 한 파티션 안에서 지킨다 |
| `members-events` | `members` CDC | `member_id` | 같은 회원의 가입 → 탈퇴 순서 |
| `orders` | `orders` CDC | `order_id` | 같은 주문의 상태 변경 순서 |
| `order-items` | `order_items` CDC | `order_item_id` | 기본 키. 주문 단위 조립은 Silver에서 한다 |
| `payments` | `payments` CDC | `payment_id` | 기본 키. 시도 순서는 `attempt_no`·`requested_at`으로 맞춘다 |

모두 파티션 3, 복제 1(브로커 1대), 보관 72시간이다. 토픽은 Helm values(`infra/platform/kafka/cdc-orders-values.yaml`)가 미리 만든다. Connect는 토픽을 자동으로 만들지 않는다(`topic.creation.enable: false`). CDC 메시지 키는 `{"order_id":"..."}`처럼 기본 키 하나짜리 JSON이다.

### 로컬 `member-*.json`과 다른 점

| 항목 | 로컬 | EKS | 이유 |
|---|---|---|---|
| 형식 | Connect REST JSON | Strimzi `KafkaConnector` CR (`kubectl apply`) | Connect가 `use-connector-resources`로 CR만 받는다 |
| DB 계정 | `sim`(테이블 소유자) | `clothes_cdc`(전용) | 인프라 chart가 마스터 계정 연결을 막는다. 계정이 새도 정해진 테이블·컬럼만 읽힌다 |
| DB 주소·비밀번호 | `${env:...}` | `${directory:/mnt/cdc-database:<키>}` (K8s Secret `cdc-database`) | 주소와 비밀번호가 Git에 들어가지 않는다 |
| TLS | 없음 | `verify-full`, RDS CA(`rds-ca` Secret) | RDS가 `rds.force_ssl=1`이다 |
| publication | Debezium이 만든다(`filtered`) | 마스터가 미리 만든다(`disabled`) | publication은 테이블 소유자만 만들 수 있다 |
| snapshot 잠금 | 기본 | `snapshot.locking.mode: none` | 회원 테이블은 컬럼 단위 `SELECT` 권한뿐이라 `LOCK TABLE`을 못 한다. slot을 만들 때의 exported snapshot이 일관성을 지킨다 |
| 토픽 이름 | `RegexRouter` 1개 | 3개 (`members` → `members-events`, `order_items` → `order-items`, `orders`·`payments`는 그대로) | 계약 이름과 Debezium 기본 이름(`cdc.public.<테이블>`)이 다르다 |
| heartbeat 토픽 | `__debezium-heartbeat.cdc` | `debezium-heartbeat.cdc` (`topic.heartbeat.prefix`) | chart의 토픽 이름 규칙이 `_`로 시작하는 이름을 받지 않는다 |
| WAL 확인 위치 | (로컬은 계속 쓰기가 있어 문제 없음) | `heartbeat.action.query`: 10초마다 `pg_logical_emit_message(true, 'heartbeat', …)`(트랜잭션 메시지여야 COMMIT 위치가 움직인다), 그 메시지 이벤트(`cdc.message`)는 `dropMessage`(Filter) 변환이 버린다 | 업무 테이블에 변경이 없으면 slot 위치가 멈춰 RDS WAL이 5분마다 64MB씩 쌓인다(실측). 테이블에 쓰지 않고 WAL에 논리 메시지만 남겨 위치를 옮긴다. 메시지는 Kafka로 보내지 않아 Bronze에 영향이 없다. `message.prefix.exclude.list`로 버리면 위치가 기록되지 않아 slot이 움직이지 않는다(실측) |
| S3 자격 증명 | `.env`의 키 | Pod Identity (ServiceAccount `clothes-query-dev-connect-connect`, `bronze/`만) | 키를 이미지·Secret에 넣지 않는다 |
| Sink 키 변환기 | JSON | 문자열(`StringConverter`) | `clickstream` 키는 JSON이 아닌 `session_id` 문자열이다. 키는 파일에 쓰지 않는다 |
| `s3.part.size` | 기본(25MB) | 5MB(최소값) | 열린 파티션 15개마다 버퍼를 잡는다. 25MB면 Connect 힙(512MB)이 모자란다 |

같은 점: 회원 10컬럼(`column.include.list`), 관리 컬럼 `__op`·`__source_ts_ms`·`__source_snapshot`, 삭제 이벤트를 보내지 않음(`tombstones.on.delete=false`, `delete.handling.mode=drop`), S3 경로 `bronze/<토픽>/year=YYYY/month=MM/day=DD/<토픽>+<파티션>+<시작offset>.json`(UTC, 레코드 시각 기준), 15분 또는 10,000건마다 파일 끊기.

### Bronze v2 (`bronze-s3-sink-v2.yaml`)

`bronze/`의 줄에는 Kafka 위치(offset)와 Kafka 시각이 없다. 파일 이름에 첫 offset만 있고, 빈 값을 건너뛰거나(`behavior.on.null.values: ignore`) 재시작으로 같은 메시지가 두 파일에 들어갈 수 있어 줄 번호로도 계산할 수 없다. 그래서 Gold B 재처리가 원장의 같은 줄을 찾지 못해 두 번 쌓고, Kafka 시각의 시간 폴더(dt, hour)도 정하지 못한다(Gold B 담당 요청, 2026-10-23).

v2는 `bronze-s3-sink`와 설정이 같고 두 가지만 다르다(`infra/platform/kafka/verify/check.py`가 확인한다).

| 값 | v2 | 이유 |
|---|---|---|
| `topics.dir` | `bronze_v2` | 옛 파일과 섞이지 않게 경로를 나눈다. 경로는 `bronze_v2/<토픽>/year=YYYY/month=MM/day=DD/<토픽>+<파티션>+<시작offset>.json` |
| `transforms` | `InsertField$Value`: `kafka_topic`, `kafka_partition`, `kafka_offset`, `__kafka_timestamp` | 줄마다 Kafka 위치·시각(ms, UTC). 이름은 Gold B 담당이 정했다 |

- 이름이 새것이라 컨슈머 그룹 `connect-bronze-s3-sink-v2`도 새것이다. Sink는 처음 읽는 그룹을 가장 오래된 메시지부터 읽으므로 **Kafka에 남은 메시지를 처음부터 다시 쓴다**(offset을 되감는 작업 없음). 다 따라잡으면 옛 Sink처럼 끝에서 따라간다.
- Kafka 보관 기간보다 오래돼 이미 지워진 메시지는 v2에 없다. 그런 날짜는 옛 `bronze/`에만 있다.
- 값이 JSON 객체가 아닌 메시지가 오면 이 변환이 실패해 작업이 멈춘다. 업무 토픽 5개는 모두 객체다.
- 따라잡는 동안 두 Sink가 함께 돈다. 경로와 그룹이 달라 서로 영향이 없다. 진행은 Kafka UI → Consumers의 `connect-bronze-s3-sink-v2` lag로 본다.
- 읽는 쪽(Silver, Gold B, Athena 테이블)이 `bronze_v2/`로 옮긴 뒤 옛 Sink를 지운다. Gold B 지연 수집기는 `GOLD_B_SINK_CONNECTOR=bronze-s3-sink-v2`로 바꾼다. 옛 `bronze/` 객체는 지우지 않는다.
- 적용 순서: `infra/platform/kafka/cdc-orders/README.md`의 "6. Bronze v2".

### PII를 두 겹으로 막는다

1. `cdc-source.yaml`의 `column.include.list`: 회원은 10컬럼만 내보낸다.
2. `cdc-prepare.sql`의 컬럼 단위 `GRANT SELECT`: 커넥터 설정이 틀려도 snapshot에서 PII 컬럼을 읽지 못한다.

`members_archive`와 `product_*`는 publication에도 `table.include.list`에도 없다. 이 규칙은 `infra/platform/kafka/verify/check.py`가 검사한다(회원 컬럼이 로컬 설정과 같은지, 주문 컬럼이 `004_orders.sql`과 같은지, 토픽 이름이 계약과 같은지, 비밀값이 없는지).
