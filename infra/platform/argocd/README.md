# 개발용 Argo CD

Argo CD를 기존 WAS 노드풀 `clothes-query-dev-api`에 배치한다. WAS 앱 내부에서 실행하는 것이 아니라 `argocd` namespace의 별도 Pod로 실행한다. GitHub Actions가 이미지 검사·빌드·ECR 업로드를 맡고 Argo CD는 Git에 기록된 배포 상태를 반영하는 구분이다. 현재는 Argo CD 설치와 저장소 조회 기반만 준비한다.

## 설치 구성

- 공식 Helm chart **10.10.5**, Argo CD **3.5.6**, Redis **8.6.4-alpine**. 공개 릴리스의 chart SHA256과 공식 image digest를 고정했다. chart 기본 appVersion 3.5.5 대신 당시 최신 안정판 3.5.6을 지정했다.
- controller·server·repo-server·Redis 총 4개 Pod. 요청량 합계 **275m CPU / 704MiB memory**. Dex·알림은 비활성, ApplicationSet Deployment는 upstream chart에 enabled 옵션이 없어 replicas 0이다.
- SSO·HA·외부 Ingress·PVC·새 EC2·AWS IAM 자격증명을 추가하지 않는다. 서버 TLS와 로그인을 유지하며 포트포워딩으로 접속한다.
- Redis는 임시 캐시다. Pod 교체 시 캐시가 사라져도 Application/AppProject는 Kubernetes CRD, 설정·인증은 Kubernetes ConfigMap/Secret에 남는다. CRD는 chart uninstall 시 보존한다. namespace 삭제는 별도 위험한 작업이다.
- 기존 노드 자원을 쓰므로 추가 EC2 고정비는 없다. 이미지 pull/NAT 전송·AZ 간 통신은 사용량에 따라 추가된다. 자원 부족 시 느려지거나 Pending/OOM이 발생할 수 있고, 단일 노드 장애가 WAS·모니터링·Argo CD에 같이 영향을 준다.

설치 직전 WAS 노드의 예약 여유는 980m/2099MiB였다. Argo CD와 추가 WAS Pod 1개(500m/256MiB)를 함께 예약해도 약 **205m/1139MiB**가 남았다. 이 값은 스케줄링 요청량 계산이며 실제 최대 부하·무중단 배포 성공을 보장하지 않는다.

## 배포 권한과 현재 경계

`was-access.yaml`은 controller에 `api` namespace의 Deployment·Service·ConfigMap·Ingress 변경과 관련 상태 조회를 허용한다. server는 같은 대상 조회만 한다. 다른 namespace 배포, Secret 직접 조회, RBAC·ServiceAccount·NodePool·NodeClass·CRD 변경은 허용하지 않는다. Deployment 변경 권한은 기존 앱 Secret을 사용하는 코드를 실행할 수 있는 권한이기도 하므로 데이터 접근의 절대적인 격리 경계로 보지 않는다.

cluster-wide 권한은 namespace/CRD 발견용 조회로 제한했다. 로컬 클러스터 등록은 `api` namespace만 대상으로 하고 별도 bearer token을 저장하지 않는다. repo-server/Redis에는 Kubernetes API token을 자동 마운트하지 않는다.

`projects.yaml`은 default 프로젝트를 닫고, `was` 프로젝트에 저장소 하나·대상 namespace `api`·앱 리소스 4종만 허용한다. **Application은 만들지 않으므로 기존 WAS의 배포 소유권을 가져오거나 자동 sync/prune/self-heal을 시작하지 않는다.**

현재 `api/deploy/chart`에는 NodePool·IngressClass·IngressClassParams도 들어 있고 Git 제외 runtime 값도 필요하다. 이 chart 전체를 그대로 Application에 등록하면 안 된다. 앱/인프라 관리 경계, 이미지 digest 공급, 기존 Helm release 소유권 전환을 정한 뒤 첫 Application을 만든다. Terraform·Kafka·Airflow 전체를 Argo CD에 넘기는 작업도 이번 범위가 아니다.

## 로컬 검사와 재현

```powershell
python -m pip install -r infra/platform/argocd/requirements.txt
python infra/platform/argocd/check.py --helm <helm 경로> --output .cache/argocd-rendered.private.yaml
```

공개 chart 다운로드·체크섬·렌더·4개 실행 Pod 자원·기존 WAS 노드 지정·최소 cluster 권한·앱 미등록을 확인한다. AWS 인증·로컬 Docker는 필요 없다. `.github/workflows/argocd-checks.yml`도 같은 검사만 수행하며 배포하지 않는다.

초기 설치 시 `argocd` namespace와 `argocd-redis` Opaque Secret(`auth` 키의 무작위 비밀번호)을 메모리/표준입력으로 준비한다. 비밀을 Helm values나 Git에 넣지 않는다. 설치 명령은 다음과 같다.

```powershell
kubectl apply --dry-run=server -f infra/platform/argocd/was-access.yaml
kubectl apply -f infra/platform/argocd/was-access.yaml
helm upgrade --install argocd .cache/argo-cd-10.10.5.tgz --namespace argocd -f infra/platform/argocd/development-values.yaml --atomic --wait --timeout 5m
# 최초 설치이며 default 프로젝트를 쓰는 Application이 없는지 먼저 확인한다.
kubectl get applications.argoproj.io -A
kubectl apply -f infra/platform/argocd/projects.yaml
```

다른 Argo CD/CRD/Helm release가 이미 있으면 덮어쓰지 말고 소유권을 확인한다. 실제 Secret과 Helm dry-run 전체 출력은 커밋하지 않는다. chart는 `check.py`가 `.cache`에 다운로드한다.

## 접속

```powershell
kubectl -n argocd port-forward svc/argocd-server 18443:443
```

브라우저에서 **https://localhost:18443**, ID **admin**을 사용한다. 처음에는 자체 서명 인증서 경고가 나올 수 있다. 초기 비밀번호는 본인 PowerShell에서만 조회한다.

```powershell
$encoded = kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}'
[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($encoded))
```

비밀번호를 변경했다면 initial-admin-secret 값은 현재 비밀번호가 아닐 수 있다. 변경·초기 Secret 삭제는 별도 운영 절차로 진행한다. UI에 Applications가 비어 있는 것은 이번 단계에서는 정상이다. Settings → Repositories에서 저장소 연결 상태를 본다. 아직 GitHub webhook이나 ECR push가 자동 배포를 시작하지 않는다.

Application이 0개인 현재 로컬 클러스터는 `Unknown / Cluster has no applications and is not being monitored.`로 표시된다. 저장소 연결 Successful·로그인·Kubernetes 권한 검사는 통과했지만 실제 앱 sync는 아직 검증하지 않았다.

## 후속

첫 WAS Application을 구성할 때 소유권 전환과 수동 sync를 검증하고, 이후 main 머지 → Actions 빌드/ECR push → Git의 digest 갱신 → Argo CD sync 흐름을 연결한다. 자동 sync·prune 여부와 접근 도메인은 별도로 결정한다. 알림 채널이나 팀원 메시지는 이번 설치에서 발송하지 않는다.

공식 근거: [Argo Helm chart](https://github.com/argoproj/argo-helm/tree/argo-cd-10.10.5/charts/argo-cd), [Argo CD 3.5.6](https://github.com/argoproj/argo-cd/releases/tag/v3.5.6), [선언적 설정](https://argo-cd.readthedocs.io/en/stable/operator-manual/declarative-setup/), [프로젝트 범위](https://argo-cd.readthedocs.io/en/stable/user-guide/projects/).
