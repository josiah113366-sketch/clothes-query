# 대시보드 배포 (EKS)

앱 소스는 [`dashboard/`](../../../dashboard/README.md)에 있고, 이 폴더는 배포용 파일만 둔다. 외부 접속(ALB)은 [`../ingress`](../ingress/README.md)의 공유 ALB가 맡으므로 여기에는 Ingress가 없다(`dashboard:8501`로 연결).

| 파일 | 내용 |
|---|---|
| `Dockerfile`, `Dockerfile.dockerignore` | 이미지 빌드(컨텍스트는 저장소 루트). `dashboard/`와 재처리 승인 화면이 쓰는 `agent/approval/approval.py`·`agent/detect/athena_io.py`만 들어간다. 계정 파일(`.local/`)과 비밀값은 제외 |
| `k8s/namespace.yaml` | namespace `dashboard` (공유 ALB 라벨 포함) |
| `k8s/deployment.yaml` | 파드 1개, `AUTH_MODE=local`, 계정 Secret 마운트, `DATA_SOURCE=auto`(실데이터가 없거나 실패하면 더미), `MODEL_REGISTRY_URI` |
| `k8s/service.yaml` | ClusterIP 8501 |
| `deploy.ps1` | 빌드·ECR push·digest 반영·apply 를 한 번에 하는 PowerShell 스크립트 (아래 "스크립트로 배포") |
| `argocd/` | Argo CD 프로젝트·권한·Application. main 머지 후 자동 배포 (아래 "CI/CD") |

## 실제 승인 연결

2026-10-23 실제 승인 연결: ServiceAccount는 `dashboard/approval-dashboard`, workgroup은 `clothes-query-dev-dashboard`다. 기존 Secret `dashboard/airflow-api-client`의 `username`·`password`를 사용한다. 기존 역할과 전용 workgroup은 [dashboard-access](../../stacks/dashboard-access/README.md)에서 관리한다. 실제 Pod의 승인 조회·S3 패치노트·Airflow 인증을 확인했다. 재처리 DAG 등록과 실제 승인·재처리 시험은 구분하며 최신 Silver 정상 실행 결과는 [공개 연결 기록](../../../docs/tasks/infra-silver-publication.md)을 따른다. [기존 배포·검증 기록](../../../docs/tasks/infra-dashboard-runtime-connect.md)도 보존한다.

2026-10-24 파이프라인 상태 화면을 위해 같은 역할에 Gold B 원장 4개·Silver/Gold 완료 목록의 Glue/S3 읽기를 추가했다. 기존 전용 workgroup을 그대로 쓰며 새 원본 쓰기·삭제는 허용하지 않는다. `gold_a.gold_runs`의 실제 파티션이 가리키는 채널별 완료 목록도 읽는다. 화면 코드 배포와 데이터 조회 권한 적용은 별개다. [대상과 확인 기록](../../../docs/tasks/infra-dashboard-status-read.md)을 따른다.

## CI/CD (GitHub Actions + Argo CD)

main 에 대시보드 소스가 머지되면 사람이 digest 를 고치거나 커밋하지 않아도 배포된다.

```
main 머지 ──▶ .github/workflows/dashboard-deploy.yml
               ├ GitHub OIDC 로 AWS 역할(clothes-query-dev-dashboard-ci, ECR push 전용) 받기
               ├ 이미지 빌드·ECR push (태그 = 커밋 7자리, 이미 있으면 건너뜀)
               └ deploy/dashboard 브랜치 = 그 main 커밋 + deployment.yaml image digest 1줄 변경 (강제 덮어쓰기)
            ──▶ Argo CD Application `dashboard` 가 deploy/dashboard 의 k8s/ 를 자동 sync (약 3분 주기)
```

