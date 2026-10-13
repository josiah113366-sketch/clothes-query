# 구현 및 배포 계획

상태: 제안 · 아래 명령/검증은 향후 절차이며 실행 완료 기록이 아님

## 0. 현재 분석 이후 선행 확인

최신 원격 main을 확인한 뒤 기존 로컬 변경을 보존하여 작업 브랜치를 만든다. AWS/state 담당자에게 bootstrap을 실행했던 환경과 local state 보관 위치를 확인한다. 대상 계정/profile이 정해지면 읽기 전용으로 VPC/subnet/route, EKS/node/IAM, RDS/백업, S3 설정 및 ECR을 조회하여 소유 state와 대응시킨다. 공개 문서에는 실제 계정 ID·endpoint·state를 남기지 않는다.

bootstrap 버킷이 이미 있는데 local state가 없으면 새 apply로 복구하지 않는다. 소유 state 회수 또는 승인된 import 계획을 먼저 마련한다. state key는 스택마다 유일해야 하며 기존 state를 새 root에 임의 연결하지 않는다.

## 1. 구현 순서

1. [결정 목록](missing_components.md)을 해소하고 네트워크·EKS 방식·DB·앱 계약·비용 상한을 확정한다.
2. 실습 VPC 패턴을 `infra/modules/`와 `infra/stacks/network/` 관례로 분리한다. subnet/route/NAT/S3 Gateway Endpoint를 준비한다.
3. 선택한 EKS 운영 방식에 맞게 eks 스택, 역할, access entry, API 접근 제한과 로그 보존을 작성한다.
4. 별도 RDS/데이터 S3/ECR 역할의 스택을 작성한다. 실제 명칭은 합의 후 결정한다. DB SG 입력은 실제 workload SG로 연결한다.
5. 앱 담당자가 예제의 PostgreSQL 전환, 안전한 DB 검증, S3 SDK 접근을 구현한다. WEB은 Service 경로에 맞추고 이미지 digest를 고정한다.
6. Deployment/Service, 설정 및 Secret 공급, ServiceAccount IAM, Ingress를 준비한다. Ingress 참조 오류·metadata 라벨 오류를 수정한다. EKS와 Kubernetes provider state를 분리한다.
7. 모듈/스택 README와 기존 infra 지도 변경안은 구현 단계의 별도 수정으로 준비한다. 이번 분석은 기존 파일을 수정하지 않는다.

## 2. 승인 전 검증 및 plan

- provider lock을 보존한다. 승인된 구현 작업 환경에서 필요한 provider를 설치하여 `terraform fmt -check`, `terraform validate`를 수행한다. 현재 bootstrap validate는 provider 부재로 미완료다.
- 새 backend는 버킷/key/리전을 담당자와 대조하고 초기화한다. `init -migrate-state`, import, state mv/rm/force-unlock을 자동 실행하지 않는다.
- network → eks → 종속 스택 순으로 plan한다. 선행 output이 없으면 모든 후속 plan을 한 번에 성공시킬 수 없으므로 단계별로 진행한다.
- plan의 add/change/destroy와 replacement 이유, 리전/AZ, IAM, 월 비용 변화를 요약한다. 예상 외 destroy/replace가 있으면 원인을 해결하기 전 배포하지 않는다.
- Kustomize 렌더링 및 Kubernetes 스키마 검사, 이미지 실행과 health/API 테스트를 한다. 실제 cluster의 CRD가 준비되면 server-side dry-run으로 확인한다.
- plan 파일과 원문 로그는 민감정보를 포함할 수 있으므로 Git/공개 보고서에 첨부하지 않는다.

## 3. 승인 후 배포 순서

사용자 요청과 `infra/CLAUDE.md`에 따라 실제 apply는 사용자가 검토 후 실행하는 절차다. 기존 bootstrap이 정상 관리 중이면 재생성하지 않는다.

