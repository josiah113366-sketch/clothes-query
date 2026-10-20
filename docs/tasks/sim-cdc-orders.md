# 작업 지시서: sim/cdc-orders

> 상태: 진행 전 · 브랜치: `sim/cdc-orders` (분기 기준: 최신 `main`, `sim/clickstream` 머지 후) · 이전 작업: `sim/cdc-local`, `sim/s3-sink-local`, `sim/clickstream` · 다음 작업: `sim/ecs-image`

## 목표

**실제 AWS(EKS)** 에서 `RDS → Debezium → Kafka → S3 Sink → S3 Bronze` 경로를 업무 토픽 5개로 띄운다. 로컬(`sim/cdc-local`, `sim/s3-sink-local`)에서 회원 테이블 하나로 만든 방식을 주문 3테이블과 `clickstream`까지 넓혀 클라우드에 올리는 작업이다.

이 브랜치가 끝나면 이렇게 된다.

```
RDS(clothes)                         EKS (kafka namespace)                         S3 clothes-query-datalake
members ──┐                          ┌ members-events ┐
orders ───┼─ Debezium(source 1개) ──┤ orders         ├─ S3 Sink(1개) ──→  bronze/<토픽>/year=YYYY/month=MM/day=DD/*.json
order_items┤   slot 1개             │ order-items    │
payments ─┘                          │ payments       │
(ECS 시뮬레이터, 다음 작업) ─────────→ └ clickstream    ┘
                                     Kafka UI (port-forward 로만 접속, 읽기 전용)
```

- 이미 떠 있는 Kafka(브로커 1대)에 **같은 Helm release를 upgrade** 해서 토픽·계정·Connect·Kafka UI를 더한다. 브로커와 디스크(PVC)는 그대로 둔다.
- 회원 10만 명은 **snapshot**(`op=r`)으로 한 번 들어간다. 주문 3테이블은 지금 비어 있어서 snapshot이 0건이고, 이후 변경(`c`/`u`)만 흐른다.
- `clickstream` 토픽은 만들고 S3 Sink 대상에도 넣는다. 하지만 **ECS에서 EKS Kafka로 보내는 경로는 만들지 않는다**(→ `sim/ecs-image`). 그래서 이번에는 `clickstream`에 메시지가 없어도 된다.

이 지시서는 **자기 완결형**이다. 필요한 값은 본문에 있다. 레포 밖 설계 문서(`member_design.md` 등)와 어긋나면 추측하지 말고 묻는다.

## 먼저 읽을 것

- 루트 `CLAUDE.md`, `simulator/CLAUDE.md`, `infra/CLAUDE.md`
- `docs/tasks/sim-cdc-local.md`, `docs/tasks/sim-s3-sink-local.md` (로컬에서 정한 커넥터 값과 그 이유)
- `docs/tasks/infra-pipeline-smoke.md`, `infra/platform/kafka/pipeline-smoke/README.md` (10-18 인프라 담당자가 실제 AWS에서 같은 경로를 시험하고 정리한 기록. **적용 순서를 그대로 따른다**)
- `infra/platform/kafka/README.md`, `infra/platform/kafka/chart/` (`values.yaml`, `templates/*.yaml`), `single-node-values.yaml`, `measurement-values.yaml`
- `infra/stacks/rds/README.md`, `infra/stacks/workload-access/README.md`, `infra/EKS_ACCESS.md`, `infra/TOPOLOGY.md`
- `connectors/member-source.json`, `connectors/member-s3-sink.json`, `connectors/README.md`
- `db/schema/001_member.sql`, `db/schema/004_orders.sql`
- `simulator/src/sim/behavior/sink.py` (`click_record`, 135번째 줄의 KST 변환)

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- **실제 AWS에 띄운다.** RDS 재부팅도 허용한다(2026-10-20 사용자 확인). 다만 논리 복제는 이미 켜져 있어서(`in-sync`) 재부팅이 필요 없을 것으로 본다. 필요해지면 먼저 알린다.
- **한 브랜치에서 `infra/`, `connectors/`, `simulator/`를 함께 고친다.** 루트 `CLAUDE.md`의 "PR 하나에 한 영역"의 예외다. PR 설명에 인프라를 고쳤다고 사용자가 적는다. 인프라 전용 브랜치는 따로 만들지 않는다.
- **역할 나누기.**
  - **Claude:** 파일(values, 커넥터 설정, SQL, 코드, 문서)을 만들고, 정적 검사(`helm template`, `terraform validate`, `pytest`)를 돌린다.
  - **사용자:** DB 접속과 SQL 실행, Secrets Manager, `kubectl`/`helm` 적용, `terraform plan/apply`. Claude는 **실행할 명령과 순서만** 드린다. RDS에 직접 접속하지 않는다(비밀번호가 Secrets Manager에 있고 RDS는 private이다). EKS API는 사용자 PC(Windows)에서만 열려 있다.
