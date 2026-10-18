# AWS 시험 데이터 경로 준비

상태: 로컬 실행 검증 완료·AWS 적용 계획 준비 / AWS 시험 경로 미적용 · 2026-10-18.

사용자가 업무 계약 확정 전 시험 연결을 먼저 진행하기로 했다. 범위는 숫자 id/value만 사용하는 `RDS → Debezium → Kafka → S3`이며, 제네레이터·Airflow·분석 작업·업무 테이블은 포함하지 않는다. 실제 데이터 계약을 대신하지 않는다.

## 위치와 고정 시험 계약

| 대상 | 시험용 이름/위치 |
|---|---|
| DB | 기존 clothes DB 안의 infra_smoke.events |
| DB 역할 | infra_smoke_writer / infra_smoke_cdc |
| publication / slot | infra_smoke_publication / infra_smoke_slot |
| Kafka 토픽 | infra-smoke.infra_smoke.events, partition 1, RF1, 72시간 |
| Connect | kafka namespace, infra-smoke-connect 1개 |
| Connector | infra-smoke-postgres / infra-smoke-s3 |
| S3 | 기존 레이크의 infra-smoke/ 아래만 |

기존 `infra-smoke` 메시지 시험 토픽·클라이언트는 유지한다. Kafka의 기존 이름·복제 수·20GiB PVC·72시간 설정을 바꾸지 않는다. 임의 업무 테이블과 `bronze/`, `gold_b/`, `ground_truth/`를 수집하거나 저장하지 않는다.

## AWS 적용 순서와 영향

1. 최신 main·계정·state·실제 보안 그룹 부착 상태를 확인한다. RDS overlay는 EKS SG에서 PostgreSQL 접속을 허용하며 특정 Pod만 격리하는 규칙은 아니다. 이 접근 범위와 적용 시점을 검토한다.
2. 기존 비공개 RDS 입력 뒤에 `rds-cdc.tfvars.example`을 병합해 plan한다. 시험 제안은 slot 한도 5개/sender 10개/WAL 보존 예산 256MiB다. 2026-10-18 AWS postgres16 메타데이터에서 slot/sender의 최소 허용값 5를 확인했으며, 시험에서 실제 생성할 slot은 1개다. **논리 복제 정적 설정을 위해 별도 RDS 재부팅** 및 적용 확인이 필요하다. 업무 CDC 기본값으로 채택하지 않는다. WAL 값은 전체 WAL의 실시간 디스크 상한이나 유실 방지 보장이 아니다.
3. 기존 ECR stack에서 `enable_connect_repository=true`를 plan한다. 기존 CDC Dockerfile로 base를 빌드하고 `../local-smoke/s3/Dockerfile`에 BASE_IMAGE를 주어 두 플러그인이 들어간 이미지를 빌드·스캔·push한다. 실제 ECR digest는 무시되는 runtime.local.yaml에만 입력한다. 기존 WEB/WAS repository를 재생성하지 않는다.
4. network의 `additional_s3_endpoint_actions`에 AbortMultipartUpload만 합치고, workload-access의 기존 bindings에 예시의 infra-smoke-sink를 추가해 각각 plan한다. 다른 binding/action을 덮어쓰지 않는다. AWS 역할은 해당 S3 prefix에만 접근한다. node role에 S3 권한을 주거나 AWS 키를 이미지에 넣지 않는다.
5. 관리용 임시 DB client에서 RDS CA/hostname을 검증해 `prepare.sql`을 실행한다. master 자격증명은 초기화에만 사용하고 Connect에 전달하지 않는다. DB CONNECT 권한이 기본 PUBLIC에서 제거돼 있다면 두 시험 역할에 현재 DB CONNECT를 별도로 부여한다. 비밀번호는 새 난수로 생성해 프로세스 환경으로만 공급하고 SQL/에러 로그 원문에 노출하지 않는다. 같은 이름이 있으면 중단하여 소유권을 확인한다.
6. Kafka namespace에 시험 Secret 두 개를 별도로 준비한다. infra-smoke-database 키는 hostname/database/username/password이고 username은 infra_smoke_cdc다. infra-smoke-rds-ca 키는 bundle.pem이다. Secret 값·실제 endpoint·계정 ID는 Git/Helm values에 넣지 않는다.
7. 기존 single-node + measurement values 뒤에 runtime 예시를 병합하고, 비공개 복사본에서만 Connect enabled와 image digest를 입력한다. 전체 Helm diff에서 기존 Topic/User/PVC 삭제가 없는지 확인한 뒤 **동일 cq-kafka release**를 upgrade한다. Pod Identity 연결 대상 SA가 `infra-smoke-connect-connect`인지 실제 생성 리소스로 확인한다. Connect Ready와 두 플러그인 발견을 확인한다.
8. `connectors.yaml.example`을 등록한다. Source와 Sink task가 모두 RUNNING인지 확인한다. Kafka와 RDS는 mTLS 및 verify-full을 유지하며, 로컬 fixture의 store.url·더미 AWS 키·DB sslmode=disable을 복사하지 않는다.

