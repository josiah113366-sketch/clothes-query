# Kafka runtime Helm chart

기본 `profile=standard`는 기존 RF=3 구성이다. 새 개발 runtime의 단일 노드 후보는 `../single-node-values.yaml`을 명시해 `profile=single-node`를 선택한다. Kafka/Connect 각 1개·RF/min ISR 1로 업무·내부 토픽을 함께 맞추며 두 AZ minDomains 강제 조건을 제거한다. 해당 파일만으로 리소스가 활성화되지 않는다. TLS/ACL·PVC 보존은 유지하고 기존 runtime/PVC 축소에는 사용하지 않는다. [검증 결과](../../../../docs/design/infra/kafka-single-node-validation-2026-10-16.md).

[상위 실행 안내](../README.md)를 따른다. 공식 Strimzi 운영자·CRD·StorageClass 설치 후 사용한다. 기본 values는 리소스를 생성하지 않는다. `values.schema.json`은 타입·digest·이름·수치 범위를 검증하고 템플릿은 미정 용량·보존 값과 토픽/ACL 참조를 검증한다.

이 chart는 Kafka/KafkaNodePool, 명시된 KafkaTopic/KafkaUser, 선택적 KafkaConnect와 지표 ConfigMap을 관리한다. StorageClass와 운영자는 관리하지 않는다. namespace는 `kafka`로 한정했다. release 이름은 리소스 이름에 붙지 않으므로 한 namespace에는 이 chart를 **한 release만** 설치한다. 기존 클러스터 이름·node pool 이름·Connect 내부 토픽 이름을 변경하면 별개 리소스로 취급될 수 있다.

Debezium 기본 `prefix.schema.table` 토픽의 점·밑줄은 실제 Kafka 이름에 유지한다. Kubernetes 이름으로 사용할 수 없으면 `topics[].resourceName`을 별도로 지정한다. 예: `name: smoke.public.cdc_probe`, `resourceName: smoke-public-cdc-probe`. ACL의 produceTopics/consumeTopics에는 **실제 토픽 이름**을 쓴다. 기존 DNS-compatible `name` 입력은 resourceName 없이 그대로 유지된다. 중복 리소스 이름은 거부한다.

지표는 기본 비활성이다. `metrics.enabled`로 JMX 노출을 켜고, 별도 `metrics.lagExporter.enabled`에는 실제 토픽/group regex를 명시한다. [노출·수집·검증 안내](../metrics/README.md)를 따른다.

Connect에서 Sink도 실행하려면 `connect.consumeTopics`와 `connect.consumerGroups`를 명시한다. 빈 기본값은 기존 source-only 권한을 유지한다. 읽기 토픽은 chart에 선언된 실제 토픽이어야 하며, consumer group은 Sink 이름에 맞는 `connect-<connector-name>`을 사용한다. wildcard와 그룹 없는 consume 설정은 거부한다. `produceTopics`는 계속 명시적으로 필요하므로 이 chart는 source 없는 Sink-only 배포를 지원하지 않는다.
