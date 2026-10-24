# 노드 수와 자원 사용량

기존 Grafana의 `Infrastructure` 폴더 → `Clothes Query - Infrastructure` 대시보드 맨 위에 노드 패널 7개를 추가한다.

| 패널 | 의미 |
|---|---|
| Node count | 현재 등록된 전체 노드 수 |
| Ready nodes | Ready=True 노드 수 |
| Nodes by pool | API·공용·Spark 등 노드풀별 수와 변화 |
| Node CPU used / allocatable | kubelet의 노드 전체 CPU 사용률 |
| Node memory working set / allocatable | 시스템 포함 노드 메모리 working set 비율 |
| Node container CPU requests / allocatable | 현재 Running/Pending Pod의 컨테이너 CPU 예약 비율 |
| Node container memory requests / allocatable | 현재 Running/Pending Pod의 컨테이너 메모리 예약 비율 |

사용률 분모는 인스턴스 전체 사양이 아니라 Kubernetes allocatable이다. 시스템 사용분도 포함하므로 100%를 넘을 수 있다. `kubectl top`과는 측정 시점·평균 구간이 다르므로 완전히 같을 필요는 없다.

예약 패널은 일반 컨테이너 request 합계다. init-container 최대값·Pod overhead·sidecar 초기화 규칙·taint·affinity·볼륨 조건을 모두 계산한 스케줄러 가용량이 아니다. request가 낮아도 실제 사용량이 클 수 있으므로 두 패널을 함께 본다.

## 수집과 비용

- kubelet `/metrics/resource`에서 CPU counter와 메모리 working set 두 종류만 보관한다. TLS 검증을 유지하며 Prometheus에는 nodes 조회와 nodes/metrics GET만 추가한다. node proxy·Secret·쓰기 권한은 주지 않는다.
- 공식 kube-state-metrics v2.20.0을 불변 digest로 고정하고 nodes/pods 조회·watch 및 필요한 지표만 사용한다. Secret이나 업무 데이터는 수집하지 않는다.
- 새 Pod 한 개는 기존 API 노드에 CPU 25m/메모리 64MiB를 예약한다. 새 EC2·ALB·PVC·DaemonSet은 없다. 기존 스크랩·경보·이미지·자원·Secret은 유지한다.
- 60초마다 수집한다. CPU는 첫 두 번 이상 수집 후 표시된다. 기존 Prometheus 보관 설정 48시간/1GB 중 먼저 도달하는 한도를 적용하며 무제한 이력이 아니다. 추가 수집/저장 비용이 완전히 0이라는 보장은 아니다.
- 시계열이 없으면 수집 target을 확인한다. 수집 장애를 CPU 0 또는 노드 0으로 바꾸지 않는다. kube-state-metrics 장애 시 노드 수 패널도 No data가 된다.

`nodeMetrics.enabled=false`로 새 수집과 관련 RBAC를 끌 수 있다. 노드 패널은 No data가 되며 기존 Kafka/WAS 패널은 유지된다.

공식 근거: [kube-state-metrics](https://github.com/kubernetes/kube-state-metrics), [Node 지표](https://github.com/kubernetes/kube-state-metrics/blob/main/docs/metrics/cluster/node-metrics.md), [Pod 지표](https://github.com/kubernetes/kube-state-metrics/blob/main/docs/metrics/workload/pod-metrics.md).
