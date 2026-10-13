# 작업 지시서: infra/first-stage-checks

> 상태: 완료(코드 보완·로컬 검증) · 브랜치: `infra/first-stage-checks`

## 목표

원래 1차 범위인 VPC·EKS·WEB/WAS·RDS·S3의 이미 정해진 연결 설정을 앱·AWS 인증 없이 검증한다. 확정된 코드 오류만 수정하고 미정인 앱 구현·Secret 공급 도구·실배포 입력은 보류한다. 새 플랫폼·보조 도구를 만들지 않는다.

## 먼저 읽을 것

- 루트 `CLAUDE.md`, `infra/CLAUDE.md`.
- `infra/IMPLEMENTATION.md`, `infra/modules/apps/`, `infra/stacks/apps/`, `infra/tests/`.
- 기존 `docs/tasks/infra-analysis.md`와 네트워크 plan 기록.

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- 사용자가 불분명한 항목은 넘기고 가능한 기존 범위의 작업을 요청했다.
- 제네레이터·앱·Kafka 등 후속 플랫폼 구현과 AWS 배포는 수행하지 않는다.
- 기존 작업 폴더·브랜치를 보존한다. 최신 origin/main `f0a6059`에서 별도 worktree/브랜치를 만든 뒤 기존 `infra/analysis@7cdd4d5`를 로컬로 통합해 검토 기반을 준비했다. 원격 main/브랜치는 변경하지 않았다.

## 만드는 것

- `apps-connections.tftest.hcl`: HTTPS ingress→WEB→WAS, DB 설정/Secret 참조, Pod Identity, S3 prefix 권한과 기초 단계/잘못된 입력 검증.
- 확인된 배포 입력 검증 오류 수정. 기존 이름·리소스 수·네트워크·권한 범위는 바꾸지 않는다.
- 기존 구현/검사 안내의 실제 코드와 다른 설명 보완 및 이 작업 기록.

## 만들지 않는 것

- WEB/WAS 소스·이미지·실제 Secret 값·인증서·DNS.
- DB 계정 생성/스키마 적용, 실제 backend/state·AWS·클러스터 조작.
- 새 검사 도구·비용 계산기·플랫폼 배포 구성·CI 변경, push·PR·원격 머지.

## 작업 순서

1. 기존 코드와 기록을 대조하고 별도 검토 브랜치를 준비한다.
2. 기존 연결 계약과 잘못된 입력을 검사하는 mock plan을 추가한다.
3. 수정 전 실패를 확인한 뒤 필요한 조건만 수정한다.
4. fmt·validate·기존/추가 mock plan을 검증하고 결과를 기록한다.

## 완료 확인

- [x] 수정 전 입력 검증 실패 재현.
- [x] apps 모듈과 stack에서 동일한 입력 조건 적용.
- [x] 기존 및 추가 mock plan 통과, root validate와 fmt 통과.
- [x] 원본 작업 폴더·state·lockfile·팀원 코드 변경 없음.
- [x] 문서 링크·비밀값 패턴·diff 확인 후 로컬 커밋.

## 실행 결과 (2026-10-14 KST)

- 기존 코드에서 `certificate_arn = ""`가 유효성 검사 오류를 내지 않아 `expect_failures = [var.certificate_arn]` 테스트가 실패하는 것을 재현했다.
- apps 모듈/stack의 인증서·hostname 검사를 `trimspace` 후 길이 확인으로 보완했다. 기초 단계의 null 입력 허용은 유지한다. ARN 문법·인증서 존재/리전·DNS 소유권을 확인하는 변경은 아니다.
- 기존 검사기를 Git 제외 임시 경로에서 재사용해 소스 임시 복사본을 검사했다. 새 검사 도구와 AWS 자격증명을 추가하지 않았다.
- Terraform 1.15.8 / AWS provider 6.68.0 / Kubernetes provider 2.38.0으로 9개 root의 fmt·backend 없는 init·validate 통과.
- 기존 mock plan 16개와 추가 8개, 총 24개 통과. HTTPS/프록시/DB 설정·Secret 참조/Pod Identity/S3 prefix와 기초 단계·잘못된 입력의 계약을 확인했다.
- HCL 파싱으로 apps 모듈과 stack의 두 변수 검증 조건이 동일함을 확인했다. 실제 앱과 AWS 연결 검증은 미실행이다.
- 기존 세 작업 폴더는 clean 상태 유지. 기존 provider lock·backend·state·앱 코드는 변경하지 않았다.
- 구현 안내의 기초 단계에는 Metrics Server와 IAM도 생성됨을 명시하고, 기존 network 실환경 plan 기록과 불일치하던 설명을 정정했다. 과거 AWS 기록을 재조회 결과로 표시하지 않는다.

## README 갱신

- `infra/tests/README.md`에 기존 연결 계약 검사 범위 추가.
- `infra/IMPLEMENTATION.md`의 기초 단계 생성 항목과 network plan 기록 설명 정정.

## 보류 항목

실제 앱과의 호환성, DB 앱 계정/Secret 공급, TLS·DNS·이미지 digest 및 비공개 RDS/관리자 입력은 자료가 없어 확인하지 않았다. 실제 연결·복구·후속 실환경 plan은 배포 PC에서 검증한다.