- 루트 `CLAUDE.md`의 Git 규칙을 따른다(작은 커밋, **push와 PR은 사용자 확인 후**). 커밋 메시지는 `<타입>(sim/cdc-orders): <한국어 요약>`이다. 타입은 `feat`, `fix`, `test`, `docs`, `refactor`, `chore` 중 하나다.
- 브랜치 대장 `docs/BRANCHES.md`의 `sim` 구역에 한 줄 추가하고(같은 PR), 머지 전에 이 지시서 맨 아래 `작업 결과`를 채운다.
- **`infra-smoke` 토픽과 `infra-smoke-client` 계정은 지운다**(사용자 결정). `measurement-values.yaml` 파일 자체는 지우지 않고 이번 upgrade에서 빼기만 한다.
- **Connect 이미지 취약점(Trivy High 42)은 이번 작업에서 다루지 않는다**(사용자 결정). 이미 ECR에 있는 이미지를 그대로 쓴다.
- 비밀값(DB 비밀번호, RDS 주소, AWS 계정 ID, 이미지 digest를 포함한 ECR 주소)은 Git에 넣지 않는다. 무시되는 파일(`runtime.local.yaml`, `deployment.local.tfvars`)이나 K8s Secret에만 둔다.

## 시작 전 확인 (Claude가 한다)

