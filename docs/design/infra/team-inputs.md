# 팀원에게 받을 연결 입력

상태: 입력 대기 · 2026-10-14. 사용자가 DB→Kafka 캡처 범위와 업무 토픽은 팀원에게 받을 항목으로 보류했다. 이 목록은 전달용 초안이며 메시지를 전송하거나 임의 명세를 구현하지 않았다.

현재 인프라는 도쿄·EKS 두 AZ·RDS PostgreSQL 16.15 Single-AZ다. Kafka는 broker/controller 3개, RF=3/min ISR=2, broker당 gp3 20 GiB, 초기 업무 이벤트 보관 24시간을 기준으로 코드만 준비했다. EKS/Kafka/RDS는 아직 생성하지 않았다.

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
| 토픽별 24시간 보관 예외와 추가 heartbeat/transaction 토픽 | 명시적 보관 및 ACL 준비 |
| Producer/Consumer namespace·ServiceAccount·group 이름 | TLS 인증과 토픽/group 권한 연결 |
| Consumer 이미지 digest/명령·환경변수·health·자원 요구 | 런타임 배포 준비 |
| commit/재처리/중복 처리 계약과 checkpoint 필요 여부 | 재시작·장애 시 전달·적재 검증 |
| S3에 필요한 작업 종류 | 경로가 나중에 결정되면 prefix별 Pod Identity 권한 준비 |

실제 비밀번호·토큰·개인정보 레코드는 이 문서나 공개 Git에 넣지 않는다. 계정 ID·endpoint·실제 ARN·Secret 값은 기존 비공개 입력/승인된 공급 경로로 전달한다. 지금은 사용자 요청으로 S3 내부 경로 구조도 미정이므로 이 문서에서 경로를 새로 정하지 않는다.

사용자 합의: S3 내부 경로는 데이터·앱 담당자의 구조가 완성된 뒤 받는다. 인프라 담당은 그때 서비스별 실제 prefix와 필요한 action에 맞춰 IAM/Pod Identity를 연결한다. 경로 이름·데이터 형식·파티션을 인프라에서 먼저 확정하거나 빈 객체로 생성하지 않는다.

## 이번에 보류된 항목

RDS 크기·저장량은 db.t4g.small·초기 20GiB / 자동 증가 최대 100GiB로 확정됐다. S3 내부 경로, WEB/WAS 앱 준비, 도메인·HTTPS, DB→Kafka 캡처 범위와 업무 토픽은 결정/입력 대기로 남긴다. 앱 준비를 보류했다고 CDC 업무 명세나 Consumer 구현을 인프라 담당이 대신 만들지 않는다.

명세가 도착하면 토픽/ACL·CDC 설정·Secret 참조·서비스 권한을 연결하고 정적/로컬 검증을 수행한다. 실제 생성과 통합·부하 테스트는 마지막 배포 단계에서 진행한다.
