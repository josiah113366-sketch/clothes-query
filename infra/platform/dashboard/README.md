# 대시보드 배포 (EKS)

앱 소스는 [`dashboard/`](../../../dashboard/README.md)에 있고, 이 폴더는 배포용 파일만 둔다. 외부 접속(ALB)은 [`../ingress`](../ingress/README.md)의 공유 ALB가 맡으므로 여기에는 Ingress가 없다(`dashboard:8501`로 연결).

| 파일 | 내용 |
|---|---|
| `Dockerfile`, `Dockerfile.dockerignore` | 이미지 빌드(컨텍스트는 저장소 루트). `dashboard/`와 재처리 승인 화면이 쓰는 `agent/approval/approval.py`·`agent/detect/athena_io.py`만 들어간다. 계정 파일(`.local/`)과 비밀값은 제외 |
| `k8s/namespace.yaml` | namespace `dashboard` (공유 ALB 라벨 포함) |
| `k8s/deployment.yaml` | 파드 1개, `AUTH_MODE=local`, 계정 Secret 마운트, `DATA_SOURCE=auto`(실데이터가 없거나 실패하면 더미), `MODEL_REGISTRY_URI` |
| `k8s/service.yaml` | ClusterIP 8501 |
| `deploy.ps1` | 빌드·ECR push·digest 반영·apply 를 한 번에 하는 PowerShell 스크립트 (아래 "스크립트로 배포") |

## 실제 승인 연결

2026-10-23 실제 승인 연결: ServiceAccount는 `dashboard/approval-dashboard`, workgroup은 `clothes-query-dev-dashboard`다. 기존 Secret `dashboard/airflow-api-client`의 `username`·`password`를 사용한다. 기존 역할과 전용 workgroup은 [dashboard-access](../../stacks/dashboard-access/README.md)에서 관리한다. 실제 Pod의 승인 조회·S3 패치노트·Airflow 인증을 확인했다. 재처리 DAG 등록과 실제 승인·재처리 시험은 구분하며 최신 Silver 정상 실행 결과는 [공개 연결 기록](../../../docs/tasks/infra-silver-publication.md)을 따른다. [기존 배포·검증 기록](../../../docs/tasks/infra-dashboard-runtime-connect.md)도 보존한다.

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
- `DATA_SOURCE=auto`는 데이터별 연결 상태에 따라 실데이터 또는 더미를 쓴다. 실제 연결된 것은 승인 조회와 모델 패치노트이며, Gold A 등 나머지 분석 화면을 모두 연결한 것은 아니다. 패치노트 prefix는 읽기만, 승인 이벤트 prefix는 필요한 쓰기만 허용하며 `ground_truth/`는 명시 거부한다. 앱 담당의 Athena 함수 연결은 별도다.
