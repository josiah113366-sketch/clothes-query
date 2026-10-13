# infra/ 작업 규칙

이 문서는 `infra/` 폴더 작업에만 적용된다. 
프로젝트 공통 규칙(Git, 문서, 보안)은 루트 `CLAUDE.md`를 따른다.

## 폴더 구조

```
infra/
├── README.md              # 전체 지도: 스택 순서, 의존 관계, apply/destroy 순서
├── bootstrap/             # state용 S3 버킷. local state, 최초 1회만 apply
├── modules/               # 재사용 설계도. 직접 apply하지 않는다
│   └── <name>/
│       ├── main.tf
│       ├── variables.tf
│       └── outputs.tf
└── stacks/                # 실제로 apply하는 단위
    └── <name>/
        ├── backend.tf
        ├── providers.tf
        ├── versions.tf
        ├── main.tf        # modules/ 의 모듈을 호출
        ├── variables.tf
        ├── outputs.tf
        └── terraform.tfvars
```

- `modules/<name>/`에는 `main.tf`, `variables.tf`, `outputs.tf`만 둔다. backend와 provider는 넣지 않는다.
- 스택은 `modules/`를 `source = "../../modules/<name>"`으로 호출한다.
- `bootstrap/`은 `stacks/` 밖에 둔다. local state를 쓰는 특수한 스택이기 때문이다.
- 각 폴더에 `README.md`를 둔다 (목적, 의존 스택, 실행 방법, 주요 output, destroy 주의점).
- modules의 입력/출력 표는 terraform-docs로 생성할 수 있으면 직접 쓰지 않는다.

## 스택 순서와 의존 관계

```
bootstrap → network → eks → platform
```

| 스택 | 내용 |
|---|---|
| `bootstrap` | state 저장용 S3 버킷 (버저닝, 암호화, 퍼블릭 차단) |
| `network` | VPC, 서브넷, NAT 등 |
| `eks` | EKS 클러스터, 노드그룹, IAM(IRSA), 접근 권한(access entry) |
| `platform` | Helm으로 Kafka / Spark / Airflow 설치 |

- 이후 필요하면 RDS, S3 데이터 레이크 등 스택을 추가한다. 추가할 때는 의존 관계를 `infra/README.md`에 갱신한다.
- `eks` 스택과 그 위의 Helm/Kubernetes provider 리소스(`platform`)는 **state를 반드시 분리**한다. 한 state에 넣으면 provider 초기화 순서 문제로 자주 깨진다.
- 스택 간 값 전달은 `terraform_remote_state` 또는 SSM Parameter Store를 쓴다. 그래서 각 모듈/스택에 `outputs.tf`가 필요하다.
- 새 스택을 만들기 전에 어떤 스택에 속해야 하는지 먼저 확인한다. 한 스택에는 하나의 역할만 담는다.

## State 규칙

- backend는 S3를 쓴다. 버킷은 프로젝트 전체에 **하나**이고, 스택마다 **key만 다르게** 한다.
- 버킷 이름: `clothes-query-tfstate-<AWS계정ID>` (리전 `ap-northeast-1`)
- key 규칙: `clothes-query/dev/<스택명>/terraform.tfstate`
- 스택마다 key는 반드시 달라야 한다. 새 스택을 만들 때 다른 스택의 `backend.tf`를 복사하면 **key를 반드시 바꾼다.** key가 같으면 두 스택이 같은 state를 공유해서, 한쪽 apply가 다른 쪽 리소스를 삭제하려 한다.
- backend 설정 예시:

```hcl
terraform {
  backend "s3" {
    bucket       = "clothes-query-tfstate-<AWS계정ID>"
    key          = "clothes-query/dev/network/terraform.tfstate"
    region       = "ap-northeast-1"
    use_lockfile = true
    encrypt      = true
  }
}
```

- backend 블록에는 변수를 쓸 수 없으므로 값을 직접 적는다.
- `use_lockfile = true`는 Terraform 1.10 이상이 필요하다. `versions.tf`의 `required_version`을 팀이 쓰는 버전에 맞춘다.
- bootstrap 스택만 local state로 최초 1회 apply한다. 버킷이 생긴 뒤 필요하면 `terraform init -migrate-state`로 그 버킷에 옮긴다.

## Provider와 공통 설정

- 리전: `ap-northeast-1` (도쿄)
- provider에 `default_tags`를 건다.

```hcl
provider "aws" {
  region = "ap-northeast-1"

  default_tags {
    tags = {
      Project   = "clothes-query"
      ManagedBy = "terraform"
    }
  }
}
```

