# connectors/

Debezium(Kafka Connect) 커넥터 설정이다. 로컬 구성(`simulator/docker-compose.yml`의 프로필 `cdc`)과 이후 RDS 구성이 같은 파일을 기준으로 한다.

| 파일 | 내용 |
|---|---|
| `member-source.json` | `public.members`를 읽어 토픽 `members-events`로 보내는 커넥터. Kafka Connect REST에 그대로 보내는 **평평한 설정 묶음**(`name` 포함) |

등록과 상태 확인, 초기화는 `sim cdc setup` / `status` / `reset`으로 한다 (`simulator/README.md`의 "로컬 CDC").

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
