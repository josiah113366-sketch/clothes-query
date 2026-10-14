# 두 AZ 인프라·Single-AZ RDS 및 local-ready 통합

상태: 완료 (로컬 통합·검증 범위) · 브랜치 `infra/integration-rds-single-az` · 2026-10-14

사용자가 리뷰 결과에 따른 통합과 수정·재검증을 승인했다. 이어서 전체 단일 AZ 요청은 실수였으며 **RDS만 Single-AZ, VPC·EKS는 두 AZ 유지**라고 정정했다. 이 최종 지시를 우선한다. 문서 파일명은 기존 링크 보존을 위해 유지한다. 원격 push, PR, AWS 배포는 포함하지 않는다.

## 최종 통합 범위

- 기존 미커밋 변경은 `infra/analysis@088ee05`에 보존했다. 비공개 입력/state/plan은 제외했다. 이 checkpoint의 전체 단일 AZ 구성은 최종 배포 기준이 아니다.
- `origin/infra/local-ready@84080d8` 이력을 통합한다. 해당 이력은 main `f0a6059`를 포함한다. 실제 병합 충돌은 6개 파일이었고 모두 내용상 해결했다.
- network NAT 2개, EKS 두 app subnet/두 AZ, 앱과 Kafka minDomains=2를 복원했다. HPA와 노드 풀 상한은 유지한다.
- RDS는 PostgreSQL 16.15, Single-AZ, 기본 DB AZ a다. 위치는 `database_availability_zone`으로 지정하며 network AZ에 포함되는지 검사한다. 인스턴스 크기는 보류한다.
- 선택적 CDC parameter group, S3 endpoint action, workload-access, Connect ECR, CI/Helm/로컬 검증 코드를 함께 통합한다. 기본 비활성 기능은 그대로다.
- Kafka 예약 resourceName을 configs/offsets/status 모두에 대해 거부하고 회귀 테스트를 추가했다. RDS CDC 테스트는 Single-AZ 및 필수 AZ 입력에 맞췄다.
- 처음 리뷰에서 발견한 Kafka 2-AZ/단일-AZ 충돌은 사용자 정정에 따라 더 이상 적용되지 않는다. Kafka 3개 broker·RF=3·두 AZ 분산은 유지한다.

## 검증

- 검사기 unit 9개 통과.
- 최종 두 AZ 구성의 Terraform 10 roots 및 mock plan 38개 모두 통과.
- Helm lint/고정 CRD/21개 입력 거부 및 두 AZ 배치 검사 통과.
- 통합 소스의 Docker 이미지 빌드, mTLS/ACL 거부, CDC snapshot/insert/update/delete, Connect 재시작 후 전달, Kafka 재생성 후 데이터/offset 보존, 지표 검사 통과. 전용 테스트 자원 정리 완료.
- 마지막 AZ 정정은 Terraform 및 Helm 배치에만 적용했고 Docker 이미지·smoke 소스는 바뀌지 않았다. 따라서 같은 Docker 검사를 반복하지 않았다.
- simulator는 main f0a6059와 동일, bootstrap 추적 파일은 checkpoint와 동일하다. 비공개 입력/plan Git 제외 및 민감값 패턴 검사를 통과했다.

실제 EKS/RDS 연결·장애·성능 및 최신 취약점 검증은 별도다. 이번 통합에서 취약점 스캔을 새로 실행하지 않았고 이전 High 35개 기록은 배포 승인과 무관하다. 최종 배포 전 최신 plan을 다시 만든다. [현재 구성](../../infra/TOPOLOGY.md)을 따른다.
- 최종 실제 network plan: NAT/EIP 각각 2개, 23 create / 0 change / 0 destroy, 교체 없음. apply 미실행. 이전 NAT 1개 plan은 사용하지 않는다.

## 후속 EKS 관리자 준비 (2026-10-14)

후속 CDC 결정: DB→Kafka 캡처 범위와 업무 토픽은 팀원에게 받을 항목으로 보류했다. [팀원 입력 목록](../design/infra/team-inputs.md)에 DB/CDC 및 Kafka/Consumer 담당에게 받을 연결 정보를 정리했다. 기존 디스크·보관 설정 외의 업무 입력은 임의 확정하지 않는다.

