# 작업 지시서: infra/analysis

Network 재검토 완료(2026-10-14): 실제 backend에서 단일 NAT 구성 plan을 실행했다. 21 create / 0 change / 0 destroy, 교체 없음. NAT/EIP 각각 1개와 workload AZ ap-northeast-1a를 확인했다. fmt/validate 통과, 새 plan의 Git 제외 확인, apply 미실행. 실제 배포 때 plan을 다시 생성한다.

최신 결정(2026-10-14): 사용자 요청으로 **RDS 인스턴스 크기는 나중에 결정**한다. PostgreSQL 16.15·Single-AZ는 유지하며 micro/스탠다드 비교는 참고 자료로만 보관한다. 크기를 임의로 확정하거나 배포하지 않는다.

상태: 구현·로컬 검증 완료 / 남은 사양 검토 및 종속 스택 실환경 plan 대기 · 브랜치: `infra/analysis`

후속 기록(2026-10-13): 사용자 요청으로 ECR 스택만 plan/apply했다. 저장소 2개 생성, S3 state 저장·암호화·버저닝 및 lock 해제를 확인했고 후속 plan은 변경 없음(0)이다. AWS 인증/버킷 접근은 확인됐다. 다른 스택은 미배포이며 실제 계정 ID/endpoint/state 내용은 이 기록에 포함하지 않는다.

Network 후속 기록: 사용자가 10.70.0.0/16과 6개 subnet 구성을 승인했다. 기존 VPC 대역과 겹치지 않고 도쿄 a/c AZ가 사용 가능함을 확인했다. 실제 plan은 23개 생성, 변경/삭제 없음이며 apply는 미실행이다. [배포 전 검토](../design/infra/network-plan.md) 참고.

## 목표 및 사용자 결정

추가 결정: 실제 생성 테스트는 마지막에 진행한다. EKS 1.36, m6i.large/m7i.large On-Demand, custom NodePool 8 vCPU/32GiB를 승인했고 Generator 부하에 따른 증설·축소 안내를 요청했다. compute 스택과 WEB/WAS 용량 입력을 추가했으며 [운영 가이드](../../infra/SCALING.md)를 작성했다. AWS/Kubernetes mock plan 테스트 12개 통과. 실제 AWS 생성/변경은 이번 후속 작업에서 수행하지 않았다.

기존 분석 문서를 보존하며 1차 VPC/EKS/WEB/WAS/RDS/S3 연결용 Terraform을 작성한다. 2026-10-13 사용자가 EKS Auto Mode와 고가용성을 선택했다. 기존 bootstrap은 다른 팀원 환경에서 배포된 것으로 추정되며 state/계정은 미확인이다.

## 범위

network/eks/rds/storage/ecr/apps 모듈과 스택, 비공개 입력 예제 및 운영 문서, mock 검증. 도쿄/PostgreSQL/2 AZ/NAT 2개/Multi-AZ RDS를 반영한다. 기존 bootstrap, 앱 소스, 팀원 데이터, 원격 Git을 변경하지 않는다. apply/destroy/import/state 변경은 수행하지 않는다.

## 완료 확인

- [x] 원격 main 해시가 bbe9fae와 동일함을 읽기 전용 조회로 확인
- [x] 신규 스택별 고유 backend key 및 EKS/앱 state 분리
- [x] provider 설치: backend=false, AWS 6.68.0, Kubernetes 2.38.0
- [x] bootstrap 및 신규 6개 스택 terraform validate 통과
- [x] AWS mock plan 테스트 5개 통과 (NAT/endpoint, CIDR 충돌, AZ 불일치, RDS, S3)
- [x] 최종 fmt 검사 통과, 신규 문서 링크 오류 0건, 계정 ID/키 패턴 점검 0건
- [x] bootstrap 추적 파일 변경 없음, 비공개 tfvars/backend 파일의 Git 제외 확인
- [x] AWS 인증 및 대상 state 버킷 접근 확인 (bootstrap local state 관리 위치는 미확인)
- [ ] 실환경 terraform plan 검토
- [ ] 앱 이미지/Secret/DNS 준비 및 사용자 승인 후 배포·통합 검증

실제 리소스의 존재·비용·quota·엔진 지원 조합은 mock 테스트로 확인되지 않는다. [실행 안내](../../infra/IMPLEMENTATION.md)를 따른다.

## WAS HPA 결정
사용자 승인으로 WAS HPA 2~3개, CPU 70%, 축소 안정화 300초와 Metrics Server를 구현했다. WEB은 Terraform, WAS 수는 HPA가 관리한다. mock plan 테스트 16개 통과. 실제 생성·확장·축소 검증은 마지막에 진행한다.

## 2026-10-14 후속 준비

후속 사용자 결정: PostgreSQL 16으로 변경하고 medium보다 작은 사양을 재검토한다. 도쿄 API에서 16.15 및 micro/small의 Multi-AZ gp3 지원을 확인해 버전만 Terraform에 반영했다. 월 730시간·20 GiB 기준 micro $42.02, small $79.25이며 크기는 미확정이다. 실제 생성은 보류한다.

HPA 추가로 달라진 기초 배포 안내를 수정하고 [배포 준비 현황](../../infra/READINESS.md)을 작성했다. 사용자 승인으로 RDS 시작안의 지원 조합과 비용을 읽기 전용 검토했다. 도쿄 db.t4g.medium/PostgreSQL 17/Multi-AZ/gp3 20 GiB 조합이 조회되었고 기본 월 비용은 730시간 기준 $152.98이다. [검토 상세](../design/infra/rds-sizing.md). 로컬 PostgreSQL 16과의 차이 및 정확한 버전 선택은 남아 있다. 이번 작업은 문서와 예제 주석만 변경했고 fmt/diff 검사를 통과했다. 리소스 생성·state 변경은 수행하지 않았다.

## 단일 AZ 변경 (2026-10-14)
사용자 승인으로 워커·앱·RDS를 ap-northeast-1a로 모으고 NAT를 1개로 줄였다. AWS 제약으로 EKS/ALB/RDS subnet group의 두 AZ subnet은 유지한다. RDS Single-AZ, Pod zone spread min_domains=1로 변경했다. WEB 2개·WAS HPA 2~3개는 유지한다. DB 크기는 미정이며 micro Single-AZ + 20 GiB는 월 730시간 기준 21.01 USD다. mock plan 16개 통과, 실제 생성 없음. 이전 network plan은 사용하지 않고 최종 배포 때 다시 생성한다.

## 최종 사용자 정정
전체 단일 AZ는 오해였으며 RDS만 Single-AZ로 유지한다. VPC·EKS는 두 AZ, NAT 2개, 앱/Kafka 두 AZ 분산으로 복원했다. infra/integration-rds-single-az에서 local-ready 통합을 이어간다. DB 크기는 보류, 실제 생성은 마지막이다.
