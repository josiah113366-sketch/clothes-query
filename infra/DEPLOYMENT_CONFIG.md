# 공유 Terraform 배포 설정

사용자 결정(2026-10-21): 공통 배포값을 Git으로 관리하고 개인정보·인증 비밀을 분리한다. 설정 공유는 AWS 배포 실행이 아니며 자동 apply를 추가하지 않는다.

2026-10-23 Spark 준비: ecr 공유 auto 입력은 기존 저장소를 보존하며 Spark 저장소 2개와 de-ai-18 push 정책만 추가하도록 선택했다. plan과 적용 완료는 구분한다. spark-access는 별도 backend key를 쓰며 namespace=null·enabled=false다. network의 추가 S3 action은 platform/spark/handoff/network-magic.tfvars.example 검토안으로만 두고 아직 공유 auto 입력에 적용하지 않았다. compute Spark enabled=false도 유지한다.

## 파일과 우선순위

| 파일 | Git | 내용 |
|---|---|---|
| `terraform.tfvars` | 추적 | 기존 기본 버전·사양 |
| `deployment.auto.tfvars.json` | 추적 | 실제 공통 계정·리소스 식별자·배포 설정. Terraform 자동 로드 |
| `deployment.backend.hcl` | 추적 | 기존 state bucket·region. init에서 명시 지정 |
| `deployment.local.tfvars.json` | 제외 | 개인 IP·이메일 등 로컬 값. plan에서 필요 시 명시 지정 |
| `*.tfstate`, `*.tfplan`, `.terraform/`, Secret 파일 | 제외 | 실제 상태·계획·자격증명. 공개하지 않음 |

기존 `terraform.tfvars`보다 `deployment.auto.tfvars.json`이 우선하며, 명시한 `-var-file=deployment.local.tfvars.json`이 공유값보다 우선한다. map 값은 같은 변수 전체를 대체하므로 로컬에서 공통 map 일부만 덮어쓰지 않는다. 오래된 전체 로컬 파일이 남으면 공유 설정을 가릴 수 있어 기존 사용자도 로컬 파일을 정리해야 한다.

계정 ID·SG ID·일반 ARN·bucket 이름·VPC CIDR·namespace·S3 prefix·WAL/NAT 설정은 공유한다. 실제 비밀번호·AWS 키·토큰·개인 공인 IP·이메일은 공유하지 않는다. `sensitive=true`는 Terraform 출력 숨김 표시이며, 공유할 수 있는 식별자도 이 표시가 남아 있을 수 있다. 표시만으로 state가 암호화되는 것은 아니다.

## 사용

AWS CLI에 본인 계정을 설정한 뒤 스택 폴더에서 실행한다. backend/state 소유권과 대상 계정을 확인하며 기존 state key를 바꾸거나 재생성하지 않는다.

```powershell
terraform init -backend-config=deployment.backend.hcl -lockfile=readonly
terraform fmt -check
terraform validate

# 개인 입력이 없는 스택: 공유값이 자동으로 들어간다.
terraform plan -input=false

# EKS·알림 등 개인 입력이 있는 스택:
terraform plan -input=false -var-file=deployment.local.tfvars.json
```

EKS 개인 파일 예시:

```json
{"public_access_cidrs": ["192.0.2.1/32"]}
```

알림 개인 파일 예시(실제 주소는 로컬에만 저장):

```json
{"email_recipients": ["operator@example.invalid"]}
```

다른 스택의 기존 로컬 파일은 호환을 위해 `{}`로 남겼다. 개인 값이 없으면 생략해도 되고 기존 `-var-file=deployment.local.tfvars.json` 명령을 계속 사용해도 된다. AWS profile·키·SSO 정보는 각 PC에서 관리한다. 개인 입력이 필요한데 파일이 없으면 `-input=false`로 즉시 실패하게 하며 팀원의 개인 값을 대신 하드코딩하지 않는다.

## 범위와 의존 관계

2026-10-23 후속 정리: `infra/applied-state-sync`는 실제 적용된 후속 8개를 최신 main 4d80c76 기준으로 통합한 브랜치다. 이 브랜치의 compute는 Spark 풀 enabled=true, 현재 실행 노드는 0대다. infrastructure-alerts는 승인 후 적용·검증했으며 개인 이메일은 여전히 Git 제외 입력을 사용한다. 아래의 operations-alerts는 별도 과거 후보이므로 두 이름을 혼동해 중복 배포하지 않는다. 기존 state/backend 위치와 실제 실행 권한은 유지했다. [통합 검증 결과](../docs/tasks/infra-applied-state-sync.md)를 참고하며, 이전 main 설정으로 apply하지 않는다.

현재 공유 설정은 network/eks/rds/storage/ecr/compute/workload-access/team-access/gold-b-access/agent-development-access/operations-alerts에 준비했다. apps는 기존 backend 위치만 공유한다. Gold B·조사 쓰기·Airflow·개발 접근 소스는 #40·#50·#41·#49로 main에 반영됐다. `operations-alerts` 소스는 여전히 별도 보류 브랜치에 있고 설정 파일만으로 미반영 모듈이 생기지는 않는다.

`operations-alerts`는 계속 미적용 보류다. `athena-query-base`는 Gold B로 대체된 과거 후보라 이번 전환에서 제외했고 함께 apply하지 않는다. SageMaker·ECS 등 팀원 스택의 이 PC에 없는 배포 입력을 추정해 만들지 않는다. Helm `runtime.local.yaml`은 이번 Terraform 변수 분리 범위에 포함하지 않는다.

이 파일들은 현재 합의된 배포 입력을 공유하는 것이며 AWS 현재 상태 전체를 보장하지 않는다. 노드/서비스가 외부에서 바뀐 경우 별도 plan으로 확인한다. EKS 코드는 실제 활성 상태와 맞춰 audit를 포함한 관리 로그 5종을 수집한다. 예전 audit 비활성화 코드나 저장 plan을 재사용하지 말고 최신 main에서 plan을 새로 만든다. [설정 일치 확인 기록](../docs/tasks/infra-eks-audit-restore.md)을 따른다. 공통 설정 공유와 코드 정리 과정에서는 apply를 실행하지 않는다.

기존 작업 문서의 '계정 ID/ARN은 항상 비공개'는 이전 정책이다. 현재 입력 방식은 이 문서를 우선한다. 현재 적용 환경과 다른 스택을 무작정 실행하거나 새 공유값을 확인 없이 적용하지 않는다.

과거 network 로컬 파일의 state_bucket은 그 스택에서 선언·사용하지 않는 값이라 공통 tfvars에서 제거했다. 실제 backend bucket은 기존 deployment.backend.hcl에 그대로 유지한다. 그 외 선언된 배포 입력은 분리 전과 같다. 과거 일회성 로컬 스크립트가 전체 입력이 개인 파일에 있다고 가정할 수 있으므로 재사용할 때 공유 파일을 먼저 읽도록 확인한다.

`gold-b-catalog`는 기존 storage state만 읽는 독립 Glue DB 스택이다. backend key는 clothes-query/dev/gold-b-catalog/terraform.tfstate이며 기존 DB를 같은 state로 관리한다. database.sql은 실행하지 않고 표·뷰 DDL은 pipelines 담당 SQL을 Athena에 별도 반영한다. 2026-10-24 draft #74의 누락 소스를 통합했으며 이미 적용된 JP Haiku와 대시보드 후속 설정은 보존했다.
