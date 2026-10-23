# 개발용 모니터링

장애 감지 범위·일회성 읽기 점검은 [READINESS.md](READINESS.md), Kafka/CDC/RDS 복구 순서는 [장애 대응 안내](../../../docs/operations/incident-recovery.md)를 따른다. 화면 경보와 외부 통보, 백업 설정과 실제 복원 검증을 구분한다.

기존 WAS 노드에 Prometheus·Grafana·Metrics Server를 배치한다. Kafka/Airflow 공용 노드와 API Deployment·NodePool 설정은 변경하지 않는다. WAS 전용 taint를 허용하는 monitoring Pod만 추가하며, 새 EC2·ALB·NodeClass는 기본 구성에서 생성하지 않는다.

## 구성과 비용

- namespace `monitoring`, Helm release `cq-monitoring`.
- Prometheus 3.15.1, Grafana 13.2.4, Metrics Server 0.9.0 공식 이미지를 digest로 고정했다.
- 요청량 합계 CPU 300m, 메모리 896MiB. 단일 WAS 노드의 자원을 공유하므로 성능 격리나 고가용성을 보장하지 않는다.
- Prometheus gp3 5GiB, Grafana gp3 1GiB. 48시간 또는 블록 1GB 중 먼저 도달하는 보관 조건이 적용된다. WAL/head를 위한 여유는 별도이며 보관 시간이 보장되는 것은 아니다.
- 도쿄 gp3 공식 단가 $0.096/GB-month 기준 디스크 추가분 약 $0.576/월. 기존 노드 비용은 별도이며 NAT 전송·AZ 간 전송·세금은 포함하지 않는다.
- PVC는 Helm uninstall 시 보존하고 StorageClass는 `Retain`이다. 삭제만으로 EBS 과금이 멈추지 않으므로 폐기할 때 소유권과 백업을 확인한 뒤 PV/EBS를 별도 정리한다.

## 볼 수 있는 것과 아직 없는 것

Kafka/Connect JMX, Kafka consumer lag, WAS `/metrics`, Prometheus 자체를 60초마다 수집한다. Grafana Infrastructure 폴더의 `Clothes Query - Infrastructure`에서 연결 상태·lag·CDC 지연·WAS 요청/오류·DB 연결 대기를 본다. 대상이 사라지는 경우도 경보로 표시한다. 지표가 없는 화면은 건강하다는 뜻이 아니다.

Metrics Server는 `kubectl top`을 제공한다. 현재 Grafana에는 노드/Pod CPU·메모리 이력 수집을 연결하지 않았다. RDS/WAL/PVC 여유와 S3 파일 도착은 상시 수집 대신 [읽기 전용 점검](READINESS.md)에서 확인한다. Airflow 업무 성공 감시는 미연결이다. 경보는 Prometheus 화면에서 확인할 수 있지만 메일·Discord·Alertmanager 수신 채널은 연결하지 않았다.

## 검사

```powershell
python -m pip install -r infra/platform/monitoring/requirements.txt
python infra/platform/monitoring/check.py --helm <helm 경로> --prometheus-config .cache/monitoring-prometheus.yml
promtool check config --syntax-only .cache/monitoring-prometheus.yml
promtool check rules infra/platform/monitoring/chart/files/rules.yaml
promtool test rules infra/platform/monitoring/rule-tests.yaml
```

GitHub `Infrastructure checks`에도 Docker의 고정 Prometheus 이미지로 같은 검사를 추가했다. 로컬 Docker를 켤 필요는 없다. 이 workflow에는 AWS 배포 권한이 없다.

## 설치·접속

기존 EKS 관리자 context와 WAS NodePool `clothes-query-dev-api`, Kafka namespace가 필요하다. 다른 Metrics Server/APIService가 이미 있으면 중복 설치하지 말고 `metricsServer.enabled=false`로 조정한다. Prometheus SA는 Kafka Pod 발견 권한만 가진다. Metrics Server에는 upstream 용도의 노드/Pod 지표 조회·위임 인증 권한이 필요하며 Secret 조회나 노드 proxy 권한은 주지 않는다. kubelet TLS 검증은 유지한다.

먼저 namespace `monitoring`과 Secret `monitoring-grafana-admin`의 `username`·`password` 키를 준비한다. 실제 값은 Git·Helm values에 넣지 않는다. 이 저장소에는 비밀번호나 Secret 리소스가 없다.

```powershell
helm upgrade --install cq-monitoring infra/platform/monitoring/chart --namespace monitoring --atomic --wait --timeout 5m
kubectl -n monitoring get pods,pvc
kubectl top nodes
kubectl top pods -n api --containers
kubectl -n monitoring port-forward svc/monitoring-grafana 13000:3000
```

브라우저 `http://localhost:13000`으로 접속한다. 사용자 이름은 `operator`다. 관리자 비밀번호는 본인 터미널에서만 조회한다.

```powershell
$encoded = kubectl -n monitoring get secret monitoring-grafana-admin -o jsonpath='{.data.password}'
[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($encoded))
```

Prometheus는 필요할 때 `kubectl -n monitoring port-forward svc/monitoring-prometheus 19090:9090`으로 열고 `/targets`, `/alerts`를 확인한다. 공개 Ingress는 생성하지 않는다. ALB 연결이 필요하면 Grafana Service 포트 `3000`을 담당자에게 전달하고 HTTPS·접속 제한을 별도 구성한다. Prometheus는 외부 공개하지 않는다.

## 추후 노드 분리·Argo CD

`new-node-values.yaml`은 미적용 대안이다. 사용하면 전용 `t3a.medium` On-Demand NodePool을 만들고 모니터링을 이동시킨다. 기존 NodeClass의 OS 4GiB+데이터 80GiB와 PVC 6GiB, 월 730시간 기준 총 추가 예상은 약 **$48.70/월**이다. EC2 $0.049/h, Auto Mode $0.00588/h, gp3 $0.096/GB-month로 계산했다. 이미 존재하는 PVC의 AZ와 새 노드 가용성을 확인하고 계획된 이동으로 진행한다. NodePool 한도는 순간적인 비용 상한을 보장하지 않는다.

Argo CD는 이번에 설치하지 않았다. WAS와 모니터링의 실제 사용량·API 배포 시 추가 Pod 여유를 확인한 뒤 배치를 정한다. 지금의 낮은 사용량만으로 부하 증가나 무중단 배포 여유까지 보장하지 않는다.

공식 근거: [Prometheus 저장](https://prometheus.io/docs/prometheus/latest/storage/), [Grafana provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/), [EKS Metrics Server](https://docs.aws.amazon.com/eks/latest/userguide/metrics-server.html), [도쿄 EC2/gp3 가격](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/ap-northeast-1/index.json), [도쿄 EKS 가격](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEKS/current/ap-northeast-1/index.json).
