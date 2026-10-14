# 작업 지시서: infra/platform-plan

> 상태: 완료(계획 문서 작성·검증) · 브랜치: `infra/platform-plan` · 다음 작업: 결정 확정 후 `infra/platform`

## 목표

사용자 흐름도의 공용 플랫폼 영역을 별도 작업으로 나누고, 현재 준비된 기반·누락·담당 경계·구현 전 결정·검증 순서를 정리한다. 제네레이터와 데이터/앱 로직은 제외한다. 이번 완료는 계획 문서 작성 완료이며 플랫폼 구현·배포 완료가 아니다.

## 먼저 읽을 것

- 루트 `CLAUDE.md`, `infra/CLAUDE.md`, `docs/tasks/_template.md`.
- main의 `infra/README.md` 및 기반 브랜치 `infra/analysis@7cdd4d5`의 `infra/README.md`, `infra/IMPLEMENTATION.md`, `infra/SCALING.md`, 관련 modules/stacks/tests 및 작업 기록.
- 상위 `infra_reuse_analysis.zip`의 분석 보고서·추출 파일 목록.
- [플랫폼 계획](../design/platform/README.md)과 그 하위 문서.

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- 기존 `infra/analysis`와 작업을 분리하고 이 PC에서는 실제 배포하지 않는다.
- 사용자의 “해보자”로 앞서 제안한 플랫폼 계획 문서 작업을 진행한다.
- 기존 작업 폴더를 보존하고, 최신 origin/main에서 별도 Git worktree/브랜치를 만든다.

## 시작 전 확인

- 최초 작업 폴더는 `infra/analysis@7cdd4d5`, 미커밋 변경 없음.
- `git fetch origin` 성공. `origin/main=f0a6059` 확인.
- 기반 인프라 커밋은 main에 미병합. 병합·복사하지 않고 참조 근거로만 사용.
- 새 worktree `clothes-query-platform-plan` 및 `infra/platform-plan` 생성. origin/main 자동 upstream은 해제해 원격 배포 브랜치로 오인하지 않게 함.
- Python 3.12·kubectl·Docker 실행 파일 확인. Terraform/Helm은 PATH에서 미확인. Docker daemon·AWS 인증·클러스터 연결은 조사하지 않음.

## 만드는 것

`docs/design/platform/`에 다음 신규 문서를 작성한다.

1. `README.md`: 범위·근거·상태·문서 지도.
2. `inventory.md`: main과 기반 브랜치의 현황, 누락, 실습 재사용 후보.
3. `ownership.md`: 담당 경계와 팀원별 입력/인수인계 표.
4. `decisions.md`: 미정 항목, 공식 문서 근거, 용량 입력 양식.
5. `implementation-plan.md`: 후속 브랜치·구현 순서·로컬/실환경 검증 기준.

## 만들지 않는 것

- Terraform/Helm/Kubernetes/Docker/CI 실행 코드, 설치·서비스 구동.
- 제네레이터·Consumer·Spark job·Airflow DAG·대시보드·탐지/에이전트 코드.
- 실제 버전·규모·예산·Secret 공급 제품의 임의 확정.
- AWS 조회/변경, 기존 state 읽기/변경, 기반 브랜치 수정, push·PR 생성.

## 작업 순서

1. 사용자에게 계획을 제시하고 기존 승인 범위로 진행한다.
2. 최신 원격과 기반 커밋을 확인하고 별도 worktree를 만든다.
3. 두 브랜치와 ZIP을 대조하고 공식 문서로 기술적 선행 조건을 확인한다.
4. 신규 계획 문서와 작업 기록을 작성한다.
5. 아래 완료 확인을 실제 실행한 뒤 결과를 기록한다.

## 완료 확인

- [x] 최신 origin/main 확인 후 브랜치 분리, 기존 infra/analysis 보존.
- [x] main·기반 브랜치·실배포 기록의 차이와 관측 한계 명시.
- [x] 제네레이터 제외, 앱/데이터 로직·팀원 values 담당 경계 명시.
- [x] Kafka/Connect·CDC·영구 볼륨·Spark/Airflow·관측·CI·권한/용량의 결정 목록 작성.
- [x] 신규 Markdown의 로컬 링크 대상 존재 확인.
- [x] diff 공백 오류, 계정 ID/비밀값 패턴, 허용 파일 범위 확인.
- [x] 기존 작업 폴더와 main 파일 내용 변경 없음 확인.

검증 결과: Python 3.12로 신규 Markdown 6개, 로컬 링크 10개, 기반 커밋 파일 참조 7개를 확인해 오류 0건. 계정 ID·AWS access key·private key·비밀값 대입 형태의 패턴 검사에서 발견 0건(완전한 비밀 탐지 보증은 아님). `git diff --cached --check` 공백 오류 0건. 기존 작업 폴더는 `infra/analysis@7cdd4d5`와 clean 상태를 유지하며, 계획 브랜치는 기존 추적 파일을 변경하지 않는다. 변경은 신규 Markdown 6개로 한정한다.

Terraform/Helm·AWS·클러스터 검증은 이번 문서 작업의 실행 대상이 아니다. 플랫폼 기술 요건은 2026-10-14에 AWS·Debezium·Spark·Airflow 공식 문서를 조회해 근거 링크를 기록했다. push·PR은 수행하지 않았다.

사용자가 기존 커밋 기록의 작성자 정보가 본인 것임을 확인했다. 해당 정보를 이 저장소 범위의 Git 설정에 적용하고 신규 문서 6개를 로컬 커밋으로 보관한다. 전역 Git 설정과 원격 저장소는 변경하지 않는다.

## README 갱신

- 신규 `docs/design/platform/README.md`에서 모든 계획 문서와 작업 기록 연결.
- main의 기존 `infra/README.md` 및 미병합 분석 문서는 수정하지 않는다. 기반 코드 병합 후 후속 구현에서 인프라 지도의 링크·상태를 갱신한다.