`bootstrap 상태 확인 → network → eks → RDS/데이터 S3/ECR → 앱 이미지 → 비밀·IAM → WAS → WEB → Ingress → 통합 검증`

데이터 S3/ECR은 네트워크와 독립적으로 준비 가능하지만 첫 실행은 문제 원인을 좁히기 위해 순서대로 확인한다. 각 단계가 정상화되기 전 다음 단계로 넘어가지 않는다. AWS 생성/변경, ECR push, DB 스키마 적용, Kubernetes 배포 모두 실제 변경이므로 배포 승인 범위에 포함한다.

## 4. 단계별 완료 기준

| 단계 | 확인 방법 | 통과 조건 |
|---|---|---|
| VPC | subnet/route/SG 및 endpoint 연결 조회 | 확정 CIDR/AZ, public/app/db 경로 일치, DB public 경로 없음 |
| EKS | cluster 조회, `kubectl get nodes`, 시스템 Pod 조회 | ACTIVE, 필요한 노드 Ready, 필수 시스템 Pod 정상 |
| WAS/WEB | rollout 상태, Service EndpointSlice, /health | Ready Pod와 Service selector/port 일치, crash loop 없음 |
| ALB → WEB | ALB target health 및 사용자 URL 요청 | target healthy, WEB 응답 성공 |
| WEB → WAS | WEB의 /api/info 및 내부 Service DNS 요청 | WAS 응답 확인, nginx proxy 경로 일치 |
| WAS → RDS | WAS의 앱 계정으로 TLS 연결 및 SELECT 1 | PostgreSQL 연결 성공. 공개 GET에서 DDL/INSERT 하지 않음 |
| WAS → S3 | 실제 WAS ServiceAccount로 전용 테스트 prefix Put/Get | round trip 일치, 허용 밖 bucket/prefix 접근 거부. 테스트 객체 정리는 승인 범위 내 수행 |
| 복구 | 승인된 환경에서 Pod 하나 재시작 | Deployment가 Ready로 복구, 연결 재검증 성공. 단일 replica면 잠시 중단 허용 여부 사전 합의 |
| 멱등성 | 각 Terraform 스택 `plan -detailed-exitcode` | 0(no changes). 2는 변경 검토, 1은 오류 해결 |

DB migration은 `001_member.sql → 002_member_archive.sql` 의존 순서를 따르되, 기존 DB에는 테이블 상태를 확인한 migration으로 적용한다. Compose의 볼륨 초기화/삭제 절차를 RDS에 적용하지 않는다.

## 실패 시 대응

인프라 전체 destroy를 복구 수단으로 사용하지 않는다. 앱은 검증된 이전 이미지/설정으로 되돌리고, RDS/state/data S3는 보존한다. DB 변경은 백업과 검토된 migration 복구 계획에 따른다. ALB 문제는 Service 이름·target type·SG·health 경로부터, S3 문제는 workload IAM·bucket/endpoint policy·route를 분리해 점검한다.

## 시간 추정

실습 자료 활용, 단일 개발 환경, AWS 권한·quota 확보, 앱 담당자 가용성을 가정한 작업량 추정이다.

| 작업 | 예상 |
|---|---|
| 계정/state/설계 결정 | 2~4시간 |
| network 및 eks 통합 | 6~10시간 |
| RDS/S3/ECR/IAM | 4~6시간 |
| 예제 WEB/WAS PostgreSQL·S3 수정 및 배포 준비 | 6~10시간 |
| 단계별 배포·통합 검증·인수인계 | 4~8시간 |
| 합계 | 22~38 작업시간, 약 3~5 업무일 |

권한 승인 대기, 기존 state 복구, 실습 외 업무 WEB/WAS 신규 개발, quota 문제, 데이터 이관 시간은 제외한다. 앱이 이미 준비되어 있으면 단축할 수 있지만 현재 Git만으로는 그렇게 가정할 수 없다.