- 현재 브랜치가 `sim/cdc-orders`이고 최신 `main`(`sim/clickstream` 머지, PR #27)에서 만들어졌는지 확인한다.
- WSL Git에 `core.autocrlf=input`이 걸려 있는지 확인한다(`git config core.autocrlf`). 없으면 Windows에서 체크아웃한 CRLF 때문에 파일 수백 개가 "수정됨"으로 보인다.
- 아래 실제 상태를 **사용자에게 확인을 받아** 계획에 적는다(사용자가 실행한 결과를 받는다).
  - `kubectl get kafka,kafkanodepool,kafkatopic,kafkauser,kafkaconnect,pod -n kafka`: 브로커 1대 Ready, 토픽은 `infra-smoke`만, KafkaConnect 없음
  - `helm list -n kafka`와 `helm get values cq-kafka -n kafka`: release 이름과 지금 적용된 values 파일 조합
  - `kubectl get nodes`: 노드 수(지금 t3a.large 1대)와 allocatable 여유
  - RDS 행 수: `SELECT count(*) FROM members;`(100,000 기대), `product_design`, `product_variant`, `orders`, `order_items`, `payments`(주문 3테이블은 0 기대)
  - RDS 복제 설정: `SHOW wal_level;`(`logical`), `SHOW max_replication_slots;`, `SELECT * FROM pg_replication_slots;`(비어 있기를 기대), `SELECT * FROM pg_publication;`(비어 있기를 기대)
- AWS 읽기 전용 조회(Claude가 해도 된다): RDS parameter group `ParameterApplyStatus`가 `in-sync`인지, `rds.logical_replication=1`인지.

## 결정된 사항 (사용자가 확정)

**토픽 계약** (2026-10-20 사용자가 알려 줌. 레포에 이 표가 처음 들어간다)

| 토픽 | 내용 | 메시지 키 | 키를 고른 이유 |
|---|---|---|---|
| `clickstream` | `view`, `cart_add` (`event_type` 필드로 구분) | `session_id` | 같은 방문의 `view` → `cart_add` 순서를 한 파티션 안에서 지킨다 |
| `members-events` | `members` CDC | `member_id` | 같은 회원의 가입 → 탈퇴 순서 |
| `orders` | `orders` CDC | `order_id` | 같은 주문의 상태 변경 순서 |
| `order-items` | `order_items` CDC | `order_item_id` | Debezium 기본 키(PK). 주문 단위 조립은 Silver에서 한다 |
| `payments` | `payments` CDC | `payment_id` | Debezium 기본 키(PK). 시도 순서는 `attempt_no`·`requested_at`으로 맞춘다 |

| 항목 | 결정 |
|---|---|
| 브로커 | **1대** (controller 겸용, 지금 떠 있는 것). RF 1, 디스크 20 GiB, 기본 보관 72시간 |
| 파티션 / 복제 | 토픽마다 **3 / 1** |
| 토픽 보관 | 토픽마다 `retentionMs: 259200000` (72시간). 토픽에 직접 적어야 브로커 기본값을 덮어쓰지 않는다 |
| snapshot | **회원만 의미가 있다.** 주문 3테이블은 비어 있다. `product_*`는 CDC 대상이 아니다(RDS에 이미 있고 바뀌지 않는다) |
| `members_archive` | 대상이 아니다 (PII) |
| 회원 PII | 지금의 `column.include.list`(10컬럼) 방식을 **그대로** 쓴다 |
| DB 계정 | **CDC 전용 계정**을 만든다. 마스터 계정을 Connect에 주지 않는다(인프라 chart 규칙이기도 하다) |
| S3 경로 | `bronze/<토픽>/year=YYYY/month=MM/day=DD/<토픽>+<파티션>+<시작offset>.json`, UTC 일별. **`dt=`가 아니다** |
| 파일 끊기 | `flush.size=10000` 또는 `rotate.schedule.interval.ms=900000`(15분). 로컬과 같다 |
| 시각 | Bronze는 **UTC**. 클릭 `event_time`도 UTC(`...Z`)로 바꾼다 (지금은 `+09:00`) |
| Kafka UI | **이번에 넣는다.** EKS 안에 띄우고 `kubectl port-forward`로만 본다. 외부 공개(LoadBalancer, Ingress) 없음 |
| `infra-smoke` | 토픽과 계정을 지운다 |

## 기본값 (지시서가 정한 값. 바꾸려면 사용자에게 알린다)

| 항목 | 기본값 | 이유 |
|---|---|---|
| Debezium 커넥터 | **1개**(`cdc-source`), slot 1개(`cdc_slot`), publication 1개(`cdc_pub`) | RDS slot 한도가 5다. 한 트랜잭션에서 같이 바뀐 테이블의 순서도 한 slot에서 지켜진다 |
| CDC 계정 이름 | `clothes_cdc` | |
| publication | 마스터가 미리 만든다. 커넥터는 `publication.autocreate.mode=disabled` | publication은 **테이블 소유자만** 만들 수 있다. CDC 계정은 소유자가 아니다 |
| publication 컬럼 목록 | 쓰지 않는다 (네 테이블 전체) | 사용자가 `column.include.list` 방식을 고름. 필요해지면 PostgreSQL 16 컬럼 목록 publication으로 한 겹 더 막을 수 있다 |
| `topic.prefix` | `cdc` | 로컬과 같다. Debezium 기본 토픽은 `cdc.public.<테이블>` |
| 토픽 이름 바꾸기 | `RegexRouter` 3개: `cdc\.public\.members` → `members-events`, `cdc\.public\.order_items` → `order-items`, `cdc\.public\.(orders\|payments)` → `$1` | 계약 이름과 Debezium 기본 이름이 다르다 |
| heartbeat | `heartbeat.interval.ms=10000`. 토픽 `__debezium-heartbeat.cdc`(파티션 1)를 **미리 만든다** | 주문이 없는 시간에도 slot의 확인 위치가 앞으로 가서 WAL이 쌓이지 않는다 |
| 토픽 만들기 | 모두 KafkaTopic(Helm values)으로 **미리** 만든다. 커넥터의 `topic.creation.*`는 쓰지 않는다 | chart의 Connect 설정이 `topic.creation.enable: false`이고 ACL이 이름을 하나하나 허용한다 |
| Connect | **1대**, ECR에 있는 이미지(Debezium PostgreSQL 3.7.0.Final + Confluent S3 Sink 12.1.13), digest는 `runtime.local.yaml`에만 | chart가 같은 노드에 Connect 두 대를 두지 못하게 막는데 노드가 1대다 |
| 변환기 | 커넥터에서 `key/value.converter.schemas.enable=false` | worker 기본값은 `true`다. 로컬 Bronze 모양(스키마 없는 JSON)과 맞춘다 |
| 관리 컬럼 | `__op`, `__source_ts_ms`, `__source_snapshot` (`ExtractNewRecordState`, `add.fields=op,source.ts_ms,source.snapshot`) | 로컬과 같다 |
| 삭제 | `tombstones.on.delete=false`, `delete.handling.mode=drop` | 업무상 삭제가 없다. tombstone(null 메시지)이 S3 Sink JSON 쓰기를 깨지 않게 한다 |
| S3 Sink 커넥터 | **1개**(`bronze-s3-sink`), 5토픽 모두 | 설정이 토픽마다 같다 |
| S3 자격 증명 | **Pod Identity**. Connect ServiceAccount(`clothes-query-dev-connect-connect`)에 `bronze/*`만 허용하는 역할 | 10-18 시험과 같은 방식. 키를 이미지·Secret에 넣지 않는다 |
| DB 접속 정보 | K8s Secret `cdc-database`(키: `hostname`, `database`, `username`, `password`), `rds-ca`(키: `bundle.pem`). 커넥터는 `${directory:/mnt/cdc-database:<키>}`로 읽는다 | RDS 주소와 비밀번호가 Git에 들어가지 않는다 |
| DB TLS | `database.sslmode=verify-full`, `database.sslrootcert=/mnt/rds-ca/bundle.pem` | RDS가 `rds.force_ssl=1`이다 |
| Kafka UI 이미지 | `kafbat/kafka-ui`, 작업 시점 안정 버전을 **digest로 고정** (`latest` 금지) | |
| Kafka UI 권한 | 전용 KafkaUser `kafka-ui`: 5토픽과 heartbeat에 `Read, Describe, DescribeConfigs`, 그룹에 `Describe, Read`, 클러스터에 `Describe`. UI도 `READONLY=true` | 보기만 한다. 토픽 삭제나 메시지 쓰기는 못 한다 |

## 만드는 것

### 1. Kafka values (`infra/platform/kafka/cdc-orders-values.yaml`, 새 파일)

`single-node-values.yaml` **뒤에** 병합하는 파일이다. `measurement-values.yaml`은 넣지 않는다(그래서 `infra-smoke` 토픽과 계정이 빠진다). 비밀값은 없다.

- `kafka.enabled: true`
- `topics`: 위 5개(파티션 3, `retentionMs: 259200000`) + `__debezium-heartbeat.cdc`(파티션 1, `resourceName: debezium-heartbeat-cdc`. K8s 이름에 `_`를 쓸 수 없다)
- `connect.enabled: true`, `replicas: 1`
  - `produceTopics`: CDC 토픽 4개 + heartbeat 토픽
  - `consumeTopics`: 5개 토픽 전부(S3 Sink)
  - `consumerGroups`: `connect-bronze-s3-sink`
- `metrics.enabled: true`, `lagExporter.topicRegex`/`groupRegex`를 위 토픽과 그룹으로
- Kafka UI 설정(아래 4번)

이미지 digest 같은 비공개 값은 무시되는 `infra/platform/kafka/runtime.local.yaml`에 둔다. 적용 순서는 `single-node-values.yaml` → `cdc-orders-values.yaml` → `runtime.local.yaml`이다.

**`infra-smoke` 지우기 주의:** KafkaTopic CR이 빠지면 Topic Operator가 실제 토픽을 지운다. upgrade 전에 `helm diff`(또는 `helm template` 비교)로 **지워지는 것이 `infra-smoke` 토픽과 계정뿐인지** 사용자와 확인한다. 브로커, NodePool, PVC가 바뀌면 멈추고 알린다.

### 2. Debezium source (`connectors/cdc-source.yaml`, 새 파일)

Strimzi `KafkaConnector` CR이다(10-18 시험과 같은 방식). 로컬 `member-source.json`은 고치지 않고 남긴다.

| 설정 | 값 |
|---|---|
| `connector.class` | `io.debezium.connector.postgresql.PostgresConnector` |
| `plugin.name` | `pgoutput` |
| `database.hostname` / `dbname` / `user` / `password` | `${directory:/mnt/cdc-database:hostname}` 등 Secret 참조 |
| `database.sslmode` / `sslrootcert` | `verify-full` / `/mnt/rds-ca/bundle.pem` |
| `table.include.list` | `public.members,public.orders,public.order_items,public.payments` |
| `column.include.list` | 회원은 `member-source.json`의 10컬럼 그대로. 주문 3테이블은 **모든 컬럼**을 `public.<테이블>.<컬럼>`으로 나열한다(`column.include.list`를 쓰면 나열하지 않은 테이블의 컬럼이 모두 빠지기 때문) |
| `slot.name` / `publication.name` / `publication.autocreate.mode` | `cdc_slot` / `cdc_pub` / `disabled` |
| `snapshot.mode` | `initial` |
| 나머지 | 위 "기본값" 표(heartbeat, 변환기, unwrap, route, tombstone) |

`predicates`는 `cdc\.public\..*`로 바꿔서 heartbeat 토픽에는 unwrap·route를 걸지 않는다.

### 3. S3 Sink (`connectors/bronze-s3-sink.yaml`, 새 파일)

`member-s3-sink.json`의 값을 그대로 쓰고 아래만 바꾼다.

- `topics`: 5개 토픽
- `s3.bucket.name`: `clothes-query-datalake` (이미 `infra/TOPOLOGY.md`에 공개된 이름), `s3.region`: `ap-northeast-1`
- 자격 증명: 설정하지 않는다(기본 자격 증명 체인이 Pod Identity를 쓴다)
- 키, 값 변환기: 스키마 없는 JSON

### 4. Kafka UI (`infra/platform/kafka/chart/templates/kafka-ui.yaml`, 새 템플릿)

`values.yaml`에 `ui.enabled: false`(기본 꺼짐)와 `ui.image`를 추가하고, `cdc-orders-values.yaml`에서만 켠다.

- KafkaUser `kafka-ui`(TLS, 위 ACL). Deployment 1개, Service 1개(ClusterIP, 8080)
- UI 설정: 부트스트랩 `clothes-query-dev-kafka-kafka-bootstrap:9093`, mTLS(`kafka-ui` Secret의 PEM 인증서와 cluster CA), Connect REST `http://clothes-query-dev-connect-connect-api:8083`, `READONLY=true`
- **NetworkPolicy:** Strimzi가 만드는 정책은 broker 9093과 Connect REST 8083에 정해진 Pod만 들어오게 한다. Kafka UI Pod가 두 곳에 닿도록 chart의 broker listener 허용 대상에 Kafka UI를 더하고, Connect REST에는 Kafka UI Pod만 허용하는 NetworkPolicy를 하나 더한다. 다른 접근은 넓히지 않는다
- 리소스: requests `100m/256Mi`, limits `500m/512Mi`
- `values.schema.json`과 `verify/check.py`의 잘못된 입력 검사에 `ui` 항목을 더한다

접속: 사용자 PC에서 `kubectl port-forward -n kafka svc/kafka-ui 8080:8080` → `http://localhost:8080`

### 5. DB 준비 SQL (`connectors/cdc-prepare.sql`, 새 파일. 사용자가 마스터로 실행한다)

비밀번호는 파일에 쓰지 않는다. psql 변수(`\set`)나 프롬프트로 받는다.

```sql
CREATE ROLE clothes_cdc WITH LOGIN PASSWORD :'cdc_password' CONNECTION LIMIT 3;
GRANT rds_replication TO clothes_cdc;
GRANT CONNECT ON DATABASE clothes TO clothes_cdc;
GRANT USAGE ON SCHEMA public TO clothes_cdc;
GRANT SELECT ON public.orders, public.order_items, public.payments TO clothes_cdc;
GRANT SELECT (member_id, signup_at, signup_channel, gender, age_band, region_sigungu,
              marketing_consent, status, withdrawn_at, created_at) ON public.members TO clothes_cdc;
CREATE PUBLICATION cdc_pub FOR TABLE public.members, public.orders, public.order_items, public.payments;
```

- 같은 이름의 계정이나 publication이 이미 있으면 **멈추고** 알린다(덮어쓰지 않는다).
- 회원 테이블은 **컬럼 단위로** 권한을 준다. 그래서 커넥터 설정이 틀려도 snapshot에서 PII를 읽지 못한다. snapshot이 권한 오류로 실패하면 권한을 넓히지 말고 오류 내용을 알린다.
- 되돌리는 SQL(`DROP PUBLICATION`, slot 삭제, `DROP ROLE`)도 같은 파일 아래쪽에 주석으로 둔다.

### 6. Terraform 입력 (비공개 tfvars만. 코드 변경은 필요할 때만)

10-18 시험 뒤 원래대로 돌려놓은 것을 업무용으로 다시 연다. **사용자가 plan을 검토하고 apply한다.**

| 스택 | 바꾸는 것 |
|---|---|
| `rds` | `database_clients`에 EKS(노드) 보안 그룹에서 5432 허용 (`pipeline-smoke/rds-cdc.tfvars.example` 참고). `logical_replication` 값은 지금 값 그대로 |
| `network` | `additional_s3_endpoint_actions`에 `s3:AbortMultipartUpload` |
| `workload-access` | `bindings`에 `bronze-s3-sink`: namespace `kafka`, ServiceAccount `clothes-query-dev-connect-connect`, prefix `bronze/`, 작업 `ListBucket(prefix 제한)`, `GetObject`, `PutObject`, `AbortMultipartUpload`, `ListMultipartUploadParts` |

plan에서 **삭제나 교체가 하나라도 나오면** apply하지 않고 알린다. 코드 변경이 필요하면(예: 입력 검증이 `bronze/`를 막는 경우) 이유를 먼저 설명한다.

### 7. 클릭 시각 UTC (`simulator/src/sim/behavior/sink.py`)

`click_record`의 `event_time`을 `astimezone(KST)`가 아니라 **UTC로, `Z`로 끝나게** 내보낸다(Debezium 시각 표기와 같다). `jsonl`과 `kafka` Sink가 같은 함수를 쓰므로 둘 다 바뀐다. 시각 값 자체는 같고 표기만 바뀐다. 관련 테스트와 `simulator/README.md`의 "알려진 한계" 줄을 고친다.

## 적용 순서 (사용자가 실행한다. Claude는 명령을 준비한다)

1. **Terraform:** `network` → `rds` → `workload-access` 순서로 plan을 검토하고 apply
2. **DB:** CDC 비밀번호를 새로 만들어 Secrets Manager에 저장 → 마스터로 `cdc-prepare.sql` 실행 → `\du clothes_cdc`, `SELECT * FROM pg_publication_tables;`로 확인(테이블 4개, `members_archive` 없음)
3. **Secret:** Secrets Manager 값으로 K8s Secret `cdc-database`, `rds-ca`를 `kafka` namespace에 만든다. 값을 명령 기록에 남기지 않는다(파일을 거쳐 만들고 바로 지운다)
4. **Helm:** `helm template` 비교로 지워지는 것이 `infra-smoke`뿐인지 확인 → 같은 release `cq-kafka`를 upgrade → 토픽 6개, KafkaUser, KafkaConnect, Kafka UI가 Ready인지 확인 → Connect 플러그인 목록에 두 플러그인이 보이는지 확인
5. **커넥터:** `kubectl apply -f connectors/cdc-source.yaml` → snapshot 끝날 때까지 기다림 → `kubectl apply -f connectors/bronze-s3-sink.yaml`

## PII 안전 (중요)

| 위험 | 막는 방법 |
|---|---|
| 회원 PII(`name`, `email`, `phone`, `birth_date`, `password_hash`)가 Kafka에 들어감 | 1) `column.include.list` 10컬럼 2) CDC 계정의 컬럼 단위 `SELECT` 권한. 커넥터 등록 **전에** 두 가지를 확인한다 |
| `members_archive`가 수집됨 | publication과 `table.include.list`에 넣지 않는다. 확인 SQL로 검사 |
| Kafka UI로 메시지가 보임 | 토픽에 PII가 없다. UI는 port-forward로만 열리고 읽기 전용이다 |
| 설정을 잘못 넣고 snapshot함 | 토픽에 PII가 이미 들어갔다. 토픽 삭제, 커넥터·slot·offset 초기화밖에 방법이 없다. **바로 사용자에게 알린다** |
| 로그·콘솔 | 메시지 내용, RDS 주소, 비밀번호를 출력하지 않는다. 확인할 때 **키 이름과 건수만** 본다 |

