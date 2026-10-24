# 기존 WAS 노드에 개발용 모니터링 추가

상태: 실제 설치·수집 검증 및 2분 WAS 관찰 완료, 로컬 브랜치 보관

## 결정과 범위

사용자는 추가 모니터링을 요청했고, 전용 노드 대안을 검토한 뒤 기존 WAS 노드 공유 가능 여부와 실제 부하 우선 확인을 요청했다. 전용 노드는 생성하지 않았다. Argo CD 설치·PR 자동 머지는 하지 않는다.

처음에는 예약 자원 여유만 보고 배포를 시작했다. 설치 전 CPU/메모리 실측이 없으므로 추가 전후 성능 비교는 불가능하다. 이후 Metrics Server가 준비된 시점부터 실제 부하를 관찰하며 WAS 안정성을 확인한다. 이번 관찰은 일반 트래픽 중의 짧은 표본이며 부하 시험이 아니다.

## 완료 확인

- [x] Helm 렌더/lint, default namespace 거부, digest 고정, 신규 NodePool 기본 미생성 확인.
- [x] 공식 promtool 설정·경보 문법, 대상 소실/일시 오류/지속 오류 경보 시험.
- [x] 서버 dry-run 후 기존 WAS 노드에 세 Pod 설치, 모두 Ready. 노드 수 2개 유지.
- [x] Metrics API Available 및 `kubectl top` 동작 확인.
- [x] 기존 Kafka·Connect·lag·WAS 지표 HTTP 응답과 실제 metric 이름 확인.
- [x] Prometheus 대상 5개 모두 up, 경보 규칙 7개 health ok/inactive, Grafana database ok.
- [x] 사용자가 요청한 추가 2분 WAS 사용량·오류·응답 관찰 기록.

## 작업 결과

`infra/platform/monitoring`에 자체 Helm chart·수집 설정·10개 패널·7개 경보 규칙과 검사 코드를 추가했다. Grafana 인증 비밀은 monitoring namespace의 전용 Secret에만 생성했다. Secret 값은 출력·파일 저장·커밋하지 않았다. PVC 총 6GiB 외에 새 EC2/ALB/RDS/NAT는 생성하지 않았다.

CPU/메모리 이력의 Grafana 통합, RDS/WAL·S3 도착·Airflow 업무 상태·외부 알림은 후속이다. 앱 코드·업무 DAG·SQL을 변경하지 않았다. 원격 GitHub Actions 실행·push·PR·머지는 하지 않았다.

2026-10-22 13:27:38~13:29:38 KST에 30초 간격 5회 관찰했다(마지막 조회 종료까지 124.8초). WAS CPU 44.9~66.5m, 메모리 56.7~57.1MiB. 모니터링을 포함한 WAS 노드 전체 CPU는 allocatable 1780m 대비 5.6~8.0%, 메모리는 3251MiB 대비 31.1~31.3%였다. 모니터링 3개 Pod 합계는 CPU 16.4~22.1m, 메모리 262.0~263.9MiB였다.

healthz/readyz/metrics를 제외한 업무 요청 카운터는 1,190건 증가했고 HTTP 5xx 증가 0건, 같은 기간 histogram sum/count 차이 기준 평균 처리 시간은 7.42ms였다. 5회 readiness 응답은 모두 200이다. 이 결과는 설치 후 당시 일반 트래픽의 짧은 관찰이며 최대 처리량, 설치 전후 영향, 향후 Argo CD 동거 가능 여부를 보증하지 않는다.