- 프로바이더/Terraform 버전은 `versions.tf`에 명시하고, `.terraform.lock.hcl`은 커밋한다.
- `.terraform/`과 `*.tfstate`, `*.tfstate.*`는 커밋하지 않는다.
- `terraform.tfvars`에는 비밀값을 넣지 않는다. 비밀값은 Secrets Manager / SSM Parameter Store를 쓴다.
- 콘솔에서 이미 만든 리소스가 있으면 새로 만들지 말고 `terraform import`로 코드에 편입한다.

## 코드 작성 규칙

- 코드를 작성하거나 수정한 뒤 반드시 아래를 실행한다.
  - `terraform fmt`
  - `terraform validate`
- 하드코딩을 줄이고 변수로 뺀다. 단, backend 블록은 예외다.
- 리소스 이름은 `clothes-query-<환경>-<용도>` 형식을 따른다.
- 비용이 큰 리소스(EKS, RDS, NAT Gateway)를 추가하거나 변경할 때는 먼저 예상 비용과 영향을 설명한다.
- IAM 권한은 최소 권한으로 만든다. `*` 와일드카드 권한은 이유 없이 쓰지 않는다.

## 작업 흐름 (중요)

1. 최신 main에서 `infra/<스택명>` 브랜치를 만든다. (예: `infra/network`)
2. 코드를 작성하고 `terraform fmt` → `validate` → `plan`까지 진행한다.
3. **apply는 사용자(성철)가 직접 실행한다.** plan 결과를 눈으로 확인한 뒤 판단한다.
4. apply 직전에 `origin/main`을 브랜치에 반영했는지 확인한다. 오래된 코드로 apply하면 다른 팀원의 변경을 되돌릴 수 있다.
5. apply 후 동작을 확인하고, PR에 plan/apply 결과를 첨부해서 올린다. 빠르게 머지한다.
6. PR 리뷰에서 코드가 바뀌면 다시 plan을 확인하고, 필요하면 다시 apply한다. 코드와 AWS 실제 상태가 어긋난 채로 두지 않는다.

## 절대 하지 말 것

- **Claude는 `terraform apply`, `terraform destroy`를 실행하지 않는다.** plan까지만 실행하고 결과를 요약해서 보여준다.
- plan 결과에서 `destroy`나 `replace`(삭제 후 재생성) 항목이 있으면 반드시 먼저 알린다.
- `terraform state rm`, `terraform state mv`, `terraform force-unlock`, `terraform import` 등 state를 직접 조작하는 명령은 사용자 확인 없이 실행하지 않는다.
- main 브랜치에 직접 커밋하지 않는다.
- 스택 간에 state key를 공유하지 않는다.
- AWS 콘솔에서 리소스를 수동으로 만들거나 수정하지 않는다. 이미 생긴 차이는 코드로 맞춘다.
- 비밀값(액세스 키, 비밀번호)을 코드, tfvars, 커밋 메시지, 대화에 노출하지 않는다.
- 다른 팀원이 담당하는 영역(예: Airflow DAG, Spark job 코드)을 인프라 PR에 섞지 않는다.

## 팀원과의 경계

- `infra/`는 성철만 수정한다. 팀원이 인프라 변경이 필요하면 GitHub 이슈로 요청한다.
- 앱 레벨 설정(Airflow 워커 replica, 리소스 request/limit 등 Helm values)은 담당 팀원이 자기 values 파일을 직접 수정한다.
- 인프라 용량(EKS 노드 수, 인스턴스 타입, 노드그룹 등)은 성철이 Terraform으로 변경한다.
- 인프라 PR을 머지하고 apply한 뒤, 팀원에게는 "머지 + apply 완료"와 함께 접속 방법(엔드포인트, kubectl 접근 방법 등)을 문서로 전달한다.

## 새 스택 만들 때 체크리스트

- [ ] 최신 main에서 `infra/<스택명>` 브랜치 생성
- [ ] `stacks/<스택명>/`에 backend, providers, versions, main, variables, outputs, tfvars 작성
- [ ] backend의 key를 `clothes-query/dev/<스택명>/terraform.tfstate`로 설정 (다른 스택과 겹치지 않는지 확인)
- [ ] 필요한 모듈이 `modules/`에 있는지 확인, 없으면 새로 작성
- [ ] `terraform fmt`, `terraform validate`, `terraform plan`
- [ ] 폴더 README.md와 `infra/README.md`의 순서/의존 관계 갱신
- [ ] 사용자가 apply → 결과 확인 → PR 작성 (plan/apply 결과 첨부)