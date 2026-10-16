# 후속 구현과 검증 순서

상태: 제안 · 구현 명령 실행·배포 완료 기록이 아님 · 2026-10-14

## 브랜치와 파일의 경계

| 순서 | 브랜치 제안 | 범위 | 시작 조건 |
|---|---|---|---|
| 0 | `infra/platform-plan` | 현재 구성·담당 경계·결정 목록·검증 계획 | 이번 문서 작업 |
| 1 | `infra/platform` | 합의된 Kafka/Connect의 실행 기반, namespace·RBAC·스토리지·Secret 참조 | D01~D06·D10의 필요한 부분 결정, 기반 인프라 main 병합 |
| 병행 선행 | 별도 기반 변경 브랜치(이름은 구현 시 결정) | RDS CDC 파라미터 그룹·SG·권한 전달 기반 | 기반 담당 PC와 범위 조율. 같은 파일 동시 수정 금지 |
| 2 | `infra/observability` | 공용 지표·로그·인프라 알림·접근/보존 | 수집 제품·대상·자원·수신처 결정 |
| 3 | `infra/ci` | 인증 없는 fmt/validate/mock·Helm 검사부터 | 실제 배포 구조·버전과 검증 명령 확정 |
| 이후 | 서비스별 후속 인프라 브랜치 | Consumer·Spark·Airflow·대시보드·에이전트 실행 기반 | 담당자 입력 및 서비스별 실행 방식 확정 |

한 PR에 모든 서비스를 넣지 않는다. `infra/platform`이 커지면 Kafka 기반과 Connect 런타임을 별도 브랜치/PR로 추가 분리한다. 후속 브랜치는 계획 브랜치의 미병합 HEAD에서 연쇄 생성하지 않고, 관련 선행 변경이 합쳐진 최신 main에서 만든다.

## state와 배포 도구

기존 EKS state와 그 위의 Kubernetes/Helm state는 분리한다. 기존 `infra/stacks/platform/` 관례를 우선 검토하되, 실제 stack/state 분할은 D12에서 결정한다. 새 state key는 기존 것과 겹치지 않아야 하며 기존 backend migration·import·state 이동은 이번 계획에 포함하지 않는다.

namespace·StorageClass·CRD·operator·Helm release·워크로드별 소유자를 기록한다. Terraform과 GitOps가 같은 리소스를 중복 관리하지 않게 한다. CRD 설치와 이를 사용하는 custom resource의 검증/plan은 실제 API 준비 순서에 맞춰 분리한다. mock 성공으로 실제 CRD schema 검증을 대체하지 않는다.

관리형 Kafka가 선택되면 EKS broker/PVC 구성은 만들지 않고 관리형 서비스의 네트워크·인증·권한·연결 산출물로 바꾼다. 별도 Spark/Airflow 실행 환경이 선택되면 EKS에 중복 설치하지 않는다.

## 이 PC에서 할 일

1. 팀원 입력과 결정된 서비스 범위를 작업 지시서에 기록한다.
2. 구현 단계에 필요한 Terraform/Helm·schema 검사 도구를 준비하고 버전을 고정한다. 이번 문서 작업에는 도구 설치가 필요하지 않다.
3. 비밀 없는 설정 예제와 최소한의 배포 코드를 작성한다. 아직 전달받지 않은 비밀·실제 주소는 placeholder/참조로 둔다.
4. Terraform 변경에는 `fmt -check`·backend 없는 초기화·`validate`와 의미 있는 mock 테스트를 실행한다. 검증용으로 가짜 원격 state를 만들지 않는다.
5. 차트 선택 시 `helm lint`·`helm template`와 렌더링 schema 검사를 실행한다. 차트와 이미지 버전을 고정하고, 생성된 Secret/민감한 렌더링 결과는 Git에 올리지 않는다.
6. 도구·리소스가 허용하면 일회용 로컬 환경에서 서비스 시작·재시작·설정 연결을 확인한다. 로컬 DB/메시지에는 실제 개인정보를 사용하지 않는다.
7. 코드·검증 결과·필수 입력·실환경 미검증 항목을 배포 PC에 전달한다.

로컬 검증으로 EBS provisioning, AWS IAM/Pod Identity, ALB, RDS failover나 실제 AZ 장애를 확인했다고 기록하지 않는다. 이번 브랜치는 Markdown만 추가하므로 Terraform·컨테이너 테스트는 실행 대상이 아니다.

## 배포 PC의 단계별 완료 조건

아래는 향후 담당자가 승인된 환경에서 수행할 검증표다. 이번 PC에서 실행하지 않는다.

| 단계 | 선행 조건 | 완료 기준 | 담당 |
|---|---|---|---|
| 기반 인프라 | 최신 main, 기존 자산/state 소유권, 승인된 입력·plan | EKS Ready·필요 노드/시스템 Pod 정상·기반 경로 일치 | 인프라 |
| 영구 볼륨 | EKS 자체 운영 선택, StorageClass·보존 정책 | PVC Bound, Pod 재시작 후 검증 데이터 유지, AZ 제약과 복구 방식 확인 | 인프라 |
| Kafka | 인증·주소·스토리지/관리형 준비 | 허용 클라이언트 produce/consume, 비허용 접근 거부, 선택한 장애/보존 목표 확인 | 인프라 + 수집 |
| Connect | 버전/플러그인 이미지·내부 저장·Secret·API 접근 준비 | worker·커넥터 상태 정상, 재시작 후 offset·설정 유지 | 인프라 + CDC |
| DB CDC | parameter group 적용 상태, 전용 계정, allowlist·PII 계약 | 검증 테이블의 승인된 변경이 Kafka에 도착, 제외 데이터 미노출, WAL/slot 관측 | DB/CDC + 인프라 |
| Consumer/Bronze | 담당자 이미지, S3 역할·전용 검증 prefix | 허용 prefix의 Put/Get 및 비허용 접근 거부, 이벤트의 Bronze 적재·재처리 계약 확인 | 수집 + 인프라 |
| Spark/Airflow | 실행 방식·이미지·metadata/로그·권한 준비 | 최소 작업 성공·실패/재시도·동시성/권한 확인. 변환 정합성은 담당자가 별도 확인 | 정제/오케스트레이션 + 인프라 |
| 관측 | 선택한 수집 제품·지표·로그·수신처 | 대상 관측 가능, PII/Secret 미노출, 승인된 테스트 알림 전달 | 인프라 + 지표 담당 |
| 인수인계 | 정상/장애 검증 결과와 운영 문서 | 팀원 접속·배포·롤백·소유자 확인, 관리 대상 stack의 후속 plan 변경 검토 | 인프라 |

재시작·장애·권한 거부 시험은 승인된 검증 리소스에서 수행한다. DB 변경·데이터 삭제·slot 제거·PVC 삭제·전체 destroy를 자동 복구 수단으로 넣지 않는다. 보존 대상과 복구 순서를 먼저 문서화한다.

## 완료를 기록하는 방법

서비스마다 `코드 작성 → 로컬 검증 → 실배포 → 연결/복구 검증`을 별도로 기록한다. 실행하지 않은 단계에는 “미실행”과 이유를 남긴다. 버전/리전 지원·quota·실제 IAM·스토리지 동작은 배포 시 확인한다.

이번 계획의 완료 조건은 문서·담당 경계·미정 항목·검증 기준 정리다. 플랫폼 운영 준비 완료 조건과 구분한다.
