# 누락 구성과 결정 목록

상태: 제안 / 미정 · 신규 코드는 필요하지만 신규 AWS 리소스 필요 여부는 아직 미정

| 우선순위 | 필요한 작업 | 완료 조건 |
|---|---|---|
| P0 | 기존 AWS/state 인벤토리 | 대상 계정/profile, 리전, 소유 state, bootstrap 기배포 여부를 비공개로 확인 |
| P0 | 최신 main 및 팀 작업 확인 | network/eks/RDS/WEB/WAS 담당자와 중복 작업 없음 |
| P0 | DB·앱 계약 | PostgreSQL 유지, 예제 앱 사용 여부, 실제 API·포트·health 경로와 앱 담당자 결정 |
| P0 | 네트워크 설계 | 충돌 없는 CIDR, AZ, subnet, NAT/endpoint, 관리자 접근 확정 |
| P1 | network 모듈/스택 | VPC/route/subnet/SG/endpoint와 outputs, 고유 backend key |
| P1 | eks 모듈/스택 | 노드 방식, IAM, access entry, add-on, 노드 용량 상한 |
| P1 | RDS 구성 | PostgreSQL 버전/사양/백업/보호, subnet group, 5432 SG, 앱 DB 계정 |
| P1 | 데이터 S3·ECR 구성 | 암호화/공개 차단/삭제 정책/보존 및 이미지 빌드 경로 |
| P1 | WEB/WAS 소스와 이미지 | 실제 동작 앱, PostgreSQL 드라이버, S3 접근 구현, 재현 가능한 이미지 |
| P1 | Kubernetes 리소스 | Namespace, ServiceAccount, Deployment/Service, Ingress, ConfigMap/Secret 공급 |
| P1 | workload IAM 및 검증 | S3 prefix 최소 권한, 자격증명 전달·회전, 통합 검증 |
| 후속 | Kafka/CDC/Generator/AI/CI/CD | 1차 연결 검증 이후 별도 작업 지시서 |

## 배포 전 확인받을 사항

1. 대상 AWS 계정/profile과 기존 리소스·state의 관리자가 누구인지. 비밀키나 state 내용을 공개 문서/대화에 붙이지 않는다.
2. 현재 도쿄/PostgreSQL 설계를 유지할지. 기존 AWS가 다른 리전이면 재배치보다 보존 계획을 우선 검토한다.
3. EKS Auto Mode와 Managed Node Group 중 무엇을 사용할지, 월 예산 및 노드 상한.
4. CIDR/AZ, NAT 1개와 AZ별 구성의 가용성·비용 절충, DB Single-AZ/Multi-AZ 및 백업 복구 목표.
5. WEB/WAS가 다른 저장소에 있는지, 없으면 실습 앱을 PostgreSQL/S3 검증용으로 수정해 쓸지, 담당자와 API 계약.
6. 공개 ALB 범위, 도메인/TLS, EKS 관리 경로, 앱별 S3 prefix 및 DB 권한.
7. 데이터 S3 기존 버킷 재사용 여부, 보존 기간/암호화 키/삭제 보호, 비밀 공급 도구.
8. 구현 후 검토된 plan 기준의 배포 승인. backend 변경/import/state move는 작업별 별도 승인.

이는 지금 즉시 모두 답해야 하는 질문이 아니라 구현·배포의 결정 목록이다. 미정 항목을 코드 기본값으로 굳히지 않았다.
