# 대시보드 배포 (EKS)

앱 소스는 [`dashboard/`](../../../dashboard/README.md)에 있고, 이 폴더는 배포용 파일만 둔다. 외부 접속(ALB)은 [`../ingress`](../ingress/README.md)의 공유 ALB가 맡으므로 여기에는 Ingress가 없다(`dashboard:8501`로 연결).

| 파일 | 내용 |
|---|---|
| `Dockerfile`, `Dockerfile.dockerignore` | 이미지 빌드(컨텍스트는 저장소 루트). `dashboard/`와 재처리 승인 화면이 쓰는 `agent/approval/approval.py`·`agent/detect/athena_io.py`만 들어간다. 계정 파일(`.local/`)과 비밀값은 제외 |
| `k8s/namespace.yaml` | namespace `dashboard` (공유 ALB 라벨 포함) |
| `k8s/deployment.yaml` | 파드 1개, `AUTH_MODE=local`, 계정 Secret 마운트, `DATA_SOURCE=auto`(실데이터가 없거나 실패하면 더미), `MODEL_REGISTRY_URI` |
| `k8s/service.yaml` | ClusterIP 8501 |

## 배포 순서 (모두 아직 실행하지 않았다)
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
- 실데이터를 읽으려면 Athena 조회 함수 등록, 읽기 전용 Pod Identity ServiceAccount(`gold_a/`·`gold_b/`·`review-score/model-registry/releases/`만, `ground_truth/` 금지)가 필요하다(`DATA_SOURCE=auto` 는 이미 설정됨). 모델 패치노트 위치(`MODEL_REGISTRY_URI`)는 `deployment.yaml`에 채워 두었다. 할 일은 `dashboard/TODO.md` 의 F3, F4.
- 이미지 빌드·ECR 저장소, 위 YAML 의 실제 적용은 하지 않았고 `kubectl apply --dry-run=server` 도 해 보지 않았다.
