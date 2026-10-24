# 노드 모니터링 연결

2026-10-24 사용자 승인으로 기존 Grafana Infrastructure 대시보드에 노드 패널 7개를 추가했다.

## 적용

- 기존 Helm release와 실제 override를 보존했다. 기존 Pod 이미지·자원·PVC·알림·Secret을 바꾸지 않았다.
- 공식 kube-state-metrics v2.20.0을 registry 응답 SHA-256으로 확인해 고정했다. 기존 API 노드에 25m/64MiB Pod 1개만 추가했다.
- nodes/pods list/watch 및 Prometheus의 nodes/metrics GET·노드 발견 권한만 추가했다. nodes/proxy·Secret·쓰기·관리 권한은 없다.
- kubelet TLS 검증을 유지하고 노드 CPU counter·메모리 working set만 60초마다 수집한다. node-exporter DaemonSet·추가 EC2·ALB·PVC는 없다.
- 새 리소스 7개와 기존 ConfigMap 2개·checksum에 따른 모니터링 Deployment 3개의 재시작만 변경됐다. Alertmanager·업무 Pod는 재시작하지 않았다.

## 확인

- Helm 렌더/RBAC/TLS/옵션 경계 검사, 모니터링 회귀 15개, 실제 Prometheus promtool 설정 검사, server dry-run을 통과했다.
- Helm upgrade 완료 후 모든 노드 수집 target과 state 수집 target의 health=up을 확인했다.
- Grafana API에서 기존 uid의 대시보드가 노드 패널 7개·총 17개 패널을 실제로 로딩한 것을 확인했다. 비밀번호·토큰은 출력하거나 공유하지 않았다.
- 실제 PromQL에서 노드 수·Ready 수·풀별 대수·메모리·컨테이너 예약량과 CPU rate를 확인했다. CPU는 각 노드에서 두 번 이상 수집돼야 표시된다.
- 데이터는 적용 시점부터 쌓이며 과거 노드 증감 이력은 소급 생성하지 않는다. 기존 48h/1GB 보관 한도를 유지했다.

## 함께 확인한 증설 원인

대시보드 통합 후 19:20:02 KST의 agent-detection Pod가 Insufficient cpu로 대기했고, 19:20:03 추가 공용 NodeClaim이 지명돼 19:20:22 새 노드에 배치됐다. 이 노드는 모니터링 배포 준비 전에 이미 생겼고 Helm 적용 전후 노드 UID 집합은 동일했다. 모니터링이 새 노드를 생성한 것으로 표현하지 않는다.

이후 노드 수가 다시 4로 보일 수 있다. 기존 공용 노드 CPU 예약 1550m/1780m와 판정 요청을 함께 고려해야 하며 CPU 실제 사용량만으로 증설 원인을 판단하지 않는다. 예약량/배치 조정은 이번 감시 연결과 분리한다.

예약 패널은 일반 컨테이너 합계로 init-container·overhead·affinity 등 스케줄러 전체 조건을 계산하지 않는다. 자세한 화면 안내와 한계는 [NODE_METRICS.md](../../infra/platform/monitoring/NODE_METRICS.md)를 따른다.
