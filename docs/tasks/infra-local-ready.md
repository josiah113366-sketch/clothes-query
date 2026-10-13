# 로컬 인프라 통합 및 Connect 이미지 조치

상태: 완료 (요청한 로컬 이미지 조치·재검증·브랜치 통합·업로드·원격 CI 확인 범위 / 잔여 취약점·실제 배포는 별도)

사용자가 Connect 이미지 취약점 조치·재검증과 로컬 브랜치 통합 후 업로드를 요청했다. 최신 `origin/main`에서 `infra/local-ready`를 만들고 기존 인프라 브랜치를 병합한다. `main` 직접 변경·AWS 배포·ECR 이미지 업로드는 이 작업에 포함하지 않는다.

## 다른 로컬에서 읽는 순서

최초 인수인계서의 기존 코드/state 보존·1차 VPC/EKS/WEB/WAS/RDS/S3 준비를 기준으로 삼았다. 이후 사용자가 승인한 로컬 연결 검증·EKS 자체 운영 Kafka·관측 설정·CI·이미지 조치·브랜치 통합과 push를 단계별 지시서로 추가했다. 제네레이터·업무 앱·Consumer/Spark/DAG/AI 로직은 이 작업에서 구현하지 않았다. WEB/WAS 소스가 없어 포트·경로는 인프라 연결 계약이며 실제 앱과 맞는지는 담당자 확인이 남아 있다.

1. 최신 `origin/infra/local-ready`를 별도 작업 폴더에서 확인한다. 기존 `infra/analysis` 폴더만 보면 후속 변경이 보이지 않는다.
2. [인프라 지도](../../infra/README.md)에서 스택 순서·의존 관계·기본 비활성 구성을 읽는다.
3. 아래 표의 작업 지시서에서 변경 목적·완료 확인·실제 결과를 읽고 연결된 README에서 입력과 재실행 방법을 확인한다.
4. [데이터 경로 준비 현황](../design/infra/data-path-readiness.md)과 [이미지 잔여 취약점](../design/infra/connect-image-remediation-2026-10-14.md)을 보고 다음 작업을 정한다.

새 폴더에 받는 예시:

```powershell
git clone --branch infra/local-ready https://github.com/josiah113366-sketch/clothes-query.git clothes-query-infra-review
cd clothes-query-infra-review
```

기존 배포 PC의 미커밋 변경·비공개 입력·state는 clone에 포함되지 않는다. 기존 폴더를 덮어쓰거나 초기화하지 않는다. 다른 로컬의 미커밋 코드는 이번 통합에서 대조하지 못했다. 실제 AWS 작업 전에는 기존 관리 state·리소스와 코드의 소유 관계를 해당 환경에서 확인한다.

| 단계와 지시서 | 핵심 변경·판단 | 구현·재검증 진입점 |
|---|---|---|
| [기반 분석·구현](infra-analysis.md) | 기존 실습 재사용, Auto Mode·2 AZ·WEB/WAS·RDS·S3·state 경계 | [기반 실행 안내](../../infra/IMPLEMENTATION.md), 각 stack README |
| [플랫폼 계획](infra-platform-plan.md) | 인프라/데이터 담당 경계와 결정·미정 항목. 당시 계획은 후속 승인으로 일부 구현됨 | [계획 지도](../design/platform/README.md) |
| [초기 CI](infra-ci.md) | 인증 없는 Terraform 복사본 검사·mock provider 강제 | [검사 사용법](../../infra/checks/README.md) |
| [1차 연결 검사](infra-first-stage-checks.md) | WEB/WAS 연결 계약, HTTPS·이미지 입력 검증, foundation 배포 분리 | [apps](../../infra/stacks/apps/README.md), [mock 검사](../../infra/tests/README.md) |
| [데이터 경로 준비](infra-data-path-prep.md) | 선택적 RDS 논리 복제, 서비스별 S3 prefix/Pod Identity·endpoint 권한 연결 | [RDS](../../infra/stacks/rds/README.md), [workload-access](../../infra/stacks/workload-access/README.md) |
| [Kafka runtime](infra-kafka-runtime.md) | Strimzi·Kafka/Connect·영구 저장소·TLS/ACL·플러그인 이미지 | [Kafka 설치/입력](../../infra/platform/kafka/README.md), [Helm 검증](../../infra/platform/kafka/verify/README.md) |
| [Kafka 후속 준비](infra-kafka-followups.md) | 선택적 Connect ECR, 로컬 CDC, JMX/consumer lag | [ECR](../../infra/stacks/ecr/README.md), [로컬 검사](../../infra/platform/kafka/local-smoke/README.md), [지표](../../infra/platform/kafka/metrics/README.md) |
| [추가 검증](infra-kafka-validation.md) | mTLS·권한 거부, Kafka 재생성/offset 보존, 최초 스캔·CI 연결 | [통합 검사 명령](../../infra/checks/README.md) |
| 이 통합 지시서 | 8개 branch 통합, Connect 조치, Linux checksum 보완, 원격 CI 확인 | 아래 실제 결과와 [이미지 조치 기록](../design/infra/connect-image-remediation-2026-10-14.md) |

