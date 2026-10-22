# 기존 WAS 노드에 Argo CD 설치

상태: 실제 설치·로그인·저장소·권한·부하 검증 완료, 로컬 브랜치 보관

## 결정

사용자가 모니터링과 WAS를 함께 관찰한 뒤 Argo CD 설치를 요청했다. 기존 WAS 노드에 별도 namespace로 설치하고 빌드는 GitHub Actions에 둔다. 별도 노드·ALB·PVC 생성이나 기존 앱의 자동 배포·삭제·PR 자동 머지는 하지 않는다.

## 완료 확인

- [x] 최신 main `013264d`에서 전용 브랜치 생성, 기존 작업 브랜치 보존.
- [x] 실제 WAS 노드 CPU 약 5%·메모리 33%, 예약량·WAS surge Pod 한 개 여유 확인.
- [x] 공식 chart 10.10.5 체크섬과 Argo CD 3.5.6/Redis image digest 고정.
- [x] Helm 렌더 42개 객체, 실행 Pod 4개·275m/704MiB, 신규 인프라·Application 미생성 검사.
- [x] 서버 측 dry-run 통과.
- [x] 실제 설치와 WAS/기존 모니터링 정상 유지 검증.
- [x] 로그인·저장소 연결·권한 범위·노드 수 검증.

## 작업 결과

`infra/platform/argocd`에 고정 chart 다운로드·검사, 작은 개발 values, WAS 권한, AppProject를 준비했다. 기존 `api/deploy/chart` 전체를 바로 가져오면 클러스터 인프라와 Helm 소유권이 겹치므로 Application을 등록하지 않는다. 앱 배포 소유권 전환·이미지 digest 갱신·자동 sync 설정은 후속이다.

인증 값은 Kubernetes Secret에만 남기고 출력·파일·커밋하지 않는다. 앱 코드·업무 DAG·데이터는 변경하지 않는다. 원격 push·PR·머지는 하지 않는다.

Helm 설치 후 Argo CD 4개 Pod 모두 Ready/restart 0, 기존 노드 2개 유지, WAS Deployment spec과 Pod UID 불변을 확인했다. 자체 서명 인증서를 신뢰 저장소에 넣은 HTTPS 클라이언트로 admin 로그인, 저장소 연결 Successful, Application 0개와 default/was 프로젝트를 확인했다. 컨트롤러의 api Deployment 변경 허용, api Secret 직접 조회·kafka Deployment 변경·NodePool 생성 거부와 server의 api 조회만 허용을 실제 권한 검사 6개로 검증했다.

클러스터 상태 Unknown의 메시지는 `Cluster has no applications and is not being monitored.`였다. 앱이 없어 감시하지 않는 상태이며 실제 Application sync 성공을 검증했다는 뜻으로 보고하지 않는다. 빈 Application 목록이 JSON `items: null`로 반환되어 첫 검증 스크립트가 실패했고, null을 빈 목록으로 처리한 뒤 전체 검증을 통과했다. 이 과정에서 서비스 설정 변경은 없었다.

설치 후 1분간 30초 간격 3회 관찰: WAS CPU 14.9~19.9m/메모리 56.9~57.4MiB, Argo CD 합계 CPU 5.9~12.1m/메모리 101.4~104.1MiB. 노드 전체 CPU는 allocatable 1780m 대비 4.6~5.6%, 메모리는 3251MiB 대비 40.7%였다. 업무 요청 143건 증가·HTTP 5xx 증가 0건·histogram sum/count 차이 기준 평균 6.66ms, readiness 3회 200, Prometheus 대상 5개 모두 up, Grafana database ok를 확인했다. 앱이 없는 Argo CD의 대기 상태 관찰이므로 실제 렌더링·sync 부하와 최대 용량을 보증하지 않는다.

공식 chart SHA256 대조·Helm lint·구성/범위 검사·workflow read-only 권한/YAML 및 Python 문법 검사·git diff 공백 검사를 통과했다. 원격 GitHub Actions 실행은 아직 하지 않았다.
