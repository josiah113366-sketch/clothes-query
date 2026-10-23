# 인프라 이메일 알림

사용자가 2026-10-23 기존 이메일로 자동 장애 알림 연결을 승인했다. 수신 주소는 Git 제외 infrastructure-alerts 스택의 deployment.local.tfvars.json에만 둔다.

```text
Kafka·Connect/CDC → Prometheus 10개 경보 → Alertmanager → SNS → 확인된 이메일
RDS 표준 지표 → CloudWatch 경보 5개 ────────────────────┘
```

## 적용 순서

1. [독립 infrastructure-alerts 스택](../../stacks/infrastructure-alerts/README.md)의 계획을 검토하고 SNS·경보·publish 전용 역할/Pod Identity를 준비한다. AWS Budget은 포함하지 않는다.
2. 이메일의 AWS SNS 확인 링크를 수신자가 직접 누른다. PendingConfirmation 상태에서는 실제 경보 수신을 완료했다고 보고하지 않는다.
3. 기존 Helm release values를 보존한 비공개 overlay에 아래 값을 병합해 cq-monitoring에 적용한다. 기본 chart는 알림 비활성이다.

```yaml
alertmanager:
  enabled: true
  topicArn: arn:aws:sns:ap-northeast-1:<계정ID>:clothes-query-dev-infra-alerts
```

Alertmanager 공식 v0.34.1 digest를 고정했다. Pod는 기존 API 풀에서 25m/64Mi를 예약하고 100m/128Mi로 제한한다. Service는 내부 ClusterIP 9093이고 새 노드·PVC·Ingress·DB·CloudWatch Logs는 없다. 관리용 웹/API를 ALB로 공개하지 않는다. SNS publish 전용 Pod Identity를 사용하며 AWS 정적 키나 Kubernetes API 권한을 주지 않는다.

## 확인

- CloudWatch describe-alarms: 프로젝트 전용 5개 평가 상태 확인.
- SNS list-subscriptions-by-topic: 이메일 구독의 PendingConfirmation 여부 확인. 주소를 로그로 출력하지 않는다.
- Alertmanager Pod Ready·Pod Identity 환경변수/프로젝션, Prometheus runtime config의 alerting target 확인.
- 합성 InfrastructureEmailDeliveryTest 경보를 내부 API에 한 번 넣어 SNS 전송 성공/실패 카운터를 확인하고 같은 경보를 종료한다. Kafka·RDS 업무 데이터를 쓰지 않는다. SNS Publish 성공은 미확인 이메일의 실제 수신 증명이 아니다.
- 실제 장애를 만들거나 DB/노드를 재시작하지 않는다.

## 범위와 한계

- 자동 수집/이메일: 기존 Prometheus Kafka·Connect/CDC 경보와 RDS 여유 공간·WAL·CPU·메모리. 경보만으로 원인과 데이터 정합성을 확정하지 않는다.
- RDS WAL instance 지표 누락도 경보 대상이다. DB를 의도적으로 중지하거나 복제 지표가 없어져도 통보할 수 있으므로 CloudWatch reason을 확인한다. 실제 slot invalidation을 직접 확인하는 경보는 아니다.
- S3 실제 도착·Airflow 업무 DAG 성공·RDS PITR 복원 검증·Kafka PVC 사용률은 일회성 readiness 점검 또는 후속 범위다. 모든 인프라가 자동 감시된다고 표시하지 않는다.
- Prometheus/Alertmanager와 WAS가 같은 API 노드에 있어 이 노드/네트워크가 죽으면 Kafka 경보 전달도 멈출 수 있다. RDS CloudWatch 경보는 EKS 밖에서 계속 동작한다. 독립 heartbeat는 아직 없다.
- Alertmanager 데이터는 32Mi emptyDir에 저장한다. 재시작 시 silence/중복 방지 이력이 사라져 경보가 다시 올 수 있다. 영구 silence 설정에 의존하지 않는다.
- 같은 경보는 30초 묶은 뒤 보내고, 변경은 5분 간격, 지속 경보는 4시간마다 재전송한다. 복구 알림도 보낸다.
- 표준 CloudWatch 경보 5개 및 SNS 전송량에 소액 과금이 추가된다. 비용은 [CloudWatch 가격](https://aws.amazon.com/cloudwatch/pricing/)과 [SNS 가격](https://aws.amazon.com/sns/pricing/)의 도쿄 요율·계정 무료 구간을 따른다. 실제 청구 전 무과금이라고 단정하지 않는다.

[Alertmanager SNS 설정](https://prometheus.io/docs/alerting/latest/configuration/#sns_config), [EKS Pod Identity 신뢰 조건](https://docs.aws.amazon.com/eks/latest/userguide/pod-id-role.html).
