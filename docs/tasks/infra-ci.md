# 작업 지시서: infra/ci

> 상태: 완료(구현·로컬 검증) · 브랜치: `infra/ci` · 다음 작업: 기반 인프라 병합·플랫폼 결정 후 서비스별 구현

## 목표

사용자의 후속 진행 요청에 따라 AWS 배포 없이 가능한 공용 인프라 검사를 구현한다. Kafka 운영 방식 등 미정 아키텍처를 확정하지 않고, main과 별도 기반 브랜치를 로컬에서 검사할 수 있게 한다.

## 먼저 읽을 것

- 루트 `CLAUDE.md`, `infra/CLAUDE.md`, `docs/tasks/_template.md`.
- `infra/platform-plan@90b26cf`의 플랫폼 계획, `infra/analysis@7cdd4d5`의 기반 코드·테스트.
- [검사 사용법](../../infra/checks/README.md), [workflow](../../.github/workflows/infra-checks.yml).

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- 실제 배포·제네레이터 작업 제외. 사용자 “진행 더 할꺼 있으면 해줘” 범위에서 검사 자동화를 진행한다.
- 기존 두 작업 폴더를 보존하고 최신 origin/main에서 별도 worktree `clothes-query-infra-ci`를 만든다.
- 미병합 계획·기반 브랜치를 이 CI 브랜치에 합치지 않는다. 참조 검사만 수행한다.

## 시작 전 확인

- `git fetch origin` 후 `origin/main=f0a6059`, 기반 `infra/analysis=7cdd4d5` 확인.
- `infra/ci`는 origin/main에서 생성하고 자동 upstream을 해제했다.
- Terraform 1.15.8을 공식 ZIP/SHA256SUMS로 검증한 뒤 Git 제외 `.cache/`에 준비했다. 전역 PATH는 변경하지 않았다.
- 검사 Python 환경은 `.cache/infra-checks-venv`이며 앱/시뮬레이터 환경과 분리했다.

## 만드는 것

1. `infra/checks/check_infra.py`: Git 추적 소스/커밋의 임시 복사본에서 fmt·backend 없는 init·validate·mock plan 실행.
2. `infra/checks/requirements.txt`: 검사 전용 HCL parser 및 의존성 고정.
3. `infra/checks/tests/test_check_infra.py`: 실제 provider·implicit apply·누락 mock 거부, 인증/CLI 환경 및 소스/state 분리 검증.
4. `.github/workflows/infra-checks.yml`: 인증 없는 검사 workflow.
5. `infra/checks/README.md` 및 이 작업 기록.

## 만들지 않는 것

- Kafka·Spark·Airflow 배포 코드와 아키텍처 결정, 앱·제네레이터 변경.
- AWS/클러스터 접속·실환경 plan·apply·destroy·state 작업.
- workflow 업로드/원격 실행, push·PR·머지, 기존 코드 자동 포맷.

## 작업 순서

1. 후속 범위를 알리고 별도 브랜치/worktree 생성.
2. 공식 도구·Actions 참조를 확인하고 로컬 도구 준비.
3. 검사기·단위 검증·workflow·문서 작성.
4. 아래 완료 확인을 실행하고 결과 기록 후 로컬 커밋.

## 완료 확인

- [x] 검사기 단위 검증 통과.
- [x] main 기준 bootstrap fmt·init·validate 통과.
- [x] 기반 커밋 기준 모든 root와 mock test 검사 통과.
- [x] workflow YAML·참조·권한 및 문서 링크 확인.
- [x] 기존 작업 폴더/state/lockfile 변경 없음, 비밀값·변경 범위·diff 검사.

## 실행 결과 (2026-10-14 KST)

- 검사기 단위 검증: 9개 통과. implicit/explicit apply, 누락 mock, 실제 provider, 별도 alias·하위 module 및 임시 복사/인증 분리 확인.
- main `f0a6059`: bootstrap 1개 root의 fmt·backend 없는 init·validate 통과.
- 기반 `infra/analysis@7cdd4d5`: bootstrap·7개 stack·tests 총 9개 root의 fmt·init·validate 통과. mock suite 3개, plan run 16개 모두 통과.
- 로컬 actionlint 1.7.12로 GitHub Actions YAML/표현식 검사 통과. 공식 release checksum 검증 후 Git 제외 `.cache/`에 준비했다. 원격 Actions 실행은 미실행.
- Actions 3개의 고정 SHA가 공식 저장소의 해당 tag commit임을 API로 확인했다. 권한은 contents read이며 AWS/클러스터 인증과 배포 단계는 없다.
- 신규 Markdown 로컬 링크 3개 오류 0건. 계정 ID·실제 access key·private key 패턴 및 staged diff 공백 검사에서 발견 0건.
- 기존 `clothes-query`의 infra/analysis와 `clothes-query-platform-plan`은 clean 상태 유지. 기존 Terraform·provider lock·state 파일을 변경하지 않았다.

실환경 plan·클러스터 연결·AWS 권한·리전/버전 지원 조합·스토리지/장애 검증은 미실행이다. 소스·mock 검증 결과를 실배포 성공으로 해석하지 않는다. 변경은 신규 검사 파일·workflow·문서로 한정하고 로컬 커밋으로 남긴다. push·PR·머지는 수행하지 않는다.

## README 갱신

- 신규 `infra/checks/README.md`에서 로컬/CI 사용법 및 제한 설명.
- 기존 기반 브랜치의 파일과 README는 수정하지 않는다.