## 테스트 (Claude가 돌린다)

- `helm template`: `single-node-values.yaml` + `cdc-orders-values.yaml` 조합이 렌더되고 Strimzi 공식 CRD 검사를 통과한다. 토픽 6개(이름·파티션·보관), KafkaUser ACL(literal만, wildcard 없음), Connect 1대, Kafka UI(`READONLY`, ClusterIP), NetworkPolicy가 나온다. `infra-smoke`는 나오지 않는다
- `python infra/platform/kafka/verify/check.py`: 기존 검사 + `ui` 잘못된 입력 검사 통과
- 커넥터 CR 정적 검사(pytest 또는 기존 `tests/test_*connector_config.py` 방식): 테이블 4개(`members_archive` 없음), 회원 컬럼 10개(PII 없음), 주문 3테이블 컬럼이 DDL과 같음, 비밀번호·주소가 `${directory:...}` 참조, route 결과가 계약 토픽 이름 4개, sink `topics`가 5개, 경로 규칙이 `year=/month=/day=`·UTC
- 영향받은 Terraform 스택: `terraform init -backend=false && terraform validate`
- `simulator`: `ruff check .`, `ruff format --check .`, `pytest`. 클릭 시각이 `Z`로 끝나고, 같은 시드면 이전과 **같은 순간**을 가리킨다

