# EKS Kafka·Connect

상태: 코드·로컬 검증 준비 / AWS·Kubernetes 미배포.

로컬 검증 결과: Helm/공식 CRD 검사, 잘못된 입력 18개 거부, Connect Linux/amd64 이미지 빌드 및 플러그인 발견 검사 통과. 임시 PostgreSQL→Kafka snapshot/insert/update/delete, Connect 중단 후 재전달, JMX/consumer lag 지표 노출도 확인했다. Terraform 10개 root/38 mock 통과. 실제 RDS/EKS 전달·AZ/디스크 장애 복구는 아직 확인하지 않았다.

후속으로 로컬 mTLS/hostname·ACL 허용/거부와 Kafka 컨테이너 재생성 후 메시지/Connect offset 보존·CDC 이어받기를 확인했다. [통합 검사](local-smoke/README.md), [자동 검사 코드](../../../.github/workflows/infra-checks.yml)를 준비했다. 원격 CI 실행 결과는 [통합 작업 기록](../../../docs/tasks/infra-local-ready.md)에서 확인한다. Connect 이미지 조치 후 [재검사](../../../docs/design/infra/connect-image-remediation-2026-10-14.md)는 Critical 0/High 35이며 잔여 취약점과 별도 broker/exporter 이미지 검토가 필요하다.

