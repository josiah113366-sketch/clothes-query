# 작업 지시서: infra/data-path-prep

> 상태: 완료(확정 가능한 공통 코드·로컬 검증) · 브랜치: `infra/data-path-prep`

## 목표

사용자의 “실측 전 준비” 요청에 따라 통합 데이터 경로에 직접 필요한 선택적 RDS CDC 설정과 서비스별 S3 접근 권한을 코드로 준비한다. 처리량·용량·보존·운영 방식은 임의 확정하지 않는다.

## 먼저 읽을 것

- 루트 `CLAUDE.md`, `infra/CLAUDE.md`.
- `infra/IMPLEMENTATION.md`, RDS 모듈/스택·기존 WAS Pod Identity 구성·기존 tests.
- [데이터 경로 준비](../design/infra/data-path-readiness.md).

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- 실배포·실측 없이 가능한 인프라 코드 준비만 수행한다. 제네레이터·앱/데이터 처리·AI 구현 제외.
- 최신 origin/main `f0a6059`에서 별도 worktree/브랜치를 만든 뒤 `infra/first-stage-checks@7ab22c7`까지 로컬 fast-forward해 기존 기반을 재사용했다. 기존 브랜치/작업 폴더와 원격은 보존한다.
- CDC는 null, 서비스 binding은 빈 map을 기본값으로 두고 실제 규모·서비스 입력을 자동 채우지 않는다.

## 만드는 것

1. 기존 RDS 모듈/스택의 선택적 논리 복제 parameter group과 명시적 slot/sender/WAL 예산 입력.
2. `workload-access` 모듈/스택: 서비스 namespace/ServiceAccount·S3 prefix/object action의 명시적 역할/association. 기존 WAS 역할은 이동하지 않는다.
   필요한 object action과 network S3 endpoint 정책의 불일치를 막기 위해 명시적 optional transport action과 output/입력 검증도 연결한다. 기본 endpoint 권한은 유지한다.
3. mock plan과 README·연결 계약·활성화/실환경 검증 조건.

## 만들지 않는 것

- Kafka 운영 방식·차트·이미지·서비스 규모의 임의 선택, Kafka/Connect·정제/조회 런타임 배포.
- Namespace/ServiceAccount 중복 생성, 기존 계정·state·AWS 조회/변경, DB 계정·publication/slot·재시작.
- 실제 Secret 값·권한 자동 활성화·데이터 삭제·제네레이터·ETL/AI 코드, push·PR·원격 머지.

## 작업 순서

1. 확정 가능한 공통 인프라 범위를 알리고 공식 문서와 현재 코드 확인.
2. 선택적 CDC 및 입력 기반 데이터 접근 코드를 준비.
3. 기존 검사기를 재사용해 정적·mock 검증.
4. 담당 경계·미정 값·실환경 확인 조건을 문서화하고 로컬 커밋.

## 완료 확인

- [x] 기본값에서 새 CDC group/역할/association 생성 없음의 mock 검증.
- [x] 명시적 CDC family/파라미터/DB 연결과 잘못된 입력 검증.
- [x] 서비스별 action/prefix/trust/association 및 wildcard·중복 입력 거부 검증.
- [x] 기존/신규 10개 root fmt·init·validate 및 mock plan 36개 통과.
- [x] 기본 endpoint 권한 유지와 명시적 optional action·workload 요청 불일치 거부 검증.
- [x] 문서 링크·변경 범위·비밀값 패턴·기존 작업 폴더/lock/state 보존 확인.

## 실행 결과

Terraform 1.15.8, AWS provider 6.68.0, Kubernetes provider 2.38.0으로 기존 24개와 CDC 4개·데이터 접근 6개·endpoint 확장 2개 mock plan, 총 36개 통과. 10개 root의 backend 없는 init·validate 및 fmt 통과. 신규 stack lockfile은 기존 검증된 AWS lock을 재사용했다. 검사기는 Git 제외 임시 위치에서 기존 CI 브랜치의 도구를 재사용했으며 신규 보조 도구는 만들지 않았다.

S3 endpoint 기본 action은 유지하고, 추가 요청이 명시된 경우에만 허용 목록을 확장한다. workload-access는 최신 network output과 서비스 action을 대조해 경로에서 차단될 권한 요청을 거부한다. 추가 bucket API는 자동 지원하지 않으며 서비스별 실제 SDK/정책 검증을 남긴다. 기존 작업 폴더 4개와 기존 backend/provider lock/bootstrap·WAS 코드는 변경하지 않았다. 신규/변경 문서 링크와 staged diff·민감 패턴 검사를 확인하고 로컬 커밋으로 보관한다. 원격 변경·배포는 수행하지 않았다.

실제 RDS 파라미터 허용 범위·DB 재시작/slot 복구, IAM/bucket 정책·SDK·서비스 연결, 처리량·부하·복구 성능은 검증하지 않았다. 이 결과는 실환경 배포 준비의 공통 부품 검증이며 전체 파이프라인의 배포 가능/운영 완료 판정이 아니다.

## README 갱신

- `infra/README.md`, `modules/README.md`, `stacks/README.md`, RDS·workload-access README와 tests 설명.
- 미정 입력은 [데이터 경로 준비](../design/infra/data-path-readiness.md)에 모아 기록.
