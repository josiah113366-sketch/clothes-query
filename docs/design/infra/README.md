# AWS 인프라 현황 분석 및 구축 계획

상태: 제안 · 조사일: 2026-10-13 (KST) · 기준 커밋: `bbe9fae`

> 이 폴더는 구현 전 분석 기록이다. 이후 사용자가 Auto Mode와 고가용성을 선택하여 Terraform을 작성했다. 현재 구현·검증 상태는 [실행 안내](../../../infra/IMPLEMENTATION.md)와 [작업 기록](../../tasks/infra-analysis.md)을 우선 참고한다. 아래의 코드 부재 및 provider 미설치 설명은 조사 당시 상태다.

현재 저장소의 코드와 기존 실습 자료를 비교한 분석 문서다. 실제 AWS 배포 상태를 확인한 보고서가 아니다. 기존 코드, state, AWS 리소스를 변경하지 않았다.

루트 `CLAUDE.md`의 설계 문서 위치 규칙에 따라 `docs/design/infra/`에 작성했다. **결정**은 기존 저장소 또는 사용자 요청의 확정 사항, **제안**은 승인 전 대안, **미정**은 추가 확인이 필요한 사항이다.

| 문서 | 내용 |
|---|---|
| [current_state.md](current_state.md) | Git, Terraform, 앱 및 실습 자료의 실제 현황과 조사 한계 |
| [reuse_plan.md](reuse_plan.md) | 파일별 재사용 판단 및 수정 근거 |
| [target_architecture.md](target_architecture.md) | 현재 구조와 목표 차이, 네트워크·권한·스택 의존성 제안 |
| [missing_components.md](missing_components.md) | 신규 작업과 배포 전 결정 사항 |
| [deployment_plan.md](deployment_plan.md) | 승인 후 구현·배포 순서, 검증, 시간 추정 |
| [risks.md](risks.md) | 결함, 보안·데이터 위험, 비용 추정 |

## 핵심 판단

- Git의 Terraform은 state 저장용 S3 bootstrap뿐이다. VPC·EKS·RDS·데이터 S3·ECR·WEB/WAS 배포 코드는 아직 없다.
- 기존 프로젝트는 PostgreSQL과 시뮬레이터의 DB 직접 쓰기를 명시한다. 실습의 MySQL WAS를 그대로 채택하면 현재 DDL 및 설계와 맞지 않는다.
- 실습의 VPC, EKS Auto Mode, WEB/WAS Deployment는 수정 후 재사용 후보다. 리전/AZ 불일치와 Ingress Service 참조 오류를 먼저 고쳐야 한다.
- state S3는 그대로 유지하고 데이터 S3는 별도로 검토한다. 기존 AWS 리소스 및 state의 소유권이 확인되기 전에는 신규 생성 여부를 확정하지 않는다.
- 구현 예상은 앱 수정 담당자가 확보된 경우 약 3~5 업무일이다. WEB/WAS를 별도로 개발해야 하면 일정이 늘어난다. 상세 가정은 배포 계획에 기록했다.

## 열람 및 검증

이 폴더의 Markdown을 순서대로 읽으면 된다. 실행할 배포 스크립트는 없다. 근거 자료는 저장소 파일과 저장소 상위의 `infra_reuse_analysis.zip`이다. 압축 파일의 코드를 실행하거나 프로젝트로 복사하지 않았다.

이번 검증은 Git 상태, 코드 교차 검토, bootstrap의 `terraform fmt -check -diff`까지 완료했다. `terraform validate`는 provider 부재로 실패했고 AWS 연결 검증은 수행하지 않았다. 원격 Git 조회도 연결 실패로 최신 여부를 확인하지 못했다.
