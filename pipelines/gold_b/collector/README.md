# pipelines/gold_b/collector

**Bronze 지연 수집기**다. S3 Sink 커넥터가 Kafka 메시지를 얼마나 밀려서 처리하는지 1분마다 재서 `gold_b.bronze_lag_snapshots`에 쌓는다. 시나리오 2(트래픽 폭주)의 신호이고, 탐지 R3(`agent/detect/rules.py`)가 읽는다. 설계는 [docs/design/gold-b/README.md](../../../docs/design/gold-b/README.md)의 ③, 작업 기록은 [docs/tasks/gold-b-collector.md](../../../docs/tasks/gold-b-collector.md).

## 읽고 쓰는 것

| 구분 | 대상 | 내용 |
|---|---|---|
| 읽음 | Kafka 관리 API | 토픽·파티션별 마지막 위치, S3 Sink 소비자 그룹이 처리한 위치 |
| 읽음 | Kafka 메시지 | 밀린 파티션마다 처리 안 된 가장 오래된 메시지 1건의 **시각만** (내용은 쓰지 않음) |
| 읽음 | Kafka Connect REST | 커넥터·태스크 상태. 토픽 목록을 안 줬으면 커넥터 설정의 `topics` |
| 씀 | `<GOLD_B_LAG_OUTPUT>/dt=YYYY-MM-DD/hour=HH/part-<측정 시각>-<임의값>.parquet` | 한 번 잴 때 파일 1개, 토픽 × 파티션 줄 |

처리 위치를 커밋하지 않고, Kafka·Bronze에 아무것도 쓰지 않는다.

## 값의 뜻

컬럼 정의는 [ddl/bronze_lag_snapshots.sql](../ddl/bronze_lag_snapshots.sql). 시각은 모두 UTC다.

| 컬럼 | 뜻 |
|---|---|
| `end_offset` | 마지막 메시지 다음 위치 |
| `committed_offset` | S3 Sink가 처리한 위치 (= 다음에 처리할 메시지). 처리 기록이 없으면 NULL |
| `lag_msgs` | `end_offset - committed_offset`. 처리 기록이 없으면 NULL |
| `lag_sec` | 처리 안 된 가장 오래된 메시지의 Kafka 시각부터 측정 시각까지(초). 밀린 게 없으면 0, 처리 기록이 없거나 시각을 모르면 NULL |
| `connector_state` | 커넥터 상태 (`RUNNING`, `PAUSED`, `FAILED` …). 태스크가 RUNNING이 아니면 그 태스크 상태. Connect에 접속하지 못하면 `UNREACHABLE`, 커넥터가 없으면 `NOT_FOUND` |

- S3 Sink는 파일을 쓸 때만 처리 위치를 기록한다(지금 15분 또는 10,000건마다). 그래서 **정상일 때도 `lag_sec`이 0~약 900초를 톱니 모양으로 오간다.**
- 처리할 메시지가 보관 기간(3일)이 지나 지워졌으면 `lag_sec`은 남아 있는 가장 오래된 메시지 기준이라 실제보다 작다.
- Kafka에 접속하지 못하면 그 회차는 파일을 쓰지 않고 오류로 끝난다. 탐지가 "측정 줄 없음"으로 잡는다.
- Kafka에 없는 토픽은 건너뛰고 나머지를 잰다 (로그에 남김).

## 환경변수

공개 레포라 실제 주소·버킷 이름은 넣지 않는다. 더미 값 예시는 [.env.example](.env.example).

| 이름 | 기본값 | 뜻 |
|---|---|---|
| `GOLD_B_LAG_OUTPUT` | (필수) | 저장 위치. 로컬 폴더 또는 `s3://<버킷>/gold_b/bronze_lag_snapshots` |
| `KAFKA_BOOTSTRAP` | `localhost:29092` | Kafka 주소 (시뮬레이터와 같은 이름) |
| `KAFKA_SECURITY_PROTOCOL` | `PLAINTEXT` | `PLAINTEXT` 또는 `SSL`(mTLS) |
| `KAFKA_SSL_CA_FILE`, `KAFKA_SSL_CERT_FILE`, `KAFKA_SSL_KEY_FILE` | 없음 | mTLS 인증서 파일 경로 (인증서와 키는 함께) |
| `GOLD_B_CONNECT_URL` | `http://localhost:8083` | Kafka Connect REST 주소 |
| `GOLD_B_SINK_CONNECTOR` | `bronze-s3-sink` | 잴 S3 Sink 커넥터 이름 |
| `GOLD_B_SINK_GROUP` | `connect-<커넥터 이름>` | 그 커넥터의 소비자 그룹 |
| `GOLD_B_LAG_TOPICS` | 커넥터 설정의 `topics` | 쉼표로 나눈 토픽 목록. **운영에서는 꼭 넣는다** (Connect가 멈춰도 계속 재려면) |

S3에 쓸 때는 boto3 기본 자격 증명(EKS에서는 Pod Identity)과 `AWS_REGION`을 쓴다. 로그에는 주소·버킷 이름을 남기지 않는다.

## 실행

저장소 루트에서 Gold B 가상환경으로 실행한다.

```powershell
python -m venv pipelines/gold_b/.venv                                   # 처음 한 번
pipelines/gold_b/.venv/Scripts/python -m pip install -r pipelines/gold_b/requirements.txt pytest
pipelines/gold_b/.venv/Scripts/python -m pipelines.gold_b.collector.bronze_lag_collector --once --env-file pipelines/gold_b/collector/.env
pipelines/gold_b/.venv/Scripts/python -m pipelines.gold_b.collector.bronze_lag_collector --interval 60 --env-file pipelines/gold_b/collector/.env
```

- `.env`는 `.env.example`을 복사해서 만든다 (Git에 안 올라감). 같은 이름의 환경변수가 있으면 환경변수를 쓴다.
- `--once`는 CronJob(1분마다)용, `--interval 60`은 상시 실행용이다. 어느 쪽으로 띄울지는 재영 님과 정한다.
- 종료 코드: 성공 0, 측정 실패 1, 설정 오류 2.

시험:

```powershell
pipelines/gold_b/.venv/Scripts/python -m pytest -q pipelines/gold_b/tests
```

## EKS에 올릴 때 필요한 것 (재영 님과)

- 이미지: 이 폴더와 `pipelines/gold_b/requirements.txt`를 담은 컨테이너 이미지, 저장소(ECR)
- Kafka: mTLS 사용자. 대상 토픽 조회·읽기, S3 Sink 그룹 조회, 시각만 읽는 임시 그룹 `gold-b-lag-*`
- Connect REST: 지금은 Kafka UI만 붙을 수 있으니 수집기 파드도 허용
- S3: Pod Identity로 `gold_b/bronze_lag_snapshots/`에 쓰기
- 실행: CronJob(`--once`, 1분마다) 또는 상시 파드(`--interval 60`)
