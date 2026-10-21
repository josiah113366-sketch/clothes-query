> **실제 배포(2026-10-16):** 프라이빗 EKS Auto Mode의 `t3a.large` 한 대에서 단일 노드 Kafka 측정 구성을 확인했다. 용량 한도는 6 vCPU/24GiB(세 대분)다. NAT 1개를 공유한다. 제네레이터는 팀원이 ECS Fargate로 구성한다. Airflow는 namespace만 준비했으며 전체 플랫폼 한 대 수용은 미검증이다. WEB/WAS·ALB·Spark는 이번 최소 배포에서 제외한다.

## 최소 구성의 노드 확장

NodePool은 replicas/minimum을 예약하지 않는다. Pod requests와 배치 제약 때문에 기존 노드에 배치할 수 없는 Pod가 생기면 Auto Mode가 용량 한도 안에서 노드를 추가한다. 실제 CPU 사용률이나 Kafka lag만으로 broker/Connect replica가 늘어나는 구조는 아니다. `WhenEmptyOrUnderutilized`와 `consolidateAfter=10m`을 유지하며 PDB·배치·교체 조건에 따라 축소가 지연될 수 있다.

Kafka/Connect/운영자의 메모리 request 3456Mi와 별도 시스템 자원을 t3a.large 한 대에서 수용하는 것이 목표이며 실제 EKS 검증은 남아 있다. Fargate 제네레이터 자원은 이 풀과 별개다. 두 AZ는 배치 가능한 범위이지 노드를 각 AZ에 하나씩 강제하는 설정이 아니다. 단일 Kafka PVC의 AZ와 시스템 Pod의 배치 조건 때문에 추가 노드가 필요할 수 있다. 기본 standard Kafka나 WEB/WAS 배치를 활성화하면 한 대 목표가 성립하지 않는다.

