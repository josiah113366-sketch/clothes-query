# Agent 개발 접근·이미지 준비

상태: 완료 (실제 적용·PR #49 검토 대기, 동료 접속 확인 후속)

## 요청과 범위

동료 답변 중 확정 가능한 agent namespace 개발 접근·판정/조사 ECR·Airflow API 인증 안내를 준비한다. 기존 관리 권한은 회수하지 않는다. 표 DDL·조사 쓰기·대시보드 실행 신원·Bedrock 모델은 합의 후 연결한다. AWS 변경은 별도 state에 추가만 하고 기존 업무 데이터·DAG는 실행하지 않는다.

## 완료 확인

- Terraform fmt/validate와 저장 계획에서 신규 저장소 2개·IAM 역할/정책·EKS entry만 생성되는지 확인한다.
- namespace Role/RoleBinding server dry-run 후 적용한다.
- 개발자 group impersonation으로 agent Job 생성·로그 조회 허용, Secret/다른 namespace/RBAC 변경 거부를 확인한다. 동료 IAM 세션은 동료가 별도로 확인한다. 업무 Pod는 생성하지 않는다.
- 저장소 설정·역할 신뢰·EKS group·후속 무변경 계획을 확인한다. 실제 동료 로그인·Docker build/push는 별도 확인한다.

## 작업 결과

2026-10-21 최신 origin/main에서 별도 브랜치를 만들고 신규 Terraform 스택·모듈·namespace Role/RoleBinding·이미지/인증 안내를 추가했다. fmt/validate·격리 mock 1건 통과 후 신규 AWS 리소스 5개(ECR 2, IAM 역할/정책, EKS access entry)만 생성되는 저장 계획을 적용했다. Kubernetes server dry-run 후 namespace RBAC 2개를 적용했다. 기존 관리자·EKS 설정·업무 데이터는 보존했다.

역할 신뢰는 요청한 개발자 1명만이며 access entry는 개발 group만 연결하고 EKS 관리 정책은 연결하지 않았다. group impersonation 검사 10건에서 Pod/Job/로그는 허용되고 Secret/RBAC/ServiceAccount 수정·다른 namespace·exec·node 조회는 거부됐다. 실제 동료 IAM 세션의 접속은 아직 확인하지 않았다. 후속 Terraform plan은 변경 없음이다.

ECR 두 저장소는 immutable tag·scan-on-push를 확인했다. Docker를 시작하거나 이미지를 빌드/push하지 않았고 업무 Pod·DAG도 실행하지 않았다. 공개 코드에는 계정·실제 ARN·접속 값·Secret을 넣지 않았다. 비공개 입력과 결과는 gitignored 경로에 보관한다. 전달문 `.cache/agent-development-handoff.md`, 적용 결과 `.cache/agent-development-summary.json`을 남겼다.

Bedrock 도쿄 목록·계정 availability만 읽었다. Nova Lite 직접 호출 후보를 확인했으며 유료 추론·권한 추가는 하지 않았다. 후속 답변으로 조사 저장 위치는 Glue DB agent / S3 agent/<테이블>/로 정해졌고 데이터 역할 변경은 후속 브랜치에서 처리한다. 표 DDL·대시보드 실행 신원·실제 판정 이미지/5분 성능은 팀원 입력 대기다.

게시 정리: 최신 main을 반영하고 root 14개·mock suite 12개/plan 56건의 격리 전체 검사를 통과했다. 이후 Dockerfile #46에 맞춰 문서의 build context를 agent/detect로 고쳤다. 사용자 요청으로 브랜치를 push하고 [PR #49](https://github.com/josiah113366-sketch/clothes-query/pull/49)를 생성했다. 승인·머지는 팀원이 진행한다. 추가 AWS 변경은 수행하지 않았다.