- 실행 조건: `dashboard/**`, `agent/approval/approval.py`, `agent/detect/athena_io.py`, `infra/platform/dashboard/Dockerfile*`, `infra/platform/dashboard/k8s/**` 가 바뀐 main push. Actions 화면의 "Run workflow" 로 수동 실행도 된다.
- main 의 `k8s/deployment.yaml` image 줄은 더 이상 갱신하지 않아도 된다(실제로 떠 있는 digest 는 deploy/dashboard 브랜치와 Argo CD 화면에서 본다).
- 되돌리기: Argo CD UI 의 History 에서 이전 버전으로 Rollback 하거나(자동 sync 가 잠시 꺼짐), 이전 main 커밋을 골라 워크플로를 수동 실행한다.
- Argo CD 가 관리하는 것은 Deployment·Service 뿐이다. namespace, Secret(`dashboard-accounts`, `airflow-api-client`), ServiceAccount 는 지금처럼 수동이다. 계정 변경은 계속 `deploy.ps1 -AccountsOnly`.
- **selfHeal 이 켜져 있어서**, Application 을 만든 뒤 `deploy.ps1`(이미지 변경 + kubectl apply)로 배포하면 Argo CD 가 Git 상태로 되돌린다. 이미지 배포는 main 머지로만 한다. `-AccountsOnly` 는 Secret 과 재시작만 하므로 영향이 없다.

### 처음 한 번 준비 (순서대로)
1. AWS 역할: [`stacks/dashboard`](../../stacks/dashboard/README.md)에서 plan 을 검토하고 apply 한다. 역할 1개 + 인라인 정책 1개가 추가된다(2 to add). GitHub OIDC 공급자는 계정에 이미 있어 읽기만 한다.
2. GitHub 저장소 변수: Settings → Secrets and variables → Actions → **Variables** 에 `DASHBOARD_DEPLOY_ROLE_ARN` = `terraform output -raw github_actions_role_arn`. (저장소 관리자 권한 필요)
3. Argo CD 가 dashboard namespace 를 보게 한다: `infra/platform/argocd/development-values.yaml` 의 `namespaces: api,dashboard` 로 helm upgrade ([Argo CD 안내](../argocd/README.md)의 설치 명령과 같음).
4. 권한·프로젝트: `kubectl apply -f infra/platform/dashboard/argocd/access.yaml` → `kubectl apply -f infra/platform/dashboard/argocd/project.yaml`
5. 워크플로를 한 번 실행해 deploy/dashboard 브랜치를 만든다 (main 머지 또는 Run workflow).
6. `kubectl apply -f infra/platform/dashboard/argocd/application.yaml`. 기존 Deployment/Service 는 지우지 않고 Argo CD 가 그대로 넘겨받는다. UI 에서 Synced/Healthy 를 확인한다.

## 스크립트로 배포 (처음 한 번 준비가 끝난 뒤)
저장소 루트에서 실행한다. Docker Desktop 실행, AWS 로그인, kubeconfig(`infra/EKS_ACCESS.md`)가 필요하다. `KUBECONFIG` 가 없으면 `.cache\eks-kubeconfig.private` 를 쓴다.
```powershell
.\infra\platform\dashboard\deploy.ps1 -DryRun     # 할 일만 보기 (빌드·수정·apply 안 함)
.\infra\platform\dashboard\deploy.ps1             # 빌드 → push → deployment.yaml digest 갱신 → apply → rollout 대기
.\infra\platform\dashboard\deploy.ps1 -AccountsOnly   # 계정만 바꿀 때: Secret 덮어쓰기 + 재시작 (이미지 그대로)
.\infra\platform\dashboard\deploy.ps1 -Tag <태그> -SkipBuild   # ECR 에 있는 이전 이미지로 되돌리기
```
- 태그는 커밋 7자리다. 이미지에 들어가는 파일에 커밋 안 한 변경이 있으면 `<커밋>-dirty<시각>` 이 된다(ECR 이 태그 덮어쓰기 불가라서). 같은 커밋 이미지가 ECR 에 이미 있으면 빌드를 건너뛴다.
- 스크립트가 `k8s/deployment.yaml` 의 `image` 를 `<저장소>@sha256:...` 로 바꾼다. 클러스터에 올라간 버전 기록이므로 배포 후 커밋한다(커밋은 스크립트가 하지 않는다).
- Argo CD Application 을 만든 뒤에는 이 스크립트로 이미지를 바꾸지 않는다(위 "CI/CD"의 selfHeal). Argo CD 를 쓰기 전이거나 Application 을 지운 뒤의 수동 배포용이다.
- 계정 Secret 이 없으면 `dashboard/.local/accounts.json` 으로 만들고, 있으면 그대로 둔다(`-UpdateAccounts` 를 주면 덮어쓰고 필요하면 재시작). 계정 추가는 `python dashboard\make_test_accounts.py --add <이메일>` 후 `-AccountsOnly`.
- `-NoApply` 는 push 와 digest 반영까지만 한다. 아래 수동 순서는 스크립트가 하는 일과 같다.

