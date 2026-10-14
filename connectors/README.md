# connectors/

Debezium(Kafka Connect) 커넥터 설정이다. 로컬 구성(`simulator/docker-compose.yml`의 프로필 `cdc`)과 이후 RDS 구성이 같은 파일을 기준으로 한다.

| 파일 | 내용 |
|---|---|
| `member-source.json` | `public.members`를 읽어 토픽 `members-events`로 보내는 커넥터. Kafka Connect REST에 그대로 보내는 **평평한 설정 묶음**(`name` 포함) |

| `member-s3-sink.json` | 토픽 `members-events`를 S3의 `bronze/`에 JSON Lines 파일로 쌓는 S3 Sink 커넥터 (Confluent S3 Sink 12.1.13) |

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
| `partitioner.class` / `path.format` | `TimeBasedPartitioner` / `'dt'=YYYY-MM-dd` | Hive 방식 일별 폴더 |
| `partition.duration.ms` / `timezone` / `locale` | `86400000` / `UTC` / `en-US` | 하루 단위, UTC 기준 |
| `timestamp.extractor` | `Record` | **Kafka 레코드 시각(수집 시각)** 기준이다. 가입일이 아니다. 다시 읽어도 같은 폴더에 들어간다 |
| `flush.size` | `1000` | 로컬 테스트 값. 실제 값은 팀에서 정한 뒤 바꾼다 |
| `rotate.schedule.interval.ms` | `30000` | 트래픽이 적어도 30초마다 파일을 끊는다. 로컬 테스트 값 |
| `s3.compression.type` | `none` | |

객체 경로: `bronze/members-events/dt=YYYY-MM-DD/members-events+<파티션>+<시작offset>.json`

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
- `flush.size`, `rotate.schedule.interval.ms`: 운영 값으로 바꾼다 (파일이 너무 작으면 작은 파일이 많아진다).
- `topics`, `format.class`, `path.format`, `timezone`, `timestamp.extractor`는 그대로 쓴다.
