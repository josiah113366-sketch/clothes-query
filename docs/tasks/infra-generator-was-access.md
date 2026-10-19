# 작업 지시서: infra/generator-was-access

> 상태: 실제 권한 연결 완료 / 검토 대기 · 브랜치: `infra/generator-was-access` · 다음 작업: 동료 본인 kubectl 검증 및 앱 명세에 따른 후속 연결

## 목표와 사용자 결정

2026-10-19 사용자가 제공한 IAM 사용자가 Fargate 제네레이터와 EKS WAS를 모두 배포한다고 가정하고 접근을 열어달라고 요청했다. 동료는 현재 사용자와 같은 공인 IP 네트워크를 사용한다고 확인했다. 실제 ARN/IP·계정은 공개 Git에 넣지 않는다.

이후 사용자가 권한이 작다고 지적하며 “좀 크게 줘 그냥”이라고 요청했다. WAS namespace 배포에 더해 클러스터 전체의 노드·Pod·로그·업무 자원 상태 조회를 추가한다. 다른 namespace Secret·exec·node proxy·클러스터 변경 권한은 이번 확장에 포함하지 않는다.

## 먼저 읽은 것과 사전 확인

- 루트/infra `CLAUDE.md`, EKS/apps/ECR/network 스택과 공식 EKS access entry·RBAC 안내.
- 최신 `origin/main` (`b97f113`)에서 작업 브랜치를 만들었다. 보류한 비용 알림과 Airflow 문서는 별도 브랜치에 보존했다.
- 제공 사용자 존재·공통 지원 계정 그룹 정책·도쿄 ECR/ECS를 읽기 전용으로 확인했다. ECS/ECR/IAM 등 AWS 서비스 권한은 이미 광범위하게 허용되며 EKS access entry는 없었다. 공통 정책은 변경하지 않는다.
- `clothes-query` namespace와 apps state는 없었다. 현재 EKS public API의 1개 허용 범위는 그대로 사용한다.

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- 사용자의 “둘 다 한다 가정하에 열어주자”는 실제 배포 접근 연결 요청에 따라 새 team-access 스택만 plan 검증 후 적용한다. 기존 인프라/공통 IAM/ALB/비용 알림은 적용 대상이 아니다.
- PR 승인·머지는 팀원이 한다. 공개 Git에 실제 사용자 ARN·계정·endpoint를 넣지 않는다.
- 후속 권한 확대 요청에 따라 같은 team-access 스택의 읽기 전용 ClusterRole/Binding 2개도 실제 적용한다.

## 만드는 것

namespace·EKS access entry·namespace RoleBinding 3개. EKS 전체 관리자 대신 애플리케이션 namespace의 edit 권한을 연결한다. 기존 공통 IAM의 광범위한 AWS 권한을 제한했다고 주장하지 않는다. ALB는 서비스 준비 후, 업무 DB 계정/SG는 실제 명세 후 연결한다.

## 완료 확인

- [x] 전체 infra fmt·새 스택 validate·mock plan/잘못된 입력4개 통과.
- [x] 실제 plan 신규3개·수정/삭제/교체0개, 기존 IP 허용 유지.
- [x] 허용된 스택만 실제 적용 후 no-change plan 확인.
- [x] 그룹 impersonation 검사8개: WAS 배포/로그/Secret 생성 허용3개, Kafka Secret/Airflow 배포/노드 삭제/ClusterRoleBinding 및 RoleBinding 생성 거부5개.
- [x] 공개 파일14개 민감정보·상대 링크4개·diff 확인, 동료용 접속 명령 준비.

## 작업 결과

- **한 줄 요약:** 제공 동료 IAM 신원을 기존 도쿄 EKS의 WAS namespace 배포 그룹에 실제 연결했다.
- **무엇을 만들었나:** 독립 team-access 스택·모듈·mock4개, `clothes-query` namespace와 namespace edit RoleBinding, STANDARD EKS access entry를 생성했다. 실제 ARN·계정·backend·plan은 Git 제외 경로에만 저장했다.
- **왜 이렇게 했나:** 공통 그룹에서 ECS/ECR 배포 권한이 이미 있어 중복 IAM 정책을 추가하지 않고 Kubernetes 배포 경로만 연결했다. 공통 IAM 정책을 좁혔다고 주장하지 않는다.
- **확인한 결과:** 생성3·수정0·삭제0 적용, 사후 plan 변경 없음. 기존 EKS public IP 허용1개를 그대로 유지했다. RBAC 검사8개 통과, namespace 내부 Pod0개로 실제 업무 앱은 아직 미배포다. ALB/추가 노드/Fargate runtime·RDS 접속 규칙·보류한 비용 알림은 만들거나 변경하지 않았다.
- **알려진 한계·남은 일:** 동료 본인 AWS 인증/kubectl 및 실제 WAS/Fargate 배포는 담당자 검증으로 남는다. 내부 ALB·업무 DB 계정/SG·Task 실행 역할·이미지는 실제 명세 후 연결한다. 추후 apps Terraform 사용 전 namespace 소유권 재사용 처리가 필요하다. 동료 IAM의 광범위한 AWS 서비스 권한은 공통 지원 그룹에서 이미 부여된 상태이며 이번 RBAC의 제한과 별개다.

## 후속: 운영 조회 확대

운영 상태용 ClusterRole과 ClusterRoleBinding을 추가해 현재 스택의 총 관리 자원은 5개다. WAS namespace의 edit 권한을 유지하고 전체 노드·namespace·Pod/로그·Deployment/Job·Service/Ingress·스토리지·HPA·Kafka/NodePool 상태를 get/list/watch로 조회한다. 지표 조회 권한은 지표 수집기 설치를 의미하지 않는다.

새 mock 검사 포함5개·validate·fmt 통과. 확장 plan 신규2개·수정/삭제0개 적용 후 실제 RBAC16개(허용8/거부8) 및 no-change plan을 통과했다. 동료 본인 로그인 검증은 남는다. 첫 실측 검사에서 kubectl의 슬래시 리소스 표기가 하위 리소스를 구분하지 않아, 명시적 `--subresource` 옵션으로 검사 방식을 수정했다. 권한 정책 자체를 넓혀서 검사를 통과시키지는 않았다.