## 배포 순서 (수동)
0. ECR 저장소 준비: [`stacks/dashboard`](../../stacks/dashboard/README.md)에서 plan(1 to add)을 검토하고 apply한다.
1. 이미지 빌드·ECR 업로드 (repo 루트에서)
   ```
   docker build -f infra/platform/dashboard/Dockerfile -t <ECR 주소>:<태그> .
   docker push <ECR 주소>:<태그>
   ```
   push 후 digest 를 확인해 `deployment.yaml` 의 `image` 를 채운다.
2. namespace: `kubectl apply -f k8s/namespace.yaml`
3. 계정 Secret (파일은 `python make_test_accounts.py --force [--same-as-id]` 로 만든 `dashboard/.local/accounts.json`)
   재처리 승인을 할 사람은 이메일 아이디 계정을 더한다: `python make_test_accounts.py --add <이메일> [--roles data] [--same-as-id]` (공용 3계정은 승인 불가)
   ```
   kubectl create secret generic dashboard-accounts -n dashboard --from-file=accounts.json=dashboard/.local/accounts.json \
     --dry-run=client -o yaml | kubectl apply -f -
   ```
   이미 Secret 이 있어도 위 명령으로 덮어쓴다. 파드는 Secret 변경을 자동으로 다시 읽지 않으므로 `kubectl rollout restart deployment/dashboard -n dashboard`를 한다.
   비밀번호는 해시로만 저장되지만 Git·문서에 올리지 않는다.
4. `kubectl apply -f k8s/deployment.yaml -f k8s/service.yaml`
5. 공유 ALB 적용은 [`../ingress/README.md`](../ingress/README.md) 순서를 따른다.

## 알아둘 것
- 로그인 실패 잠금은 파드별 메모리라 replicas 는 1로 둔다.
- HTTP 구간에서는 비밀번호가 암호화되지 않는다. 운영 전 도메인과 HTTPS 로 바꾼다.
- `DATA_SOURCE=auto`는 데이터별 연결 상태에 따라 실데이터 또는 더미를 쓴다. Gold A는 아래 별도 설정으로 실데이터를 조회하며 오류를 더미로 숨기지 않는다. 패치노트 prefix는 읽기만, 승인 이벤트 prefix는 필요한 쓰기만 허용하며 `ground_truth/`는 명시 거부한다.

## Gold A 조회 연결

Gold A 실데이터는 `GOLD_A_DATA_SOURCE=athena`, `GOLD_A_ATHENA_WORKGROUP=clothes-query-dev-dashboard`, `GOLD_A_DATABASE=gold_a`로 연결한다. IAM은 dashboard-access의 `enable_gold_a_reads`가 관리한다. 환경 변수는 main 대상 PR 머지 후 Actions → deploy/dashboard → Argo CD 경로로 반영한다. live Deployment만 수정하면 selfHeal이 되돌린다. [권한 적용·실제 Pod 조회 검증](../../../docs/tasks/infra-dashboard-gold-a-read.md)을 참고한다.
