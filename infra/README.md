# infra

clothes-query의 AWS 기반 인프라를 Terraform으로, Kafka runtime을 별도 Helm release로 준비한다. 리전은 `ap-northeast-1`(도쿄).

## 스택 순서와 의존 관계

```
bootstrap → network → eks → compute → apps
                          └→ Kafka 운영자 → Kafka/Connect (Helm, 미배포)
```

| 스택 | 위치 | 내용 | 의존 | 상태 |
|---|---|---|---|---|
| `bootstrap` | `bootstrap/` | state 저장용 S3 버킷 (버저닝, 암호화, 퍼블릭 차단) | 없음 | 코드 작성됨 |
| `network` | `stacks/network/` | 2 AZ VPC, public/app/db subnet, AZ별 NAT, S3 endpoint | bootstrap | 코드 작성·정적 검증 |
| `eks` | `stacks/eks/` | EKS Auto Mode, IAM, access entry | network | 코드 작성·정적 검증 |
| `compute` | `stacks/compute/` | custom NodeClass/NodePool, 타입·증설 한도·자동 축소 | network, eks | 코드 작성·정적 검증 |
| `rds` | `stacks/rds/` | private Multi-AZ PostgreSQL | network, eks | 코드 작성·정적 검증 |
| `storage` | `stacks/storage/` | 데이터 S3, 버저닝·암호화·보호 | bootstrap | 코드 작성·정적 검증 |
| `ecr` | `stacks/ecr/` | WEB/WAS 및 선택적 Connect 이미지 저장소 | bootstrap | WEB/WAS 기존 배포 기록, Connect 코드·mock 준비 |
| `apps` | `stacks/apps/` | Pod Identity, WEB/WAS, Auto Mode ALB | eks, compute, rds, storage, 앱 이미지 | 코드 작성·정적 검증 |
| `workload-access` | `stacks/workload-access/` | 명시된 데이터 서비스의 S3 prefix별 IAM/Pod Identity | network, eks, storage, 서비스 입력 | 코드·mock 검증, 기본 binding 없음 |
| Kafka platform | [platform/kafka/](platform/kafka/README.md) | Strimzi 운영자·영구 저장소·Kafka/선택적 Connect Helm 구성 | eks, compute, 실제 입력·Secret·이미지 | 코드·로컬 검증, 기본 비활성 |
| Spark / Airflow | 미구현 | 정제·오케스트레이션 runtime | 실행 방식·서비스 입력 | 예정 |

Kafka 후속 준비는 선택적 Connect ECR, [로컬 CDC 전달 검사](platform/kafka/local-smoke/README.md), [JMX/consumer lag 지표 노출](platform/kafka/metrics/README.md)까지 포함한다. 실제 AWS 생성·수집 서버·알림은 미배포다.

로컬 TLS/ACL·Kafka 재생성/offset 검증과 [통합 자동 검사 코드](checks/README.md)도 준비했다. Connect 이미지의 불필요한 구성요소 제거·OS 패치 후 [재검사 결과](../docs/design/infra/connect-image-remediation-2026-10-14.md)는 Critical 0/High 35이며 잔여 조치가 필요하다. [통합 작업 기록](../docs/tasks/infra-local-ready.md)에서 브랜치와 검증 범위·원격 CI 결과를 확인한다. 실제 AWS 배포는 수행하지 않았다.

## apply / destroy 순서

- apply: bootstrap 상태 확인 후 network → eks → compute 순서. rds/storage/ecr 준비 후 apps, platform은 후속이다. 생성 테스트는 사용자 요청으로 마지막 단계에 진행한다.
- workload-access는 network/eks/storage 이후 서비스별 namespace/ServiceAccount·prefix/action 합의 시 준비한다. runtime 배포는 각 서비스 담당자의 별도 작업이다.
- Kafka는 EKS 자체 운영으로 결정했다. Terraform 기반 준비 후 공식 운영자/CRD·StorageClass → runtime 순서이며, [Kafka 안내](platform/kafka/README.md)의 2 AZ 한계·노드 예산·비용 영향을 확인한다. Spark/Airflow와 CDC 커넥터 설정은 포함하지 않았다.
- destroy: apps/platform → compute → eks → network 순서로 종속성을 검토한다. RDS·S3 삭제 보호는 자동 해제하지 않는다. bootstrap은 state 보존 대상이다.

## state

- 버킷: `clothes-query-tfstate-<AWS계정ID>` (프로젝트 전체에 하나)
- key: `clothes-query/dev/<스택명>/terraform.tfstate` (스택마다 다르게)
- `bootstrap`만 local state를 쓴다. 자세한 내용은 [bootstrap/bootstrap.md](bootstrap/bootstrap.md) 참고.

## 1차 고가용성 구성

실행 전 [구현·입력·검증 안내](IMPLEMENTATION.md)를 읽는다. 위 기존 platform 로드맵은 후속 단계다.

이번 순서는 `bootstrap 관리 상태 확인 → network → eks → compute → rds → apps`이며 storage/ecr은 bootstrap 확인 후 독립적으로 준비한다. apps는 먼저 기반 설정만 만들고, 이미지·DB Secret·인증서 준비 후 워크로드를 활성화한다.

노드 및 WEB/WAS 용량은 변수로 조정한다. [Generator 부하에 따른 증설·축소 가이드](SCALING.md)를 참고한다.

사용자 요청으로 ECR만 실환경 plan/apply 및 S3 state 저장을 검증했다. 다른 스택은 미배포다. 기존 bootstrap은 보존하며 재생성하지 않는다. 삭제 시에는 앱/ALB 등 종속 리소스를 먼저 검토하고 RDS·S3 삭제 보호를 자동 해제하지 않는다.

## 데이터 경로의 실측 전 준비

RDS의 선택적 CDC 파라미터와 데이터 서비스별 S3 접근 코드, Kafka/Connect 배포 구성을 준비했다. 기본값에서는 활성화하지 않으며 실제 예산·서비스 입력은 미정이다. [준비 범위와 연결 계약](../docs/design/infra/data-path-readiness.md)을 참고한다. Kafka/Connect의 실행 검증·Consumer·정제·조회 runtime 구현/배포는 남아 있다.
