# AWS 인증 없는 인프라 검사

Terraform 서식·구성 유효성 및 AWS/Kubernetes mock plan을 로컬과 GitHub Actions에서 같은 명령으로 확인한다. 실행 대상은 `infra/bootstrap`, `infra/stacks/*`, `infra/tests` 중 `.tf` 파일이 있는 root다. module은 참조하는 root의 validate/mock plan에서 확인하고 전체 `infra/`의 Terraform 서식도 검사한다.

## 로컬 실행

저장소 루트에서 Python 3.12 가상환경과 Terraform 1.15.8을 준비한다. 검사 도구 의존성은 시뮬레이터와 분리한다.

```powershell
python -m venv .cache/infra-checks-venv
.cache/infra-checks-venv/Scripts/python.exe -m pip install -r infra/checks/requirements.txt
.cache/infra-checks-venv/Scripts/python.exe -m unittest discover -s infra/checks/tests -v
.cache/infra-checks-venv/Scripts/python.exe infra/checks/check_infra.py
```

Terraform이 PATH에 없으면 `--terraform`으로 실행 파일을 지정한다. 아래 경로는 이 PC에서 공식 배포 파일의 SHA-256을 검증해 준비한 portable 실행 파일이다. 다른 PC에서는 [공식 설치 안내](https://developer.hashicorp.com/terraform/install)에 따라 준비하거나 실행 파일 경로를 바꾼다.

```powershell
.cache/infra-checks-venv/Scripts/python.exe infra/checks/check_infra.py --terraform .cache/terraform-1.15.8/terraform.exe

# 기존 기반 브랜치를 수정하지 않고 해당 커밋의 infra를 검사
.cache/infra-checks-venv/Scripts/python.exe infra/checks/check_infra.py --terraform .cache/terraform-1.15.8/terraform.exe --ref infra/analysis
```

Linux에서는 가상환경 Python 경로를 `.cache/infra-checks-venv/bin/python`으로 바꾸거나 CI처럼 준비된 Python/Terraform을 사용한다.

## 검사 방식

1. 기본 실행은 Git 추적 파일의 **현재 작업 내용**을 임시 폴더에 복사한다. 신규 파일은 먼저 `git add`해야 검사 대상이 된다. `--ref`는 그 Git ref의 커밋 내용을 읽으며 미커밋 변경은 포함하지 않는다.
2. 무시된 로컬 입력·state·기존 `.terraform/`를 복사하지 않는다. root별 provider lockfile이 없으면 실패한다.
3. Terraform 자식 프로세스의 AWS 인증·Kubernetes 설정·`TF_*` 변수를 제거하고 빈 인증 파일, 독립 CLI 설정 및 임시 provider cache를 사용한다.
4. `fmt -check -recursive`, root별 `init -backend=false -input=false -lockfile=readonly`, `validate`를 실행한다. backend/state 초기화나 기존 lockfile 변경은 수행하지 않는다. [Terraform init 공식 옵션](https://developer.hashicorp.com/terraform/cli/commands/init)
5. `infra/tests`의 최상위 `.tftest.hcl`가 있으면 HCL 파싱으로 **명시적 `command = plan`**, 실제 provider 설정 부재, 사용하는 AWS/Kubernetes provider의 mock을 확인한 파일만 `terraform test` 필터로 실행한다. alias mock도 이름이 일치해야 한다. 원격 module·provider 재매핑·다른 provider는 현재 검사 범위에서 거부한다.
6. 임시 복사본과 provider cache는 종료 시 정리한다. 원본 소스·backend·state는 검사 작업에서 수정하지 않는다.

검사기는 신뢰할 수 있는 저장소 코드의 배포 전 검사 도구이며 악성 코드 실행을 막는 OS sandbox는 아니다. `validate`와 mock test 성공은 실제 AWS 권한·quota·CRD·클러스터 연결·스토리지·앱 동작의 성공을 뜻하지 않는다. 초기 provider 설치에는 인터넷 연결과 디스크 공간이 필요하다.

## GitHub Actions

[infra-checks.yml](../../.github/workflows/infra-checks.yml)은 main 대상 PR, main/infra 브랜치 push, 수동 실행에서 동작하도록 준비했다. 인프라 파일 또는 해당 workflow 변경 시 검사한다. Actions는 commit SHA, Terraform은 1.15.8, Python 패키지는 requirements 파일에서 고정했다.

권한은 `contents: read`만 사용하며 AWS/클러스터 인증, PR 댓글 쓰기, ECR push, apply/destroy가 없다. `pull_request_target`이나 저장소 Secret을 사용하지 않는다. 버전·버전 SHA 변경은 검증 후 별도 커밋으로 갱신한다.

현재 main에는 bootstrap만 있으므로 1개 root를 검사한다. `infra/analysis`가 main에 병합되면 현재 구조의 root와 mock suite를 자동으로 발견한다. 계획 문서 브랜치나 기반 인프라 브랜치를 이 CI 브랜치에 합칠 필요가 없다.

## 실패 시

- Terraform이 없으면 설치하거나 `--terraform` 경로를 지정한다.
- 서식 오류는 소스 담당 브랜치에서 `terraform fmt`로 수정한다. 이 검사기는 자동 수정하지 않는다.
- lockfile 오류는 해당 root 담당자가 provider 선택·체크섬을 검토한 뒤 lockfile을 갱신한다. 검사 실행 중 자동 upgrade는 하지 않는다.
- 새 mock 테스트가 거부되면 누락된 mock/명시적 plan을 보완한다. 실환경 plan·apply 테스트를 이 workflow에 섞지 않는다.
- 실제 backend·클러스터가 필요한 문제는 배포 PC의 승인된 별도 절차로 검증한다.
