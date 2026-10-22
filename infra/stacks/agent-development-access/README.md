# Agent 개발용 접근 스택

기존 `eks` state의 cluster_name을 읽고 agent 전용 개발자 역할·access entry·ECR 두 개를 추가한다. 기존 관리자·EKS 설정을 수정하지 않는 별도 state다. [모듈](../../modules/agent-development-access/README.md), [namespace 권한·이미지 등록](../../platform/agent-development/README.md)을 함께 따른다.

입력 `expected_account_id`, `state_bucket`, `trusted_principal_arns`는 gitignored `deployment.local.tfvars.json`으로 공급한다. 실제 동료 ARN을 공개 파일에 넣지 않는다. backend bucket/region도 gitignored `deployment.backend.hcl`로 공급한다.

```powershell
terraform init -backend-config=deployment.backend.hcl
terraform fmt -check
terraform validate
terraform plan -var-file=deployment.local.tfvars.json -out=deployment.tfplan
```

계획을 검토한 뒤 저장된 계획을 적용하고 `infra/platform/agent-development/namespace-access.yaml`을 namespace `agent`에 적용한다. 새 컴퓨팅·NAT·ALB는 만들지 않는다. ECR은 이미지 저장량·스캔·전송 관련 비용이 발생할 수 있다. 저장소는 내용이 있으면 자동 삭제되지 않는다. 이 state의 저장소를 기존 ecr state에도 중복 정의하지 않는다.

역할 ARN과 저장소 URL은 sensitive output이다. 개발자 접속은 별도 kubeconfig context로 확인하고 기존 관리자 접속과 혼동하지 않는다. 기존 관리자 역할 사용 권한은 자동 회수하지 않는다.