사용자 결정은 **EKS 자체 운영**이다. 공식 Strimzi 1.3.0 Helm chart, Kafka 4.3.1, PostgreSQL CDC용 Debezium 3.7.0.Final을 고정했다. Strimzi의 시험 범위 Kubernetes 1.32~1.37에 현재 EKS 코드의 1.36이 포함된다. Debezium 호환 표는 Kafka Connect 3.1 이상, PostgreSQL 14~18을 명시한다. 실제 조합의 실행 검증은 남아 있다. [Strimzi 버전 표](https://strimzi.io/downloads/), [Debezium 호환 표](https://debezium.io/releases/)

## 소유권과 구성

| 파일/단계 | 관리하는 것 | 선행 조건 |
|---|---|---|
| `operator-values.yaml` + 공식 chart | namespace 내 Strimzi 운영자, cluster 범위 CRD/RBAC | network → eks → compute, kubeconfig·관리 권한 |
| `storage-class.yaml` | Kafka 전용 Auto Mode gp3 StorageClass | Auto Mode EBS 및 암호화 권한 |
| [runtime chart](chart/README.md) | Kafka/NodePool, 명시적 Topic/User, 선택적 Connect | 운영자·CRD Ready, StorageClass, 실제 입력 |
| [Connect 이미지](connect-image/README.md) | PostgreSQL 플러그인이 포함된 Dockerfile | 로컬 Linux Docker, 이후 별도 레지스트리 |
| [검증](verify/README.md) | Helm 렌더·잘못된 입력·고정 CRD 검사 | Python 3.12, Helm 3; 최초 공식 artifact 다운로드 |

Terraform 스택의 EKS·NodeClass·NodePool·RDS·S3는 그대로 관리한다. 이번 Helm 리소스는 Terraform state에 넣지 않는다. 운영자와 runtime을 한 번에 설치하지 않는다. Helm은 CRD 업그레이드·제거를 자동 관리하지 않으므로 운영자 업그레이드 때 공식 마이그레이션 절차를 따른다. [Strimzi Helm 설치](https://strimzi.io/docs/operators/latest/deploying.html#deploying-cluster-operator-helm-chart-str)

## 실행 전 입력과 자원 영향

기본 chart는 Kafka/Connect 모두 비활성이다. 활성화하려면 Kafka 디스크 크기와 broker 기본 보존 시간을 명시한다. 업무 토픽마다 이름·partition·보존 시간을 지정하고, Producer/Consumer의 토픽 및 consumer group을 명시한다. 6개 토픽의 정확한 이름·키·파티션 계약은 팀과 확정해야 하므로 임의로 만들지 않았다. 추가 heartbeat/transaction 토픽을 쓰면 해당 토픽도 명시한다. 예시 파일의 이름·100Gi·24시간은 렌더 확인용이며 확정된 배포 사양이 아니다.

기본 구성은 broker/controller를 겸하는 3개 Kafka Pod, Connect 활성 시 2개 worker다. Kafka는 서로 다른 호스트와 2개 AZ에 배치하며 복제 3·min ISR 2를 사용한다. **2 AZ에 3개 controller를 분산하면 2개를 가진 AZ의 장애에서 과반수를 잃는다. 전체 AZ 장애 내성을 보장하지 않는다.** 목표가 모든 AZ 장애 극복이면 세 번째 AZ와 controller/broker 분리·용량 변경을 먼저 결정해야 한다. 호스트 장애·디스크 보존과 이 목표를 혼동하지 않는다.

Kafka request 합계는 1.5 vCPU/6Gi, Connect는 0.5 vCPU/2Gi다. 운영자 0.2 vCPU/384Mi 외에도 Entity Operator·시스템 Pod·WEB/WAS와 노드 예약량이 추가된다. broker 3호스트 요구 때문에 현재 2 vCPU 인스턴스라면 최소 3노드가 필요하다. 기존 공유 NodePool 상한 8 vCPU/32Gi는 변경하지 않았다. 이를 플랫폼 전체 충분 용량으로 보장하지 않으며 배포 전 allocatable·Pod 수·EBS 부착·IP 여유를 확인한다.

실제 활성화하면 노드 증가, broker당 EBS `storageGi`(합계 3배), AZ 간 복제 트래픽, 이미지 전송 비용이 발생할 수 있다. Retain 볼륨은 Pod/release 삭제 후에도 비용이 남는다. 이번 준비 작업 자체는 클라우드 자원을 생성하지 않았다.

## 보안과 데이터 보존

Debezium 기본 토픽 이름의 점·밑줄은 [chart의 `resourceName`](chart/README.md)으로 Kubernetes 리소스 이름과 분리할 수 있다. [로컬 CDC 검사](local-smoke/README.md)는 임시 DB에서 실제 전달과 재시작 후 전달을 확인하며 EKS/RDS 검증을 대체하지 않는다.

- Kafka client listener는 내부 9093만 제공하며 TLS 서버 인증과 client 인증서 인증을 요구한다. 외부 LoadBalancer·Ingress·평문 listener를 만들지 않는다.
- User Operator가 KafkaUser와 같은 이름의 TLS Secret(`user.crt`, `user.key`, `ca.crt` 등)을 `kafka` namespace에 만든다. Connect는 자신의 Secret와 cluster CA를 직접 참조한다. 업무 클라이언트 ACL은 literal topic/group만 허용한다. `IdempotentWrite`는 Kafka가 요구하는 cluster 범위 작업이며 관리자 권한을 부여하지 않는다.
- broker listener의 NetworkPolicy는 지정한 client namespace와 Connect Pod만 허용한다. NetworkPolicy는 Strimzi가 생성하며 실제 CNI의 적용을 확인해야 한다. 다른 namespace의 Consumer/Producer는 TLS Secret을 그 namespace에 공급할 별도 절차가 필요하다. 이 chart는 인증서를 복사하거나 모든 Secret 조회 RBAC를 주지 않는다.
- Connect REST는 기본 내부 Service이며 Strimzi의 NetworkPolicy를 유지한다. `KafkaConnector` CR 관리만 켜고, 담당자에게 필요한 namespace RBAC만 별도로 부여한다. REST·Connector 쓰기 권한은 DB 자격증명 사용 권한과 함께 취급한다.
- Connect에는 `cdc-database` Secret의 `username`, `password` 키와 `rds-ca` Secret의 `bundle.pem` 키를 외부 절차로 준비한다. master Secret을 연결하지 않는다. Secret 원문은 Git·Helm values·명령행에 넣지 않는다. 이 구성은 Secrets Manager 자동 동기화 기능을 구현하지 않는다.
- CDC 담당자의 Connector 설정에서 `database.user`는 `${directory:/mnt/cdc-database:username}`, `database.password`는 `${directory:/mnt/cdc-database:password}`를 참조하고 `database.sslmode=verify-full`, `database.sslrootcert=/mnt/rds-ca/bundle.pem`을 사용한다. DB host/name·allowlist·slot/publication은 담당자 입력이다. 공급한 CA·hostname 검증과 Secret 교체 후 재시작/재연결은 실배포 검증 대상이다.
- EBS는 Auto Mode 전용 provisioner, gp3, 암호화, WaitForFirstConsumer, Retain을 사용한다. Kafka `deleteClaim=false`로 PVC를 보존한다. Retain은 백업·다른 AZ 복구를 대신하지 않는다. [AWS StorageClass 안내](https://docs.aws.amazon.com/eks/latest/userguide/create-storage-class.html)
- Connect 내부 3개 토픽은 RF 3/min ISR 2/compact, 각 1 partition이다. offset·config·status 토픽 이름을 재사용·변경하거나 삭제하면 복구에 영향을 주므로 일반 업무 토픽과 분리한다.

## 배포 PC에서의 순서

아래는 사용자가 배포 환경에서 검토 후 실행할 절차다. 이 PC에서는 실행하지 않았다. 우선 최신 main 반영·대상 kube-context·동일 이름 리소스/운영자 부재를 확인한다. 기존 자원이 있으면 중복 설치하거나 자동으로 인수하지 않는다.

1. 기존 Terraform network/eks/compute를 준비하고 노드 예산을 확인한다. RDS 설정·버전·전용 복제 계정·CA·publication/slot/allowlist는 CDC 담당자와 준비한다. 실제 논리 복제 설정 적용 상태를 확인한다.
2. [로컬 검증](verify/README.md)을 실행하면 공식 chart/CRD가 checksum 확인 후 `.cache/kafka-verify/`에 저장된다. 저장소 루트에서 운영자와 StorageClass를 별도 설치한다.

```powershell
helm upgrade --install strimzi .cache/kafka-verify/strimzi-kafka-operator-helm-3-chart-1.3.0.tgz --namespace kafka --create-namespace --values infra/platform/kafka/operator-values.yaml --wait --timeout 10m
kubectl wait --for=condition=Established crd/kafkas.kafka.strimzi.io crd/kafkanodepools.kafka.strimzi.io crd/kafkaconnects.kafka.strimzi.io crd/kafkatopics.kafka.strimzi.io crd/kafkausers.kafka.strimzi.io --timeout=120s
kubectl apply -f infra/platform/kafka/storage-class.yaml
```

3. `runtime-values.yaml.example`을 무시되는 `runtime.local.yaml`로 복사해 실제 계약·용량·보존 값을 작성한다. 처음에는 `connect.enabled=false`로 Kafka·업무 토픽·클라이언트만 준비한다. `helm template`과 diff를 검토한 뒤 runtime을 설치한다.

```powershell
helm template cq-kafka infra/platform/kafka/chart --namespace kafka --values infra/platform/kafka/runtime.local.yaml
helm upgrade --install cq-kafka infra/platform/kafka/chart --namespace kafka --values infra/platform/kafka/runtime.local.yaml --wait --timeout 15m
kubectl wait --for=condition=Ready kafka/clothes-query-dev-kafka --namespace kafka --timeout=15m
kubectl get kafkatopics,kafkausers,pvc --namespace kafka
```

Helm `--wait`만으로 custom resource Ready가 보장되지는 않는다. `kubectl wait`와 status/observedGeneration을 확인하고, 각 topic/user Ready·3개 서로 다른 호스트·AZ 배치·PVC Binding을 확인한다. bootstrap 주소는 기본 이름 기준 `clothes-query-dev-kafka-kafka-bootstrap.kafka.svc:9093`이다. namespace/토픽 권한 없는 접근이 거부되는지도 확인한다.

4. 별도 승인된 이미지 배포 절차로 Connect 이미지를 빌드·스캔·레지스트리에 저장하고 받은 digest를 `connect.image`에 작성한다. DB/CA Secret 준비 후 명시적 `connect.produceTopics`와 함께 Connect를 활성화한다. 동일 runtime release를 upgrade하고 Connect Ready·내부 토픽 Ready·플러그인 목록을 확인한다. 토픽/인증서 생성 순서 때문에 초기 reconciliation이 재시도될 수 있으므로 최종 Ready를 확인한다. CDC 담당자가 별도 관리하는 KafkaConnector를 등록한다.
5. DB 변경 한 건 → Kafka 전달을 확인한다. Consumer를 연결한 뒤 Bronze 적재와 재시작 재처리·consumer lag·WAL/slot 지연·디스크/ISR/quorum 경보를 확인한다. [지표 노출·수집 연결 예시](metrics/README.md)는 준비했으며 수집 서버·경보 전달과 Consumer 배포는 포함하지 않았다.

이미 배포한 release에서 `enabled=false`, 이름 변경, 일반적인 `helm uninstall/rollback`을 단순 롤백으로 사용하지 않는다. CR 삭제·topic 삭제·재처리 영향이 있으므로 데이터·PVC·slot·offset 보존 및 복구 계획을 확인한다. Helm release를 지워도 보존된 EBS/PVC는 수동 복구·정리 대상이다. 운영자 제거는 모든 관리 대상 runtime을 정리하거나 보존 계획을 확인한 뒤 진행한다.
