# 통합 데이터 경로의 실측 전 준비

상태: 코드 준비·로컬 검증 완료 / 실제 값·실배포·실측 미완료 · 2026-10-14

## 범위와 현재 결과

목표 경로는 `운영 DB → CDC → Kafka → Consumer → S3 Bronze → 정제 → Silver/Gold → 조회·관제`다. 사용자의 요청에 따라 실측 전에도 확정할 수 있는 공통 인프라 연결을 준비했다. 제네레이터·데이터 처리·AI 코드는 구현하지 않는다.

| 구간 | 이번 준비 | 아직 필요한 것 |
|---|---|---|
| RDS → CDC | 선택적 parameter group·engine-major family 연결·slot/sender/WAL 입력 검증 | DB 사양·예산, 전용 계정, publication/slot·캡처 allowlist, 재시작·failover 검증 |
| 데이터 서비스 → S3 | namespace/ServiceAccount별 Pod Identity·prefix/action 분리 모듈과 별도 stack | 서비스별 실제 namespace/SA·경로·작업 목록, SDK 호환성·권한 검증 |
| S3 통신 경로 | 기본 endpoint 권한 유지, 명시적 optional action과 workload 요청의 일치 검증 | 필요한 optional action 결정 후 network state output 반영 |
| Kafka/Connect | EKS 자체 운영 결정, Strimzi Helm·영구 저장소·TLS/ACL·Secret 참조, Connect 이미지 빌드와 로컬 CDC/재시작 전달 검증, 선택적 ECR | 실제 업무 토픽/용량/보존·레지스트리 push/digest·Secret 공급·RDS/EKS 실행 검증 |
| Kafka/Connect 관측 | 선택적 JMX/consumer lag 노출·scrape 예시, 로컬 HTTP 지표 확인 | 실제 수집 서버·RBAC·EKS discovery·RDS/노드/PVC 지표·경보/알림 |
| Consumer | 입력/출력·관리 경계·S3 권한 입력 준비 | 서비스 실행 코드·이미지·배포 설정 |
| 정제·조회·관제 | 서비스별 데이터 접근 계약을 수용할 권한 입력 구조 | 실행 방식·입출력/checkpoint·조회 API/SQL 경로·이미지·자원 요구 |

기본 설정은 RDS `logical_replication = null`, 데이터 역할 `bindings = {}`다. CDC와 새 서비스 접근 권한은 자동 활성화되지 않는다. mock 검증을 데이터 경로 실행 성공으로 표시하지 않는다.

Kafka/Connect도 기본 비활성이며 [Kafka runtime 안내](../../../infra/platform/kafka/README.md)에 설치 순서·2 AZ quorum 한계·자원 예산·팀원 경계를 정리했다. 플러그인의 PostgreSQL 호환 범위는 실제 RDS 버전과 별도 확인한다. 이 결정은 MSK 도입이나 기존 2 AZ 네트워크/노드 상한 변경을 포함하지 않는다.

[후속 결과](../../tasks/infra-kafka-followups.md)는 선택적 Connect 저장소, 일회성 로컬 DB→Kafka 전달/재시작, 선택적 지표 노출을 포함한다. 로컬 연결 검증 결과와 AWS/EKS 완료 기준을 구분한다.

[추가 검증](../../tasks/infra-kafka-validation.md)은 로컬 TLS/ACL·Kafka 재생성 후 메시지/Connect offset 보존·자동 검사 코드 연결을 포함한다. [이미지 검사](connect-image-security-2026-10-14.md)는 Critical 1/High 73 등 미조치 결과가 있으며 배포 허용을 뜻하지 않는다. 실제 Secret 공급·EKS/RDS/스토리지/장애·수집 서버·알림 검증은 남아 있다.

## RDS CDC 활성화 조건

[RDS stack](../../../infra/stacks/rds/README.md)의 `logical_replication`에 세 값을 명시해야 custom parameter group을 만든다.

| 입력 | 정할 근거 | 현재 상태 |
|---|---|---|
| `max_replication_slots` | DB별 활성 커넥터·유지/복구용 slot 수. 토픽 수와 같은 값으로 가정하지 않음 | 미정 |
| `max_wal_senders` | 동시에 사용하는 복제 연결 및 다른 복제/운영 여유 | 미정 |
| `max_slot_wal_keep_size_mb` | DB의 WAL 발생량·허용 중단/재처리 시간·가용 스토리지에 맞는 유한 예산 | 미정 |

RDS 논리 복제는 파라미터·권한이 필요하고 정적 설정 적용에는 재시작이 필요하다. 이 코드는 parameter group과 DB 연결을 준비하며 재시작이나 DB 계정·publication/slot을 생성하지 않는다. `apply_immediately=false`를 유지하고 설정은 pending-reboot로 준비한다. [AWS 논리 복제 안내](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/PostgreSQL.Concepts.General.FeatureSupport.LogicalReplication.html)

family는 명시한 PostgreSQL major에서 계산한다. 이번 WAL 예산 옵션은 PostgreSQL 13 이상을 요구하지만 RDS의 실제 버전/family·각 파라미터 허용 범위는 배포 PC에서 확인해야 한다. 테스트의 버전·수치는 배포 권장값이 아니다. `max_connections`는 임의로 덮어쓰지 않으며 앱/CDC 연결 예산과 함께 배포 전에 검토한다.