## 만들지 않는 것

- ECS(Fargate)에서 EKS Kafka로 가는 경로(내부 NLB, 클라이언트 인증서 공급, SG) → `sim/ecs-image`
- 시뮬레이터 ECS 배포, 컨테이너 이미지 → `sim/ecs-image`
- `product_*` CDC 또는 S3 적재
- 브로커 증설(3대, RF 3), 노드 증설
- Connect 이미지 다시 빌드, 취약점 조치
- Silver 이후, Glue/Athena 테이블, 중복 제거
- 탈퇴(`u`)와 `members_archive` 이동
- `.gitattributes` 추가(줄바꿈 규칙은 팀과 따로 정한다)
- 기존 로컬 `connectors/member-*.json`, `sim cdc`, `sim sink` 명령 수정

## 작업 순서

1. 시작 전 확인을 하고, **계획을 먼저 제시해 사용자 확인을 받는다**
2. `docs/BRANCHES.md`에 한 줄 추가 + 이 지시서 → 커밋 `docs(sim/cdc-orders): 브랜치 등록과 작업 지시서 추가`
3. 클릭 시각 UTC + 테스트 → 커밋 `fix(sim/cdc-orders): 클릭 event_time을 UTC로 발행`
4. `cdc-orders-values.yaml` + 정적 검사 → 커밋 `feat(sim/cdc-orders): 업무 토픽 5개와 Connect values 추가`
5. Kafka UI 템플릿, schema, 검사 → 커밋 `feat(sim/cdc-orders): Kafka UI 읽기 전용 배포 추가`
6. `cdc-prepare.sql`, `cdc-source.yaml`, `bronze-s3-sink.yaml` + 정적 테스트 → 커밋 `feat(sim/cdc-orders): 주문·회원 CDC와 Bronze S3 Sink 커넥터 추가`
7. Terraform 입력 예시(`*.tfvars.example`) 갱신, 필요할 때만 코드 변경 → 커밋 `chore(sim/cdc-orders): CDC 접속·S3 권한 입력 예시 추가`
8. README 갱신 → 커밋 `docs(sim/cdc-orders): README 갱신`
9. 사용자가 "적용 순서"를 실행하고, 함께 "완료 확인"을 한다
10. 이 지시서 맨 아래 `작업 결과`를 채우고, 상태를 `완료`로, `docs/BRANCHES.md` 상태를 바꾼다 → 커밋 `docs(sim/cdc-orders): 작업 결과 기록`. 그다음 사용자 확인을 기다린다