새 RDS/새 Kafka/새 NAT를 추가하는 구성이 아니다. Connect request 250m/1Gi, limit 1CPU/1Gi와 이미지 저장·S3 요청/저장 비용이 추가된다. 기존 워커에 들어갈 수 있는지는 live allocatable/requests로 확인한다. Auto Mode가 노드를 추가하면 추가 노드 비용이 발생하므로 이미지 다운로드 중 Pending 상태를 보고 상한을 무작정 올리지 않는다.

## 2026-10-18 준비 검증 결과

- 로컬 PostgreSQL → mTLS Kafka → 실제 S3 Sink 플러그인 → Moto S3 저장 통과. 1000행 burst 포함 최종 JSON 1007개/1007건. snapshot·추가·수정·삭제 및 Connect 중단 중 변경의 재시작 후 저장 확인. 로컬 broker 컨테이너 재생성 후 메시지/source offset 보존도 확인.
- Helm/Strimzi CRD 및 trial Connector 예시 검사 통과. Sink consume ACL의 미정 토픽/그룹 누락/wildcard 거부 포함 총 28개 잘못된 입력 검사. Terraform mock 48개 통과, 관련 네 root validate 통과.
- 실제 AWS plan: RDS parameter group 생성 1·DB parameter group 연결 변경 1·EKS SG 접속 규칙 생성 1, network S3 endpoint 정책 변경 1, Connect ECR 생성 1. 확인된 plan에 삭제/교체 없음. RDS 인스턴스 변경 필드는 parameter_group_name만이다.
- workload-access의 실제 plan은 **아직 적용하지 않은 network state에 AbortMultipartUpload가 없어 의도한 사전조건으로 거부**됐다. network 적용 후 다시 plan해야 하며, 이 역할의 실제 plan/apply 성공을 주장하지 않는다.
- 로컬 데이터 파일 읽기는 8개 병렬 요청으로 개선했고 동일 1006개 초기 파일을 읽는 별도 probe도 통과했다. Moto 결과는 AWS IAM·RDS TLS·Pod Identity 검증이 아니다. 적용·DB 재부팅·레지스트리 push·실제 시험 SQL 실행은 하지 않았다.

## 완료 확인

1. writer로 (1,10) 삽입 후 같은 id/value가 Kafka와 infra-smoke/ JSON에 나타나는지 확인.
2. (1,11) 수정 및 삭제 이벤트 저장 확인. JSON은 변경 기록이며 S3 현재값 upsert가 아님.
3. Connect 중단 중 새 숫자 행을 추가하고 재시작 후 저장 확인. 중복 전달은 허용하고 누락을 검사.
4. allowlist 밖 테이블 미수집, 시험 prefix 쓰기 성공, 다른 prefix/ground_truth 읽기·쓰기 거부 확인. Moto 결과를 이 권한 검증으로 대신하지 않음.
5. 노드 수·메모리·consumer lag·WAL/slot·디스크를 확인하고 짧은 시험 결과를 남김. 장기 처리량/72시간 보존 시험은 별도.

## 종료

자동 Helm uninstall/기존 release rollback이나 RDS logical_replication=null을 정리 수단으로 사용하지 않는다. Source를 먼저 멈추고 task 정지·slot inactive를 확인한다. 이후 시험 slot/publication/schema/계정/Secret/Connector/토픽/S3 객체·멀티파트 업로드만 소유권 확인 후 정리한다. slot만 남겨 WAL을 쌓아두지 않는다. DB 전역 설정과 재부팅은 별도 검토하고, 시험 흔적 정리 후 기존 broker/PVC와 다른 서비스 권한이 유지되는지 확인한다.

PR 승인과 머지는 팀원이 수행한다. Terraform apply는 [infra/CLAUDE.md](../../../CLAUDE.md)의 담당자 실행 규칙을 따른다.
