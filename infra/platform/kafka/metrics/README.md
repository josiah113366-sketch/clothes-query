# Kafka·Connect 지표 노출

2026-10-22 후속: 기존 WAS 노드에 [개발용 Prometheus·Grafana](../../monitoring/README.md)를 추가해 실제 Kafka·Connect·lag 지표 수집을 확인했다. 아래 수집기 미선정 문구는 초기 준비 이력이며, 현재 알림 수신 채널은 여전히 미연결이다.

결정: 인프라 범위에서 Strimzi의 JMX Prometheus Exporter와 선택적 Kafka Exporter를 준비한다. 기본 `metrics.enabled=false`, `metrics.lagExporter.enabled=false`다. 수집 서버·장기 저장·대시보드·알림 채널은 아직 선택/배포하지 않았다.

runtime의 비공개 `runtime.local.yaml`에 다음을 추가해 사용할 수 있다. 아래 regex는 예시이므로 실제 업무 토픽·consumer group으로 바꾼다.

```yaml
metrics:
  enabled: true
  lagExporter:
    enabled: true
    topicRegex: '^example-orders$'
    groupRegex: '^example-reader$'
```

Kafka가 활성화되어 있어야 한다. JMX만 필요하면 lagExporter를 켜지 않아도 된다. Connect가 비활성이면 Connect workload를 새로 만들지 않는다. chart는 `*-metrics` ConfigMap과 Kafka/KafkaConnect의 `metricsConfig` 참조를 만들고, Kafka Exporter는 Strimzi가 생성한다. exporter 이미지는 기존 Kafka의 고정 digest를 사용한다. exporter 추가 request는 100m/128Mi, limit는 500m/256Mi이며 기존 노드 상한은 늘리지 않는다. broker/worker에도 JMX agent의 자원 부담이 추가되므로 실제 heap·여유를 측정한다.

## 노출 및 수집 계약

| 대상 | 접근 | 확인할 주요 지표 |
|---|---|---|
| 각 Kafka Pod | HTTP `:9404/metrics`, container port `tcp-prometheus` | `kafka_server_replicamanager_underreplicatedpartitions`, `kafka_controller_active_controller_count`, offline/min ISR, raft, log 크기 규칙 |
| 각 Connect Pod | HTTP `:9404/metrics`, 동일 port 이름 | `kafka_connect_task_status{status=...}`, worker 수·오류·전달 수, `debezium_postgres_connected`, `debezium_postgres_millisecondsbehindsource` |
| 선택적 Kafka Exporter Pod | HTTP `:9404/metrics`, 동일 port 이름 | `kafka_consumergroup_lag`, group offset, topic offset |

JMX 규칙은 [Kafka](../chart/files/kafka-metrics.yml), [Connect/CDC](../chart/files/connect-metrics.yml)에 둔다. 데이터 레코드·SQL을 지표로 내보내지 않는다. connector/server/topic/group 이름은 지표 label이 될 수 있으므로 이름에 PII를 넣지 않는다. `kafka_log_size_bytes`는 로그 사용량이며 PVC 여유 공간이 아니다. 노드/PVC 파일시스템, RDS WAL/slot/스토리지 지표는 별도 수집이 필요하다. `MilliSecondsBehindSource`는 이벤트 시간·시계·트래픽 유무의 영향을 받으므로 단독 유실 판정에 사용하지 않는다.

외부 Service/Ingress/LoadBalancer나 공개 JMX RMI 포트를 만들지 않는다. metrics HTTP는 별도 client 인증이 없고 Strimzi 기본 NetworkPolicy는 metrics 포트를 클러스터 내에 허용한다. 수집기 namespace만 허용한다고 주장하지 않는다. 특정 수집기만 허용하려면 기존 허용 정책까지 함께 검토해야 하며 추가 NetworkPolicy 하나만으로 기존 허용을 좁힐 수 없다. Kafka 데이터 listener mTLS/ACL과 Connect REST 관리 제한은 유지한다.

[scrape-jobs.yaml](scrape-jobs.yaml)은 나중에 선택한 **클러스터 내부 Prometheus 호환 수집기**의 `scrape_configs`에 가져올 예시다. 각 Pod를 직접 발견하므로 단일 Service IP를 통해 broker 지표가 섞이는 문제를 피한다. 기본 cluster/Connect/combined pool 이름을 사용하므로 이름을 바꾸면 selector도 바꾼다. 수집기에는 kafka namespace의 Pod get/list/watch 권한과 API/DNS/metrics 통신이 필요하다. 해당 ServiceAccount/RoleBinding은 수집기 선택 이후 연결한다. 30초 수집 주기·10초 timeout은 예시이며 SLO 확정값이 아니다.

## 검증 결과와 남은 것

2026-10-14 로컬 일회성 검사에서 이 chart와 같은 JMX 규칙 파일을 고정 이미지의 agent에 연결했다. JMX scrape error 0, Kafka active controller 1/under-replicated partition 0, Connect task running/CDC streaming connected 1을 확인했다. 테스트용 group의 offset을 초기 위치로 두고 positive consumer lag 지표도 확인했다. 기존 snapshot/변경/중단 후 전달 검사를 함께 통과했고 임시 자원을 정리했다.

Helm은 기본 미생성, Kafka만 지표 활성, Connect 포함 지표 활성, exporter의 필수 regex·잘못된 regex 거부 및 공식 Strimzi CRD 참조를 검증했다. Prometheus 서버·EKS Pod discovery·NetworkPolicy·알림은 실행 검증하지 않았다. 수집 예시는 YAML 구조/선택 규칙을 검증하며 실제 대상의 label·port 이름은 배포 PC에서 확인한다.

실배포 시 각 broker/worker의 target이 하나씩 수집되는지 먼저 확인한다. 그 후 target down·복제 이상·task failed는 운영 조건과 지속 시간을 정하고, lag·CDC 지연·오류율은 실제 트래픽 기준으로 임계값을 정한다. Slack 연결이나 6번 탐지/AI 규칙을 대신 구현하지 않는다.

공식 근거: [Strimzi 1.3 Kafka 지표 예제](https://github.com/strimzi/strimzi-kafka-operator/blob/1.3.0/examples/metrics/kafka-metrics.yaml), [Connect 지표 예제](https://github.com/strimzi/strimzi-kafka-operator/blob/1.3.0/examples/metrics/kafka-connect-metrics.yaml), [Prometheus Pod discovery](https://prometheus.io/docs/prometheus/latest/configuration/#kubernetes_sd_config), [JMX Exporter 규칙](https://prometheus.github.io/jmx_exporter/1.6.0/http-mode/rules/).