## 완료 확인

아래를 **실제로 실행**해서 결과를 보고한다. EKS와 DB 명령은 사용자가 실행하고 결과를 붙여 준다.

- [ ] "테스트" 절이 모두 통과한다
- [ ] **Kafka:** `kubectl get kafkatopic -n kafka`에 6개(5 + heartbeat)만 있고 모두 Ready, 파티션 3(heartbeat 1), RF 1. `infra-smoke` 토픽과 계정이 없다. 브로커 Pod 재시작 0, PVC가 그대로(같은 이름, Bound)
- [ ] **Connect:** KafkaConnect Ready, 플러그인 목록에 `PostgresConnector`와 `S3SinkConnector`. 두 KafkaConnector가 Ready이고 task가 `RUNNING`
- [ ] **DB:** `pg_replication_slots`에 `cdc_slot` 하나(`active = true`), `pg_publication_tables`에 테이블 4개(`members_archive` 없음)
- [ ] **snapshot:** `members-events`의 `__op = r` 메시지가 **100,000건**(Kafka UI 또는 offset 합계). 걸린 시간 보고
- [ ] **PII:** `members-events` 샘플 메시지의 **키 이름**이 10컬럼 + 관리 컬럼 3개뿐이다. 금지 이름 5개가 없다
- [ ] **S3:** `aws s3 ls s3://clothes-query-datalake/bronze/ --recursive --summarize`에 `members-events/year=.../month=.../day=.../members-events+<파티션>+<offset>.json`이 있고 날짜가 오늘(UTC)이다. 파일 안 줄 수 합계가 100,000(중복이 있으면 개수만 보고)
- [ ] **주문 한 건 흐름:** 마스터로 시험 주문 1건(`orders` 1, `order_items` 1, `payments` 1)을 INSERT하고 `orders`를 한 번 UPDATE → `orders`(c, u), `order-items`(c), `payments`(c)가 Kafka에 나오고, 15분 안에 S3 Bronze에 쌓인다. 시각 컬럼이 `Z`로 끝난다. 메시지 키가 각 PK다. 확인 후 시험 행을 지우고(지우기는 `d` 이벤트가 나오지 않는다), S3 시험 파일을 남길지 사용자에게 묻는다
- [ ] **중단 후 이어받기:** Connect를 멈추고(`replicas: 0` 또는 커넥터 pause) 시험 주문 1건 추가 → slot의 밀린 WAL이 늘어난 것을 확인 → 다시 켜면 그 주문이 빠지지 않고 도착한다. 회원 `r`이 다시 나오지 않는다(snapshot 반복 없음)
- [ ] **WAL:** `pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn)`이 몇 분 뒤에도 늘지 않는다(heartbeat가 동작한다)
- [ ] **Kafka UI:** port-forward로 접속해서 토픽 6개, `connect-bronze-s3-sink` 그룹 lag, 커넥터 2개 상태가 보인다. 토픽 삭제나 메시지 쓰기 버튼이 없거나 거부된다
- [ ] **권한:** Connect가 `bronze/` 밖에는 쓸 수 없다(`infra-pipeline-smoke`의 거부 확인과 같은 방식). 노드 역할에 S3 권한이 없다
- [ ] **자원:** 노드 수, Connect·Kafka UI의 CPU/메모리 사용량(`kubectl top pod -n kafka`)을 보고
- [ ] `git status`에 비밀값 파일(`runtime.local.yaml`, `*.local.tfvars`, `.env`)이 없다. push, PR을 하지 않았다

