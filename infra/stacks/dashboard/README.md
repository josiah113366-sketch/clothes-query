# dashboard stack

대시보드(Streamlit) 컨테이너 이미지 저장소 `clothes-query-dev/dashboard` 하나를 만든다. 태그 변경 불가(IMMUTABLE), push 시 취약점 스캔, 삭제 보호(`force_delete=false`)는 [ecr 스택](../ecr/README.md)과 같다. 이미지가 있는 저장소를 지우려면 별도 정리가 필요하다.

- 선행: 기존 bootstrap(state bucket).
- backend key: `clothes-query/dev/dashboard/terraform.tfstate`.
- 입력: 공유 `deployment.auto.tfvars.json`의 `expected_account_id`뿐이다. 별도 개인 입력은 없다.
- 출력: `repository_url`, `repository_arn`, `github_actions_role_arn` (sensitive 표시).
- CI 역할(`github-actions.tf`): GitHub Actions `dashboard-deploy.yml` 이 OIDC 로 받는 `clothes-query-dev-dashboard-ci`. 조건은 `josiah113366-sketch/clothes-query` 의 main 브랜치만, 권한은 이 ECR 저장소 push·조회만(삭제 없음). GitHub OIDC 공급자는 계정에 이미 있어 읽어서 쓴다(`create_github_oidc_provider=false` 기본). 공급자가 없는 계정이면 true. 출력 ARN 은 GitHub 저장소 변수 `DASHBOARD_DEPLOY_ROLE_ARN` 에 넣는다.
- 이후 추가할 것: Athena/S3 읽기 전용 Pod Identity 역할은 실데이터 연결 때 이 스택에 넣는다(`gold_a/`·`gold_b/` 읽기만, `ground_truth/` 금지).

## 실행

[공유 배포 설정](../../DEPLOYMENT_CONFIG.md)과 [전체 안내](../../IMPLEMENTATION.md)를 먼저 읽는다. 이 폴더에서 실행한다. **apply는 검토한 plan에 대해 사용자가 직접 실행한다.**

```powershell
terraform init -backend-config=deployment.backend.hcl -lockfile=readonly
terraform fmt -check
terraform validate
terraform plan -input=false      # CI 역할 2 to add (역할·정책). OIDC 공급자는 기존 것을 읽는다
```

저장소가 만들어지면 이미지를 올리는 순서는 [대시보드 배포 안내](../../platform/dashboard/README.md)를 따른다. 태그가 immutable이므로 push마다 `v1`, `v2`처럼 새 태그를 쓰고, 클러스터에는 태그 대신 digest로 지정한다.
