# Kafka runtime Helm chart

[상위 실행 안내](../README.md)를 따른다. 공식 Strimzi 운영자·CRD·StorageClass 설치 후 사용한다. 기본 values는 리소스를 생성하지 않는다. `values.schema.json`은 타입·digest·이름·수치 범위를 검증하고 템플릿은 미정 용량·보존 값과 토픽/ACL 참조를 검증한다.

이 chart는 Kafka/KafkaNodePool, 명시된 KafkaTopic/KafkaUser 및 선택적 KafkaConnect만 관리한다. StorageClass와 운영자는 관리하지 않는다. namespace는 `kafka`로 한정했다. release 이름은 리소스 이름에 붙지 않으므로 한 namespace에는 이 chart를 **한 release만** 설치한다. 기존 클러스터 이름·node pool 이름·Connect 내부 토픽 이름을 변경하면 별개 리소스로 취급될 수 있다.
