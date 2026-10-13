# 로컬 인프라 통합 및 Connect 이미지 조치

상태: 진행 중

사용자가 Connect 이미지 취약점 조치·재검증과 로컬 브랜치 통합 후 업로드를 요청했다. 최신 `origin/main`에서 `infra/local-ready`를 만들고 기존 인프라 브랜치를 병합한다. `main` 직접 변경·AWS 배포·ECR 이미지 업로드는 이 작업에 포함하지 않는다.

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
- [ ] 민감 파일·최신 main 확인 후 통합 브랜치 push 및 원격 상태 확인

기존 검사 스냅샷은 [최초 결과](../design/infra/connect-image-security-2026-10-14.md)로 보존한다. 실제 AWS/EKS/RDS 및 GitHub Actions 실행 결과는 로컬 검사와 구분한다.

## 로컬 완료 결과

- 기존 8개 인프라 브랜치 `analysis`, `platform-plan`, `ci`, `first-stage-checks`, `data-path-prep`, `kafka-runtime`, `kafka-followups`, `kafka-validation`이 모두 통합 HEAD의 ancestor임을 확인했다. 원본 branch/worktree는 보존한다.
- 초기 CI add/add 충돌의 `.github/workflows/infra-checks.yml`, `infra/checks/README.md`는 `kafka-validation`의 확장된 최신 내용을 유지했다. 계획 문서에는 작성 당시 기록임을 표시하고 현재 구현으로 연결했다.
- [Connect 조치 후 재검사](../design/infra/connect-image-remediation-2026-10-14.md): 같은 DB에서 Critical 1→0, High 73→35, 전체 511→403. OS High 22 / Java High 13은 남아 있다. 미사용 구성요소 제거와 OS 패치만 수행했으며 broker/exporter 원본 이미지나 Java 라이브러리는 변경하지 않았다.
- Strimzi launcher로 전체 TLS/ACL·CDC·재생성/offset·지표 검사 통과. project `cq-cdc-81b6e09dd3`과 scanner `cq-trivy-c8625aea30`의 임시 자원을 정리했다. image inventory와 플러그인 service loader도 확인했다.
- Terraform fmt·backend 없는 init/validate 10 roots, mock 8 suites/38 plans, 검사기 unit 9개, Helm lint/고정 CRD/입력 거부 18개/metrics selector, actionlint 통과.
- 통합 변경의 로컬 Markdown 링크 오류 0건, 예상 밖 영역 변경 0건, 민감 확장자 파일 0건, Git 공백 오류 0건. 새로 들어오는 16개 커밋의 infra/docs/workflow에서 AWS key·private key·계정 ID 포함 ARN 패턴 발견 0건. 패턴 검사는 완전한 비밀 탐지 보증이 아니다.

원격 업로드 후 아래에 실제 결과를 기록한다. AWS 배포·ECR 업로드·`main` 병합은 수행하지 않는다.

## 원격 확인과 CI 보완

`8a0647d`를 `origin/infra/local-ready`에 push하고 원격 tip 일치를 확인했다. [최초 GitHub 실행](https://github.com/josiah113366-sketch/clothes-query/actions/runs/38454389883)에서 Helm·Kafka 로컬 연결·이미지 scan job은 성공했다. Terraform은 Kubernetes 2.38.0의 Linux `h1` 체크섬이 lockfile에 없어 readonly init 이후 validate에서 실패했다.

공식 registry에서 Windows/Linux 서명된 package를 확인해 apps/compute/tests lockfile에 Linux checksum을 추가했다. 기존 provider 버전·제약은 유지했다. 이 보완은 임시 소스 복사본에서 backend 없는 init과 `providers lock`으로 수행하고 lockfile만 되가져왔다. AWS/state를 읽거나 변경하지 않았다. 보완 후 검증과 원격 결과를 이어 기록한다.
