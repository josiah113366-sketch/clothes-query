# Kafka 후속 인프라 준비

상태: 진행 중

사용자가 승인한 순서: Connect ECR → 로컬 CDC 전달 검증 → Kafka·Connect 지표 노출.

- 기존 Kafka 준비 브랜치를 기반으로 별도 worktree/브랜치에서 작업한다.
- ECR은 선택적 Connect 저장소와 최소 push 권한 문서 출력을 추가한다. 실제 IAM identity/CI 연결은 미정으로 남긴다.
- 로컬 테스트는 일회성 DB·Kafka·Connect와 인프라 검증용 정수 데이터만 사용한다. 앱/제네레이터 코드는 수정하지 않는다.
- 지표는 Strimzi가 지원하는 노출 설정과 수집 계약을 준비한다. 수집 시스템 도입·임계값·실제 경보 전달은 별도다.
- AWS API/실제 state/원격 push/PR/이미지 업로드는 수행하지 않는다.

## 완료 확인

- [x] ECR 기본 주소 유지, 선택 활성 및 push 정책 범위 mock 검증
- [x] 로컬 CDC insert/update/delete 전달 및 재시작 후 전달 확인
- [ ] Kafka·Connect 지표 설정의 기본 비활성·활성 렌더 및 공식 CRD 검증
- [ ] 문서·실행 결과·남은 범위 기록, 단계별 로컬 커밋

## 1단계 결과

Connect 저장소는 기본 비활성이며 기존 WEB/WAS 이름과 resource key를 유지한다. 활성화 시 Connect repository만 추가한다. 최소 push 정책 JSON을 sensitive output으로 제공하되 IAM identity를 생성/연결하지 않는다. 실제 apply/login/push는 수행하지 않았다.

Terraform fmt·backend 없는 init/validate 10 root·mock 8 suite/38 plan run 통과. 그중 새 ECR 2 run은 기본 기존 주소 유지·선택적 추가·보호 설정·정책 범위를 확인했다.

## 2단계 결과

로컬 PostgreSQL 16 → Debezium 3.7.0.Final/Kafka Connect 4.3.1 → Kafka 4.3.1 연결 검사를 실행했다. 초기 snapshot, insert/update/delete의 before/after·op, Connect 중단 중 발생한 변경의 재시작 후 전달, 캡처 범위 밖 테이블 토픽 미생성을 확인했다. 전용 non-superuser replication 계정과 DirectoryConfigProvider의 임시 Secret 참조를 실제 사용했다. 실행한 project의 container/network/volume/image tag 정리도 완료했다.

검사 과정에서 로컬 로그 디렉터리 권한과 consumer 초기 group 할당 대기를 수정했다. Debezium 실제 토픽 이름의 점/밑줄을 지원하도록 KafkaTopic `resourceName` 선택 입력을 추가했다. 기존 이름은 유지하며 ACL은 실제 Kafka 토픽 이름을 참조한다. Helm/공식 CRD 검사와 잘못된 입력 14개 거부가 통과했다.

로컬 1 broker·평문·DB SSL 비활성 격리 환경의 연결 검사이며 RDS/EKS/TLS/ACL/HA/성능/S3 전달 검증은 아니다. exactly-once를 보장하지 않는다.