## README 갱신

- `connectors/README.md`: `cdc-source.yaml`, `bronze-s3-sink.yaml`, `cdc-prepare.sql` 설명(값마다 이유), 토픽 계약 표, 로컬 `member-*.json`과의 차이(Secret 참조, publication을 직접 만드는 이유, Pod Identity)
- `infra/platform/kafka/README.md`: 지금 배포 상태(업무 토픽 5개, Connect 1대, Kafka UI), values 병합 순서, Kafka UI 접속 방법
- `simulator/README.md`: 클릭 `event_time`이 UTC라는 점(알려진 한계 줄 고침), `clickstream`의 Bronze 적재가 생겼다는 점
- `infra/TOPOLOGY.md`의 Kafka·CDC 줄을 실제 상태로 갱신

## 참고: 커밋 메시지 제안

1. `docs(sim/cdc-orders): 브랜치 등록과 작업 지시서 추가`
2. `fix(sim/cdc-orders): 클릭 event_time을 UTC로 발행`
3. `feat(sim/cdc-orders): 업무 토픽 5개와 Connect values 추가`
4. `feat(sim/cdc-orders): Kafka UI 읽기 전용 배포 추가`
5. `feat(sim/cdc-orders): 주문·회원 CDC와 Bronze S3 Sink 커넥터 추가`
6. `chore(sim/cdc-orders): CDC 접속·S3 권한 입력 예시 추가`
7. `docs(sim/cdc-orders): README 갱신`
8. `docs(sim/cdc-orders): 작업 결과 기록`