유한 WAL 보존 설정은 엄격한 실시간 디스크 상한이 아니다. 보존 예산을 넘으면 slot을 사용할 수 없게 되어 재초기화가 필요할 수 있다. WAL/slot 지연과 저장 공간을 함께 관측한다. [PostgreSQL 복제 설정](https://www.postgresql.org/docs/current/runtime-config-replication.html)

한 번 배포한 CDC 설정을 null로 바꾸는 것은 검증된 해제 절차가 아니다. 실제 slot·커넥터·parameter group 연결과 재시작/복구 계획을 확인한 뒤 별도로 변경한다. master 계정을 커넥터에 자동 전달하지 않는다. 개인정보 컬럼/`member_archive`를 포함한 전체 테이블 캡처를 기본값으로 삼지 않는다.

## 팀원과 맞출 연결 계약

| 서비스/담당 | 인프라에 제공할 입력 | 인프라가 연결할 것 |
|---|---|---|
| DB/CDC | 캡처 테이블·컬럼 allowlist, snapshot·slot/publication 소유자, 필요한 DB 권한·Secret 참조, 플러그인/이미지 | RDS 설정·네트워크·Secret 공급 경계 |
| Kafka | 업무 토픽·키, 처리량·메시지 크기·보존·partition 요구, 클라이언트 namespace·group | 결정된 EKS/Strimzi·내부 TLS·영구 저장소·명시적 ACL |
| Connect | 호환 버전·플러그인 이미지, worker/내부 토픽 요구, 커넥터 등록·Secret 회전 담당 | 런타임 배포·관리 API 접근·자원/설정 전달 |
| Consumer | 이미지/명령·환경변수·Secret 참조, 종료/재처리·health, Bronze/checkpoint 경로, 필요한 S3 action | 실행 ServiceAccount·S3 역할·자원/로그 |
| 정제 | 실행 방식·이미지/패키지·driver/executor 또는 task 요구, 입력/출력/checkpoint 및 임시 경로 | 실행 권한·S3 역할·자원 한도 |
| 대시보드/관제 | 파일/SQL/API 조회 방식, 대상 테이블/경로, 읽기 범위·인증·실행 위치 | 선택한 조회 경로·서비스 권한/접속 |

Bronze writer·Silver/Gold reader 등의 명칭은 계약 예시다. 실제 역할을 생성하려면 [workload-access 입력](../../../infra/stacks/workload-access/terraform.tfvars.example)에 서비스별 정보를 명시한다. Namespace/ServiceAccount는 실행 환경 담당자가 관리하고 이 stack은 AWS 역할/association만 관리한다. 기존 WAS association과 중복 관리하지 않는다.

workload-access는 network의 `s3_endpoint_actions`도 읽는다. 기본 endpoint 정책에 없는 action은 역할에만 추가할 수 없으며, network의 `additional_s3_endpoint_actions`에 먼저 명시해야 한다. 양쪽을 검토해 latest network output을 반영한 뒤 workload plan을 실행한다. 기존 기본 action·WAS 권한은 자동으로 넓히지 않는다. endpoint 정책은 IAM/bucket 정책을 대체하지 않는다. [AWS gateway endpoint 안내](https://docs.aws.amazon.com/vpc/latest/privatelink/vpc-endpoints-s3.html)

## 실측 전·후에 정할 항목

**실측 없이 준비:** 코드 구조, state 경계, 선택적 CDC 설정, 명시적 서비스/prefix/action 권한, mock·정적 검증, 입력/출력 계약, 배포 및 복구 검증 기준.

**팀의 설계 결정 필요:** 정제·오케스트레이션 운영 방식, 서비스 소유자, 데이터 형식/스키마·보존·PII 범위, 허용 중단·유실·복구 목표, Secret 공급 방식, 조회 경로. Kafka는 EKS 자체 운영으로 결정했고 실제 배포 입력은 남아 있다. 실측 대기가 이 결정을 대신하지 않는다.

**실측으로 조정:** 처리량에 따른 broker/partition·스토리지 예산, Consumer 및 정제 동시성, CPU/메모리·노드 한도, DB 연결/IO/WAL 여유, 경보 임계값. 현재 8 vCPU/32 GiB를 전체 플랫폼의 충분한 용량으로 보장하지 않는다.

## 배포 환경에서 확인할 완료 기준

1. 승인된 RDS 설정의 적용 상태·DB 버전·복제 계정과 캡처 allowlist를 확인한다.
2. 검증용 DB 변경 한 건이 선택한 CDC/Kafka 경로로 전달되는지 데이터 담당자와 확인한다.
3. Consumer의 지정 Bronze prefix 적재와 재시작 후 처리 계약을 확인한다. S3 역할의 허용 작업·다른 prefix 거부도 확인한다.
4. DB WAL/slot 지연, Kafka consumer lag, Bronze 적재 지연 및 처리 오류를 관측할 수 있는지 확인한다. 지표 정의·노출은 해당 서비스 담당자와 합의한다.
5. 정제/조회는 담당자의 최소 작업과 필요한 권한을 확인한 뒤 연결한다. 인프라 연결 검증과 데이터 결과 정합성 검증을 구분한다.

이번 PC에서는 실제 backend·DB·클러스터·AWS 변경, 데이터 삭제, 자격증명 공급을 수행하지 않는다. 코드와 로컬 검증 결과만 준비한다.