최신 코드 전체 정적 검사(2026-10-14): 전용 EKS 관리자 역할을 포함한 10개 Terraform root의 fmt/backend 없는 init/validate와 9개 suite의 mock plan 44개가 모두 통과했다. Kafka Helm 검사는 20 GiB/24시간 기본값 반영 후 21개 잘못된 입력 거부를 포함해 통과한 결과를 유지한다. 실제 AWS 리소스를 생성하거나 실환경 역할 assume/배포·연결 검증을 수행한 것은 아니다.

후속 Kafka 디스크 결정: 사용자가 broker당 20 GiB씩 3개(총 60 GiB)로 시작하도록 승인했다. chart 기본값과 runtime 예제에 반영하고 기본 렌더의 replica/volume size/보존 정책 및 StorageClass 확장 가능 설정을 검증한다. 토픽·partition·client·CDC 예산은 미정이며 기본 비활성을 유지한다. 실제 생성과 PVC 확장은 수행하지 않았다.

후속 Kafka 결정: 메시지 보관 기간은 24시간으로 시작한다. broker 기본 `retentionHours=24`를 반영하고 업무 토픽 예제의 `retentionMs=86400000`을 구분해 표시했다. 실제 업무 토픽은 아직 만들지 않았으며 디스크·토픽/partition·CDC slot/WAL 예산은 미정이다. Connect 내부 토픽의 compact 정책은 유지한다. Kafka 기본 비활성·실제 생성 마지막 원칙도 유지한다.

후속 결정: 업무 버킷 이름은 `clothes-query-datalake`를 우선 후보로 두고 내부 경로 구조는 나중에 결정한다. application/bronze/silver/gold는 제안이었으며 승인된 경로가 아니다. apps 입력 예제도 미정 placeholder로 바꿨다. WEB/WAS 앱 준비와 도메인·HTTPS도 사용자 요청으로 보류했다. 다음 인프라 항목인 Kafka/CDC는 먼저 메시지 보관 기간을 결정하며, 디스크·토픽·복제 슬롯 예산을 예제 값으로 임의 확정하지 않는다.

사용자가 전용 관리자 역할을 선택했고 현재 사용자·현재 PC만 먼저 허용하며 팀원 추가는 나중에 하기로 했다. EKS 모듈에 명시적 trust 목록을 가진 전용 역할과 해당 클러스터 DescribeCluster 권한, 관리자 access entry 연결을 준비했다. compute/apps의 Kubernetes token도 이 역할을 사용한다. 실제 ARN/IP는 Git 제외 EKS 입력에만 저장했고 역할 이름이 현재 사용되지 않음을 읽기 전용 확인했다. 팀원 목록 확장과 잘못된 trust/CIDR 거부를 포함한 mock plan 6개 및 eks/compute/apps validate를 통과했다. 실제 생성·역할 assume·kubectl 검증은 미실행이다. [접속 준비](../../infra/EKS_ACCESS.md)를 따른다.

## 업무 S3 별도 생성 승인·검증 (2026-10-14)

사용자가 전체 생성 마지막 원칙의 예외로 업무 버킷만 먼저 생성하도록 승인했다. 현재 인증 계정 및 후보 이름 부재를 확인한 뒤 storage 실제 plan(5 create / 0 change / 0 destroy)을 검토했고, 사용자 재확인 후 저장한 plan만 apply했다. 대상은 `clothes-query-datalake`이며 도쿄·버저닝 Enabled·AES256·퍼블릭 차단 4개·HTTPS 강제·빈 버킷을 확인했다. 후속 plan 종료 코드 0, 관리 리소스 5개다. storage state는 기존 backend의 `clothes-query/dev/storage/terraform.tfstate`에 8,078 bytes로 저장됐고 AES256·버저닝 및 lock 해제를 확인했다. bootstrap 변경·다른 스택 apply·내부 경로 생성은 수행하지 않았다. 실제 계정/state 내용과 비공개 입력/plan은 공개 Git에 넣지 않는다.
