# EKS Kafka·Connect 배포 준비

상태: 완료 (로컬 준비 범위, 실배포 미수행)

## 결정과 범위

- 사용자 결정: Kafka는 기존 계획대로 EKS에서 자체 운영한다.
- 실행 순서: 공식 Strimzi 버전 확인 → 운영자/스토리지 준비 → Kafka·Connect Helm 구성 → 오프라인 검증 → 로컬 커밋.
- Terraform 기반 network/eks/compute와 분리된 Helm release로 관리한다. 기존 Terraform 리소스의 소유권을 옮기지 않는다.
- MSK, Generator, Consumer 코드, DB 테이블·publication·slot 생성, 실제 배포는 범위 밖이다.
- 저장 용량·보존 기간·업무 토픽·이미지 digest는 배포 입력이다. 미정 값을 가정해 활성화하지 않는다.

## 완료 확인

- [x] 운영자 버전·Kafka 버전·Debezium 플러그인 출처 및 checksum 고정
- [x] Auto Mode gp3 암호화·Retain·지연 바인딩, Kafka PVC 보존
- [x] 내부 TLS 인증·명시적 ACL·Connect Secret 참조
- [x] 기본 비활성 렌더, 활성 렌더, 잘못된 입력 거부, 공식 CRD 스키마 검증
- [x] 노드 예산·2 AZ 한계·배포 순서·팀원 경계 문서화
- [x] 로컬 커밋 대상으로 정리, 원격 변경 없음

## 실제 실행한 검증

- Helm 3.19.0 lint/template, Kubernetes 1.36 조건, Strimzi 1.3.0 공식 CRD 스키마: 활성 예시 CR 9개 통과.
- 기본 비활성·Kafka만 활성·Connect 활성 확인, 잘못된 입력 12개 거부, 운영자 watch scope/이미지 digest와 StorageClass 검사 통과.
- Linux/amd64 Connect 이미지 `clothes-query-connect:3.7.0` 로컬 빌드 성공. 시작 전 Docker 엔진이 꺼져 있어 설치된 Docker Desktop을 시작했다.
- `docker run --rm --network none ... connect-plugin-path.sh list --plugin-path /opt/kafka/plugins`: `io.debezium.connector.postgresql.PostgresConnector`, 버전 `3.7.0.Final`, source plugin 발견·서비스 로더 등록 확인.
- Terraform 격리 검사: fmt, backend 없는 init/validate 10개 root, mock 7 suite/36 plan run 통과. AWS 자격증명/실제 backend/클러스터에 연결하지 않았다.
- 변경 문서의 로컬 링크 15개와 Git whitespace 검사 통과. 기존 analysis/data-path 작업 폴더는 clean 유지.

## 남은 범위

실제 토픽·키·보존·용량·SLO, RDS 버전/복제 권한과 CA/Secret 공급, Connect 레지스트리 및 이미지 digest, Consumer 이미지·배포, 실제 EKS scheduling/인증/장애/CDC/Bronze 검증, 모니터링·경보는 남아 있다. 로컬 플러그인 발견은 DB 변경 전달 성공을 의미하지 않는다. 원격 push/PR/실배포는 수행하지 않았다.
