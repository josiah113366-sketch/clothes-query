# 현재 상태

상태: 결정(관찰 사실) / 미정(AWS 실배포 상태) · 2026-10-13

## Git 및 협업

| 항목 | 관찰 결과 |
|---|---|
| 브랜치 | `main` |
| HEAD | `bbe9faea78a654b94209ed760871a7e389236ca7` |
| 원격 | `https://github.com/josiah113366-sketch/clothes-query` |
| 로컬 origin/main | HEAD와 동일. 서버의 최신 상태를 의미하지 않음 |
| 최근 변경 | `sim/skeleton` PR 병합, 시뮬레이터 골격·DDL·Compose 추가 |
| 최초 미커밋 상태 | 추적 파일 변경 없음. `infra_reuse_analysis.zip`만 untracked |
| 조사 중 파일 이동 | 사용자가 ZIP을 상위 폴더로 이동했다고 확인. 에이전트가 이동하지 않음 |
| 원격 확인 | `git ls-remote origin refs/heads/main` 연결 실패. fetch/push 미실행 |
| 협업 한계 | 팀원 미푸시 작업 및 원격 신규 변경은 확인할 수 없음 |

`git status`에 사용자 전역 ignore 파일 접근 경고가 있었다. 추적 파일 목록과 변경 상태는 확인했지만 전역 ignore 규칙은 확인하지 못했다. 이번 결과는 신규 문서만 남기며 커밋하지 않는다. 구현은 원격 최신 main 확인 후 `infra/<작업>` 브랜치에서 진행해야 한다.

## 저장소에서 확인한 구성

| 구성 | 근거 | 확인 내용 |
|---|---|---|
| Terraform bootstrap | `infra/bootstrap/main.tf` | S3 버킷, 버저닝, SSE-S3, Public Access Block. `prevent_destroy=true` |
| 리전 | `infra/bootstrap/providers.tf`, `variables.tf`, `terraform.tfvars` | 도쿄 `ap-northeast-1` |
| 버전 | `infra/bootstrap/versions.tf`, `.terraform.lock.hcl` | Terraform >=1.10, AWS provider ~>6.0, lock 6.68.0 |
| backend/state | `infra/bootstrap/bootstrap.md` | bootstrap은 local state. 다른 스택은 S3 backend 예정 |
| state 출력 | `infra/bootstrap/outputs.tf` | 버킷 이름·ARN·리전. 값 자체는 조회·문서화하지 않음 |
| 네트워크/EKS | `infra/README.md` | network/eks/platform은 예정. `infra/stacks/`, `infra/modules/` 구현 없음 |
| DB | `db/schema/001_member.sql`, `002_member_archive.sql` | PostgreSQL uuid/timestamptz 기반 member 및 member_archive DDL |
| 로컬 DB | `simulator/docker-compose.yml` | postgres:16, 5432, wal_level=logical, 로컬 healthcheck 및 DDL 초기 마운트 |
| 앱 | `simulator/src/sim/cli.py`, `simulator/Dockerfile` | Typer version 명령과 CLI 이미지. HTTP WEB/WAS가 아님 |
| Kubernetes/CI | Git 추적 파일 및 작업 폴더 목록 | Kubernetes 배포 YAML, Helm, `.github/workflows`, Argo CD 없음 |
| 설계 문서 | `db/README.md`, `simulator/CLAUDE.md` | member/simulator-member 설계 문서가 참조되지만 조사 시작 시 파일 없음 |

현재 코드 구조는 `bootstrap → state S3`와 `로컬 Compose PostgreSQL ← 시뮬레이터 골격`이다. CLI의 실제 회원 생성·DB 쓰기 구현도 아직 없으므로 데이터 흐름의 실행 성공을 의미하지 않는다.

## 기존 실습 자료

상위 폴더 `../infra_reuse_analysis.zip` 내부를 메모리에서 열람했다. 아래 표의 경로는 ZIP 내부 `infra_reuse_analysis/`를 기준으로 한다.

| 경로 | 확인한 자료 |
|---|---|
| `extracted/terraform/devops_tf_k8s_ci/infra/` | VPC, Auto Mode EKS, IAM, ECR, MySQL RDS, SG, provider/variables |
| `extracted/docker/devops_tf_k8s_ci/apps/` | nginx WEB, FastAPI/PyMySQL WAS 및 Dockerfile |
| `extracted/kubernetes/devops_tf_k8s_cd/k8s/` | WEB/WAS Deployment·Service, Auto Mode Ingress, dev overlay |
| `extracted/terraform/kafka-elk-efk-opensearch/infra/s3.tf` | 암호화 및 공개 차단 S3, force_destroy=true |
| `extracted/terraform/log_gen/infra/s3.tf` | 데이터 계층용 버킷 및 공개 차단, force_destroy=false |
| `extracted/cicd/` | CI workflow 및 Argo 템플릿 존재 확인. 이번 단계 도입 대상 아님 |
| `risks.md` | 이전 분석 참고. 이번에 직접 읽은 코드와 교차 확인한 내용만 확정 결함으로 사용 |

실습 기본값은 VPC 10.0.0.0/16, 2 AZ 각각 public/app/db subnet, NAT 2개, MySQL Multi-AZ다. 이는 재사용 후보의 기본값이며 현재 프로젝트의 배포 사양이 아니다. ZIP 내 추출된 `.tf`에서 `resource "aws_vpc_endpoint"` 선언은 발견되지 않았다. ZIP에 포함되지 않은 원본 자산까지 없다고 단정하지 않는다.

## 확인하지 않은 항목과 검사 결과

- AWS API 조회, 자격증명 열람, kubeconfig 열람, state 내용 열람은 수행하지 않았다. 계정·profile·기존 리소스·실제 리전·state 소유자 모두 미정이다.
- bootstrap 폴더에는 local state 및 `.terraform/`가 관찰되지 않았다. 다른 PC나 원격 저장소에 state가 없다는 의미는 아니다. bootstrap 기배포 여부부터 확인해야 한다.
- 로컬 Terraform 1.15.8, AWS CLI와 kubectl 실행 파일 존재 확인. CLI 존재가 인증 또는 연결 성공을 의미하지 않는다.
- `terraform -chdir=infra/bootstrap fmt -check -diff`: 종료 코드 0.
- `terraform -chdir=infra/bootstrap validate -no-color`: AWS provider 6.68.0 캐시 부재로 실패. 구성 유효성 통과로 기록하지 않는다.
- init/plan/apply/destroy, Docker 실행, 클러스터 dry-run 및 앱 통합 검증은 미실행. 기존 파일은 수정하지 않았다.
