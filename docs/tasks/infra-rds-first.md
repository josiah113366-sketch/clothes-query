# RDS 선행 배포

상태: 완료 (RDS·필수 네트워크 생성/검증 범위) · 2026-10-16 · 브랜치 infra/rds-first

사용자가 비용 절감을 위해 RDS부터 먼저 올리도록 요청했다. 기존 infra/ready와 PR #11은 보존하고, 최신 main에서 준비된 인프라 이력을 반영한 별도 로컬 브랜치에서 변경한다. 본 변경은 기존 두 AZ·EKS 운영 설계를 삭제하지 않고 RDS 선행 배포를 위한 선택 입력을 추가한다.

## 결정

- 기존 업무 S3와 ECR/state는 보존한다. VPC·DB 서브넷 두 AZ와 private PostgreSQL 16.15 db.t4g.small Single-AZ, gp3 초기 20 GiB/최대 100 GiB, 백업·삭제 보호를 유지한다.
- RDS-first 실행에서는 network enable_nat_gateways=false, rds use_eks_security_group=false, database_clients={}를 비공개 배포 입력에 명시한다. NAT/EIP·EKS·노드·앱·Kafka를 생성하지 않는다.
- 새 DB는 허용 클라이언트가 없는 상태로 준비한다. 제네레이터 실행 환경이 결정되면 같은 VPC의 해당 보안 그룹만 PostgreSQL 5432로 허용한다. 이번 작업은 EC2/ECS 생성이나 앱 수정·DDL 초기화를 포함하지 않는다.
- NAT 2개 및 EKS 연동은 모듈/스택의 기본값으로 보존한다. 배포 이후 비공개 입력을 누락하면 기본 NAT가 생성될 수 있으므로 항상 동일한 검토된 입력을 사용한다.
- RDS의 기존 EKS ingress 주소는 moved 블록으로 보존한다. 미래 EC2/ECS 클라이언트는 이름별 database_clients 입력으로 추가한다.
- RDS 기본 월 비용은 기존 확인 단가 기준 $39.26(730시간, 초기 20 GiB). Secret·추가 백업·전송·세금은 별도다.

## 순서와 완료 조건

1. 계정·기존 state/VPC/DB 및 버전 지원 확인.
2. 선택 입력 구현, fmt/validate 및 NAT 없음·DB 비공개·클라이언트 제한 mock 검증.
3. network의 새 실제 plan을 검토한다. 기존 과거 plan은 재사용하지 않는다.
4. 검토한 network plan을 실행한 뒤 실제 state 출력으로 rds plan을 생성·검토한다. 가짜 state로 종속 plan을 만들지 않는다. 이번 RDS 선행 배포는 사용자의 직접 배포 요청에 따라 수행하며 기존 일반 apply 담당 규칙을 영구 변경하지 않는다.
5. RDS apply 후 available/private/암호화/백업·Secret 상태를 확인한다. DB 접속·DDL·제네레이터 연결은 별도 단계로 기록한다.

## 사전 확인

2026-10-16 AWS 읽기 조회: 계정 guard 일치. 프로젝트 VPC와 RDS 없음. 기존 S3 backend에는 ECR·storage state만 존재하며 network/EKS/RDS state는 없다. bootstrap local state 소유권은 여전히 별도 인수인계 항목이다. 기존 state 버킷은 재생성하지 않는다.

실제 network plan: 19개 생성, 변경·삭제 없음. NAT/EIP/EKS/EC2/ALB 생성 항목 없음. PostgreSQL 16.15·db.t4g.small·gp3 최소 20 GiB·선택 AZ의 도쿄 지원을 AWS API로 재확인했다. plan과 비공개 입력은 Git 제외 파일로 저장했다.

## 실행 결과

- 검사기 단위 9개, Terraform fmt/10개 root init·validate 및 10개 suite/47개 mock plan 통과. 최초 새 route 검사에서 computed 값 의존으로 실패했으며 배포 전 확인 가능한 subnet/NAT/endpoint 검사로 수정한 뒤 전체 재검증을 통과했다.
- 사용자 RDS 선행 배포 요청에 따라 실제 network 19개 생성 완료. 기존 S3 backend의 network key에 state 저장.
- 실제 network 출력으로 RDS plan 생성: private DB·subnet group·보안 그룹 3개 생성, 변경·삭제 없음. EKS state를 참조하지 않고 DB ingress는 없음. 확정 사양·암호화·7일 백업·삭제 보호·관리형 master Secret을 plan에서 확인했다.
- network 생성 후 재plan은 변경 없음.
- RDS 생성 후 재plan도 변경 없음. network/RDS state는 각각 기존 S3 backend의 별도 key에 저장했다.
- RDS 3개 생성 완료. 실제 AWS API에서 available, PostgreSQL 16.15, db.t4g.small, Single-AZ/private, 암호화, 초기 20 GiB/최대 100 GiB, 백업 7일·삭제 보호, master Secret active를 확인했다.
- DB 보안 그룹 ingress 0개, 활성 NAT 0개, private route table 3개에서 기본 인터넷 경로 0개를 확인했다. 제네레이터 연결 시 이름별 보안 그룹을 추가해야 한다.
- 테이블 초기화·앱 전용 계정 생성·SQL 접속·제네레이터 연결은 미실행. RDS 생성 완료가 데이터 파이프라인 연결 완료를 의미하지 않는다.
- 기존 S3/ECR 및 PR #11 브랜치는 변경하지 않았다. 후속 코드는 infra/rds-first 로컬 브랜치에 보존하며 push/새 PR/머지는 수행하지 않는다.