이전 단계 지시서의 “미배포/미정/미실행”은 해당 단계의 기록이다. 현재 결과는 이 통합 지시서와 각 기능의 최신 README를 우선한다. 특히 `infra/IMPLEMENTATION.md`의 ECR 배포 기록은 이전 환경의 기록이며 이 PC가 AWS 상태를 새로 확인한 결과가 아니다.

## 브랜치 생성과 통합 관계

`origin/main@f0a6059`에서 `infra/local-ready`를 생성했다. 그다음 `infra/analysis@7cdd4d5`가 이미 병합된 `infra/kafka-validation@f06d195`의 누적 구현을 fast-forward로 반영하고, `infra/platform-plan@90b26cf`와 `infra/ci@0006086`을 병합했다. 이후 이 문서의 이미지 조치와 Linux 체크섬 보완을 추가했다. 따라서 main에서 시작했으며 analysis의 변경도 전부 포함한다. 원격 `main`에 통합한 것은 아니다.

`infra/analysis`와 비교하면 그동안 main에 들어간 팀원 변경도 보인다. 이 인프라 작업 자체의 변경을 검토할 때는 최신 main과 통합 브랜치를 비교한다.

```powershell
git fetch origin
git diff --stat origin/main...origin/infra/local-ready
git log --oneline origin/main..origin/infra/local-ready
```

## 결정과 범위

- `infra/kafka-validation`의 누적 구현을 이어받고 별도로 남은 `infra/platform-plan`, `infra/ci` 이력을 병합한다. 초기 CI의 add/add 충돌 두 파일은 이미 확장 검증을 포함한 최신 내용을 유지한다.
- Connect 전용 이미지에서 실행하지 않는 `/opt/cruise-control`, `/opt/kafka-exporter`를 제거한다. JMX agent·Kafka/Connect·Debezium은 유지한다. broker와 lag exporter의 원본 Strimzi 이미지는 변경하지 않는다.
- 공개 UBI 저장소에서 확인한 curl/libcurl/pcre2/pcre2-syntax 패치를 정확한 RPM 버전으로 고정한다. 취약점 ignore·severity 재분류·개별 Java jar 덮어쓰기는 하지 않는다.
- 수정 이미지의 전체 취약점 검사와 실제 mTLS/ACL·CDC·재생성 데이터/offset·지표 검증을 실행하고 잔여 결과를 기록한다.
- 통합 브랜치에서 Terraform/Helm/CI 검사와 변경 범위·비밀값 검토 후 사용자 요청에 따라 이 브랜치 하나를 원격에 push한다. 기존 로컬 브랜치/worktree는 복구용으로 보존한다.

## 완료 확인

- [x] 실제 이미지 구성과 공식 릴리스·공개 OS 업데이트 확인
- [x] Connect 이미지 조치·플러그인 및 Strimzi 시작 경로 확인
- [x] 전체 스캔 전후 결과와 잔여 취약점·조치 한계 기록
- [x] TLS/ACL·CDC·재생성/offset·지표 재검증 및 임시 자원 정리
- [x] 통합 Terraform/Helm/CI 검사와 모든 대상 브랜치 포함 확인
- [x] 민감 파일·최신 main 확인 후 통합 브랜치 push 및 원격 상태 확인

기존 검사 스냅샷은 [최초 결과](../design/infra/connect-image-security-2026-10-14.md)로 보존한다. 실제 AWS/EKS/RDS 및 GitHub Actions 실행 결과는 로컬 검사와 구분한다.