6 vCPU/24GiB는 세 대분의 용량 한도이며 동시 provisioning 중 일시 초과할 수 있어 엄격한 노드 수/비용 상한은 아니다. t3a는 CPU credit 잔고·사용량·추가 과금 또는 throttling도 관측해야 한다. [AWS Auto Mode 지원 타입](https://docs.aws.amazon.com/eks/latest/userguide/automode-learn-instances.html), [NodePool limits](https://karpenter.sh/docs/concepts/nodepools/#speclimits).

아래 WEB/WAS HPA 내용은 추후 앱을 배포할 때 사용하는 별도 설계다. 현재 최소 실행의 활성화 기준이 아니다.

# Generator 부하에 따른 확장·축소

상태: 결정 — WAS HPA 사용. 코드만 준비했으며 실제 생성·부하 테스트는 마지막에 진행한다.

| 항목 | 설정 | 입력 |
|---|---|---|
| WEB | 2개 고정 | apps workload_settings.web.replicas |
| WAS | HPA 최소 2, 최대 3 | apps was_autoscaling |
| CPU 목표 | requests 대비 70% | target_cpu_utilization |
| 축소 안정화 | 300초 | scale_down_stabilization_seconds |
| Pod 기본 자원 | CPU 요청 100m/한도 500m, 메모리 요청 128Mi/한도 512Mi | workload_settings |
| 노드 풀 한도 | 현재 6 vCPU/24 GiB, t3a.large. 앱 활성화 전 재산정 | compute node_pool_cpu_limit/node_pool_memory_limit_gib |
| 노드 정리 대기 | 10분 | compute consolidate_after |

HPA는 WAS Pod 수를, Auto Mode는 노드 용량을 조절한다. WEB replica는 Terraform이 관리한다. WAS Deployment는 spec[0].replicas 변경을 무시하여 HPA와 충돌하지 않는다. WAS 수는 workload_settings.was.replicas 대신 아래 HPA 입력으로 바꾼다.

```hcl
was_autoscaling = {
  min_replicas = 2
  max_replicas = 3
  target_cpu_utilization = 70
  scale_down_stabilization_seconds = 300
}
workload_settings = {
  web = { replicas = 2 }
  was = {
    cpu_request_millicores = 100
    cpu_limit_millicores = 500
    memory_request_mib = 128
    memory_limit_mib = 512
  }
}
```

apps의 deployment.local.tfvars 또는 기존 deployment.local.tfvars.json에 병합한다. 동일 변수를 여러 입력 파일에 중복 설정하지 않는다. 최종 배포 때 해당 파일로 plan을 검토한다.

## 무엇을 측정할까

현재 시뮬레이터는 PostgreSQL에 직접 쓰는 설계다. 이 부하는 WAS HPA로 해결되지 않는다. WAS 자동 확장은 API 호출로 테스트해야 한다. Fargate Generator 용량과 Kafka consumer lag는 별도다.

70%는 CPU requests 대비 비율이다. 기본 100m에서는 70m이 목표이므로 실제 사용량에 맞춰 requests와 목표를 함께 조정한다. CPU가 낮은 DB 대기 병목에서는 HPA가 늘어나지 않을 수 있다.

| 관찰 | 조치 |
|---|---|
| WAS CPU 포화, HPA 최대치, DB 여유 | HPA 상한·CPU 자원 검토 |
| OOM | 누수·배치 크기 확인 후 메모리 조정 |
| Pending, 풀 한도 도달 | compute 한도와 교체 여유 확인 |
| Pending, 자원 여유 | AZ/anti-affinity, 이미지/Secret, IP/IAM/quota 확인 |
| RDS 연결·IO·lock 병목 | 쿼리·인덱스·연결 풀·동시성 검토 |
| Generator만 포화 | Generator 용량·전송 경로 확인 |
| 부하 하락, 지연·오류 안정 | HPA 축소 후 노드 정리 관찰 |

목표 RPS·p95·오류율·예산을 정하고 낮은 부하부터 단계적으로 올린다. 실제 처리량, CPU/메모리/throttling, Pending, RDS 연결·대기·IO를 함께 기록한다. 한 번에 병목 한 곳만 조정한다.

## 용량과 축소 주의점

WAS는 anti-affinity 때문에 Pod마다 다른 노드가 필요하다. WEB과 WAS는 노드를 공유할 수 있다. HPA 최대 3개에서 rollout surge까지 고려하면 네 번째 노드가 필요할 수 있다. 장애·교체·시스템 Pod와 겹치면 현재 한도에서 Pending이 생길 수 있다. HPA 상한을 늘리기 전에 compute 한도와 DB 연결 풀 총량을 검토한다. 필요하면 12 vCPU/48 GiB 등으로 조절하되 비용 증가를 검토한다.

부하가 줄면 HPA는 300초 안정화 창을 거쳐 최소 2개까지 축소한다. 확장·축소 정책은 각각 60초당 최대 1개다. 정확히 5분 뒤 축소되는 보장은 없다. 이후 Auto Mode는 기본 10분 대기와 consolidation 검토를 거쳐 노드를 정리한다. PDB·분산 조건·교체 용량이 축소를 막을 수 있다. [Kubernetes HPA](https://kubernetes.io/docs/concepts/workloads/autoscaling/horizontal-pod-autoscale/), [AWS consolidation](https://docs.aws.amazon.com/eks/latest/userguide/auto-cost-control.html)

노드 한도를 낮추는 것만으로 기존 노드가 즉시 줄지는 않는다. 6 vCPU/24 GiB는 기본 타입 약 3대분이라 HPA 최대치에서 rollout 여유가 부족할 수 있다. 노드를 콘솔에서 강제 종료하지 않는다. 풀 한도는 엄격한 실시간 비용 상한이 아니며 EKS·NAT·RDS 고정 비용은 남는다. [NodePool limits](https://karpenter.sh/docs/concepts/nodepools/#speclimits)

## 마지막 배포 검증

Metrics Server는 apps 기초 단계에서 EKS community add-on으로 준비한다. 호환 기본 버전을 조회하며 최종 plan에서 확인한 버전을 metrics_server_version으로 고정할 수 있다. 기존 설치가 있으면 관리 상태부터 확인한다. 충돌 정책 NONE으로 강제 덮어쓰기를 방지한다. 장기 지표 저장용 모니터링은 별도다. [AWS Metrics Server](https://docs.aws.amazon.com/eks/latest/userguide/metrics-server.html)

```powershell
kubectl get deployment metrics-server -n kube-system
kubectl top nodes
kubectl top pods -n clothes-query
kubectl get hpa -n clothes-query
kubectl describe hpa was -n clothes-query
kubectl get pods -n clothes-query -o wide
kubectl get nodes -L topology.kubernetes.io/zone
kubectl get nodepools,nodeclaims
kubectl get pdb -n clothes-query
kubectl get events -n clothes-query --sort-by=.lastTimestamp
```

지표 수집, HPA AbleToScale/ScalingActive, API 부하에 따른 2→3→2 변화와 후속 Terraform plan의 WAS replica 비간섭을 확인한다. 지표가 unavailable이면 Metrics Server 상태와 노드 10250 통신을 점검한다. 로컬 mock 테스트는 실제 스케줄링·지표 수집·자동 확장을 검증하지 않는다.