## 막히면

- 이 지시서와 설계 문서·인프라 문서·실제 상태가 어긋나 보이면 **추측하지 말고 묻는다.**
- Helm diff에 `infra-smoke` 말고 지워지거나 바뀌는 것(브로커, NodePool, PVC, Connect 내부 토픽)이 있으면 **멈춘다.**
- Terraform plan에 삭제나 교체가 있으면 apply하지 않는다.
- snapshot이 컬럼 권한 오류로 실패하면 권한을 넓히지 말고 알린다.
- Connect나 Kafka UI가 노드 자원 부족으로 `Pending`이면 노드 상한을 올리지 말고 알린다(비용이 늘어난다).
- slot의 밀린 WAL이 256 MB(`max_slot_wal_keep_size`)에 가까워지면 알린다. 넘으면 slot이 무효가 되어 snapshot을 다시 해야 한다.
- Kafka UI를 NetworkPolicy로 막을 수 없거나 읽기 전용이 되지 않으면 배포하지 말고 알린다.

## 작업 결과 (머지 전에 작성한다. 사람과 AI가 나중에 이 브랜치가 무엇을 했는지 읽는 곳이다)

- **한 줄 요약:**
- **무엇을 만들었나:**
- **왜 그렇게 했나:**
- **입력과 출력:**
- **확인한 결과:**
- **알려진 한계·남은 일:**