## 로컬 완료 결과

- 기존 8개 인프라 브랜치 `analysis`, `platform-plan`, `ci`, `first-stage-checks`, `data-path-prep`, `kafka-runtime`, `kafka-followups`, `kafka-validation`이 모두 통합 HEAD의 ancestor임을 확인했다. 원본 branch/worktree는 보존한다.
- 초기 CI add/add 충돌의 `.github/workflows/infra-checks.yml`, `infra/checks/README.md`는 `kafka-validation`의 확장된 최신 내용을 유지했다. 계획 문서에는 작성 당시 기록임을 표시하고 현재 구현으로 연결했다.
- [Connect 조치 후 재검사](../design/infra/connect-image-remediation-2026-10-14.md): 같은 DB에서 Critical 1→0, High 73→35, 전체 511→403. OS High 22 / Java High 13은 남아 있다. 미사용 구성요소 제거와 OS 패치만 수행했으며 broker/exporter 원본 이미지나 Java 라이브러리는 변경하지 않았다.
- Strimzi launcher로 전체 TLS/ACL·CDC·재생성/offset·지표 검사 통과. project `cq-cdc-81b6e09dd3`과 scanner `cq-trivy-c8625aea30`의 임시 자원을 정리했다. image inventory와 플러그인 service loader도 확인했다.
- Terraform fmt·backend 없는 init/validate 10 roots, mock 8 suites/38 plans, 검사기 unit 9개, Helm lint/고정 CRD/입력 거부 18개/metrics selector, actionlint 통과.
- 통합 변경의 로컬 Markdown 링크 오류 0건, 예상 밖 영역 변경 0건, 민감 확장자 파일 0건, Git 공백 오류 0건. 새로 들어오는 16개 커밋의 infra/docs/workflow에서 AWS key·private key·계정 ID 포함 ARN 패턴 발견 0건. 패턴 검사는 완전한 비밀 탐지 보증이 아니다.

원격 업로드와 CI 결과는 아래에 기록한다. AWS 배포·ECR 업로드·`main` 병합은 수행하지 않았다.

## 원격 확인과 CI 보완

`8a0647d`를 `origin/infra/local-ready`에 push하고 원격 tip 일치를 확인했다. [최초 GitHub 실행](https://github.com/josiah113366-sketch/clothes-query/actions/runs/38454389883)에서 Helm·Kafka 로컬 연결·이미지 scan job은 성공했다. Terraform은 Kubernetes 2.38.0의 Linux `h1` 체크섬이 lockfile에 없어 readonly init 이후 validate에서 실패했다.

공식 registry에서 Windows/Linux 서명된 package를 확인해 apps/compute/tests lockfile에 Linux checksum을 추가했다. 기존 provider 버전·제약은 유지했다. 이 보완은 임시 소스 복사본에서 backend 없는 init과 `providers lock`으로 수행하고 lockfile만 되가져왔다. AWS/state를 읽거나 변경하지 않았다. 보완 후 검증과 원격 결과를 이어 기록한다.

보완 후 Windows 로컬 10 roots/38 mock plan을 재검증했다. `8bbd72c`를 같은 통합 브랜치에 push한 뒤 [최종 GitHub 실행](https://github.com/josiah113366-sketch/clothes-query/actions/runs/38455289322)에서 Terraform·Helm·Kafka TLS/ACL/CDC/재생성/지표·Connect image scan **4개 job 모두 success**를 확인했다. Ubuntu 24.04의 실제 실행 결과이며 AWS/EKS 배포 검증은 아니다. 원격 scanner 집계도 Critical 0/High 35/Medium 241/Low 127이다. scan은 report-only이며 잔여 취약점이 배포 승인된 것은 아니다.

검증된 구현·lockfile 기준은 `8bbd72c`다. 이후 마무리와 인수인계 보완 커밋은 문서만 변경하며 runtime 소스·설정·lockfile을 바꾸지 않는다. 원격 업로드 대상은 [infra/local-ready](https://github.com/josiah113366-sketch/clothes-query/tree/infra/local-ready) 하나다. 기존 8개 local branch/worktree를 보존했고 `main`은 `f0a6059`로 유지했다. PR 생성과 `main` 병합은 수행하지 않았다.
