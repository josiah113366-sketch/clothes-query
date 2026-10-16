# 팀원에게 받을 연결 입력

상태: 입력 대기 · 2026-10-16 갱신. 제네레이터는 팀원이 ECS Fargate로 구성하기로 결정했다. DB→Kafka 캡처 범위와 업무 토픽은 팀원에게 받을 항목이다. 이 문서는 연결 계약이며 메시지를 전송하거나 ECS 리소스를 생성하지 않았다.

현재 도쿄의 두 AZ VPC·private RDS PostgreSQL 16.15 Single-AZ·업무 S3는 생성 완료했다. NAT는 0개이며 향후 1개 공유한다. EKS Auto Mode는 t3a.large, 용량 한도 6 vCPU/24GiB로 코드만 준비했다. 최소 Kafka는 single-node 프로필의 broker/controller 1개·Connect 1개·RF 1/min ISR 1·gp3 20GiB·72시간이다. EKS/Kafka는 미배포다.

## ECS Fargate 제네레이터 담당

Fargate cluster/task definition·실행/스케줄·이미지 배포는 팀원 담당이며 이번 EKS compute 변경에서 생성하지 않는다. EKS와 ECS는 같은 VPC의 private RDS·S3를 공유할 수 있다. AWS 계정 ID·리소스 ID·접속 주소·Secret 값은 공개 문서에 적지 않고 비공개 채널로 전달한다.

| 연결 항목 | 역할과 받을 입력 |
|---|---|
| VPC·subnet·통신 경로 | 인프라가 실제 VPC/subnet·route 정보를 비공개 전달. 팀원이 Fargate subnet·public IP 여부를 확정. private 구성에서는 활성 NAT 또는 필요한 Endpoint가 있어야 이미지·Secret·로그에 접근 가능 |
| Task 보안 그룹 | 팀원이 Task ENI의 SG ID를 전달. 인프라는 RDS `database_clients`에 해당 SG만 5432로 허용하는 plan 검토. EKS 클러스터 SG와 Fargate task SG는 별개 |
| RDS 계정·schema·TLS | 제네레이터 전용 최소 권한 DB 계정·사용할 schema와 Secret 참조를 합의. master 계정은 전달하지 않음. 로컬 DB만 허용하는 현재 코드와 RDS TLS/CA 설정은 담당자가 수정·검증 |
| ECR·이미지 | 팀원이 사용할 repository·이미지 digest·빌드/배포 주체를 확정. 기존 WEB/WAS용 repository를 자동 재사용하지 않음 |
| IAM 역할 | Task Execution Role은 ECR pull·로그·태스크 주입 Secret 등 실행에 필요한 권한. Task Role은 제네레이터 코드가 사용하는 S3 등 AWS API 권한. 실행 시 코드에서 Secret을 읽으면 Task Role에도 해당 권한 필요 |
| S3 prefix | 실제 읽기/쓰기 prefix와 역할 ARN을 받아 최소 권한 정책·필요 시 버킷 정책을 검토. 같은 계정에서는 Task Role 정책으로 허용 가능하며 역할 ARN만으로 자동 권한이 생기지 않음 |
| 실행량·중단 | Task CPU/memory·동시 실행 수·실행 주기·RDS 연결 수·예상 일일 데이터량을 팀원이 전달. EKS 자동 확장과 Fargate task 확장은 별도 |

연결 검증은 이미지 pull → Task 실행 → TLS로 RDS insert → 필요한 S3 prefix 업로드 순서로 수행한다. 이어서 CDC → Kafka → S3 Sink 전달을 별도로 검증한다. 현재 Fargate SG 허용·DB 계정/DDL·IAM 연결은 수행하지 않았다.

## DB / CDC 담당

| 받을 내용 | 필요한 이유 |
|---|---|
| 캡처할 schema.table 목록과 허용/제외 컬럼 | 전체 DB 캡처를 기본값으로 쓰지 않음. member_archive·개인정보 범위는 별도 합의 |
| snapshot 수행 여부와 기준 데이터 규모 | 첫 연결 때 기존 데이터 적재·부하·검증 범위 결정 |
| 커넥터 개수와 slot/publication 이름·소유자 | 복제 슬롯 수·권한·중단/재처리 절차 준비 |
| 허용 CDC 중단 시간과 WAL 발생량 추정 | 유한 WAL 보존 예산·디스크 여유 산정 |
| DB 계정의 필요한 권한 및 Secret 참조 이름/키 | RDS master와 별도의 계정·비밀 공급 준비 |
| 커넥터 설정 관리·Secret 회전·복구 담당 | 변경·장애 시 책임 및 재검증 절차 연결 |

## Kafka / Consumer 담당

| 받을 내용 | 필요한 이유 |
|---|---|
| 실제 토픽 이름, 메시지 key와 schema | CDC가 발행하는 이름과 사전 생성 토픽·Consumer 입력 일치 |
| partition 수, 평균/피크 bytes/s·메시지 크기 | 병렬 처리·디스크·네트워크 예산 검토 |
| 토픽별 72시간 보관 예외와 추가 heartbeat/transaction 토픽 | 업무 토픽 retentionMs=259200000 명시 및 ACL 준비. Connect 내부 compact 토픽은 별도 |
| Producer/Consumer namespace·ServiceAccount·group 이름 | TLS 인증과 토픽/group 권한 연결 |
| Consumer 이미지 digest/명령·환경변수·health·자원 요구 | 런타임 배포 준비 |
| commit/재처리/중복 처리 계약과 checkpoint 필요 여부 | 재시작·장애 시 전달·적재 검증 |
| S3에 필요한 작업 종류 | 경로가 나중에 결정되면 prefix별 Pod Identity 권한 준비 |

실제 비밀번호·토큰·개인정보 레코드는 이 문서나 공개 Git에 넣지 않는다. 계정 ID·endpoint·실제 ARN·Secret 값은 기존 비공개 입력/승인된 공급 경로로 전달한다. 지금은 사용자 요청으로 S3 내부 경로 구조도 미정이므로 이 문서에서 경로를 새로 정하지 않는다.

사용자 합의: S3 내부 경로는 데이터·앱 담당자의 구조가 완성된 뒤 받는다. 인프라 담당은 그때 서비스별 실제 prefix와 필요한 action에 맞춰 IAM/Pod Identity를 연결한다. 경로 이름·데이터 형식·파티션을 인프라에서 먼저 확정하거나 빈 객체로 생성하지 않는다.

## 이번에 보류된 항목

RDS 크기·저장량은 db.t4g.small·초기 20GiB / 자동 증가 최대 100GiB로 확정됐다. S3 내부 경로, WEB/WAS 앱 준비, 도메인·HTTPS, DB→Kafka 캡처 범위와 업무 토픽은 결정/입력 대기로 남긴다. 앱 준비를 보류했다고 CDC 업무 명세나 Consumer 구현을 인프라 담당이 대신 만들지 않는다.

명세가 도착하면 토픽/ACL·CDC 설정·Secret 참조·서비스 권한을 연결하고 정적/로컬 검증을 수행한다. 실제 생성과 통합·부하 테스트는 마지막 배포 단계에서 진행한다.
