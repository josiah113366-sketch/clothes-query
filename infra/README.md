# infra

2026-10-16 최소 배포 완료: 기존 RDS/S3를 보존하고 NAT 1개·EKS 1.36 Auto Mode·private t3a.large 1대·단일 Kafka를 생성했다. 실제 관리자 접속·20GiB 암호화 EBS·TLS 메시지 생산/소비·JMX를 확인했고 network/EKS/compute 후속 plan은 변경 없음이다. [실행 결과·인수인계](../docs/tasks/infra-deploy-result.md).

2026-10-18 사용자 승인으로 실제 RDS → Kafka → S3 JSON6개 전송·CDC 중단 후 이어받기와 Pod Identity의 다른 prefix 접근 거부를 확인했다. 더미 DB/slot·Kafka/Connect·S3 버전8개·임시 IAM/접속 권한을 정리했다. 노드1대·Kafka4 Pod Ready/재시작0을 유지하고 rds/network/ecr/workload-access 후속 plan은 모두 변경 없음이다. RDS 논리 복제 설정과 데이터 없는 Connect ECR 이미지는 후속 연결 기반으로 남았다. [실제 시험·정리 기록](../docs/tasks/infra-pipeline-smoke.md).

현재 network 비공개 입력은 `enable_nat_gateways=true`, `single_nat_gateway=true`다. NAT 한 개를 두 app subnet에서 공유하며 S3 Gateway Endpoint는 유지한다. RDS는 여전히 `use_eks_security_group=false`로 클라이언트 연결을 기다린다.

compute는 `t3a.large` On-Demand, 6 vCPU/24GiB(세 대분 한도)다. 실제 한 대 배치를 확인했으며 고정 노드 수나 엄격한 비용 상한은 아니다. Kafka는 `single-node-values.yaml` + `measurement-values.yaml`로 broker 1개·RF 1·20GiB·72시간·synthetic 토픽/JMX/lag를 활성화했다. Connect는 비활성이다. Airflow는 namespace만 준비했으며 동료가 설치한다. Fargate 제네레이터·WEB/WAS·ALB·Spark·업무 CDC/S3 Sink는 미배포이며 [연결 입력](../docs/design/infra/team-inputs.md)을 따른다.

통합 PR #11은 main에 머지됐다. 배포 결과는 `infra/deploy-result`에서 기록한다. 기존 준비 이력은 [업로드·정리 기록](../docs/tasks/infra-ready.md)을 따른다.

배치 기준: **두 AZ subnet, RDS Single-AZ, NAT 1개 공유, private t3a.large 1대·Kafka 1개**. 현재 계정에서는 t3a.large 제공 AZ를 ap-northeast-1a만 확인했다. [현재 구성](TOPOLOGY.md)을 따른다.

clothes-query의 AWS 기반 인프라를 Terraform으로, Kafka runtime을 별도 Helm release로 준비한다. 리전은 `ap-northeast-1`(도쿄).

## 스택 순서와 의존 관계

```
bootstrap → network → eks → compute → apps
                          └→ Kafka 운영자 → Kafka (Helm, 측정 배포 완료; Connect 비활성)
```

| 스택 | 위치 | 내용 | 의존 | 상태 |
|---|---|---|---|---|
| `bootstrap` | `bootstrap/` | state 저장용 S3 버킷 (버저닝, 암호화, 퍼블릭 차단) | 없음 | 코드 작성됨 |
| `network` | `stacks/network/` | 2 AZ VPC, public/app/db subnet, NAT 1개 공유, S3 endpoint | bootstrap | 배포·후속 변경 없음 |
| `eks` | `stacks/eks/` | EKS Auto Mode, IAM, access entry | network | ACTIVE·실제 관리자 접속·후속 변경 없음 |
| `compute` | `stacks/compute/` | custom NodeClass/NodePool, 타입·증설 한도·자동 축소 | network, eks | private t3a.large 1대 Ready·후속 변경 없음 |
| `rds` | `stacks/rds/` | private Single-AZ PostgreSQL | network, 선택 eks | 논리 복제 활성·실제 CDC 검증, 시험 계정/slot 제거·업무 연결 후속 |
| `storage` | `stacks/storage/` | 데이터 S3, 버저닝·암호화·보호 | bootstrap | 사용자 승인 배포·후속 무변경 plan 확인 |
| `ecr` | `stacks/ecr/` | WEB/WAS 및 선택적 Connect 이미지 저장소 | bootstrap | 세 저장소 배포·Connect 이미지 push/EKS pull 확인 |
| `apps` | `stacks/apps/` | Pod Identity, WEB/WAS, Auto Mode ALB | eks, compute, rds, storage, 앱 이미지 | 코드 작성·정적 검증 |
| `workload-access` | `stacks/workload-access/` | 명시된 데이터 서비스의 S3 prefix별 IAM/Pod Identity | network, eks, storage, 서비스 입력 | 코드·mock 검증, 기본 binding 없음 |
| Kafka platform | [platform/kafka/](platform/kafka/README.md) | Strimzi 운영자·영구 저장소·Kafka/선택적 Connect Helm 구성 | eks, compute, 실제 입력·Secret·이미지 | 코드·로컬 검증, 기본 비활성 |
| Spark | 미구현 | 정제 runtime | 실행 방식·서비스 입력 | 예정 |
| Airflow | [로컬 실행 후보](platform/airflow/README.md) | API 재처리·5분 예약 | 운영 배포 방식·메타데이터 DB·인증/IAM | AWS 미배포 |

Kafka 최소 측정 환경은 실제 배포됐고 JMX HTTP 지표를 확인했다. Connect ECR과 [로컬 CDC/S3 검사](platform/kafka/local-smoke/README.md), [실제 AWS 시험 결과](platform/kafka/pipeline-smoke/README.md)는 후속 업무 연결 기반이다. [지표 노출](platform/kafka/metrics/README.md)은 준비했지만 장기 수집 서버·알림은 미배포다.

로컬 TLS/ACL·Kafka 재생성/offset 검증과 [통합 자동 검사 코드](checks/README.md)도 준비했다. Connect 이미지의 불필요한 구성요소 제거·OS 패치 후 [재검사 결과](../docs/design/infra/connect-image-remediation-2026-10-14.md)는 Critical 0/High 35이며 잔여 조치가 필요하다. [통합 작업 기록](../docs/tasks/infra-local-ready.md)에서 브랜치와 검증 범위·원격 CI 결과를 확인한다. 실제 AWS 배포는 수행하지 않았다.

## apply / destroy 순서

- apply: bootstrap 상태 확인 후 network → eks → compute 순서. rds/storage/ecr 준비 후 apps, platform은 후속이다. 생성 테스트는 사용자 요청으로 마지막 단계에 진행한다.
- workload-access는 network/eks/storage 이후 서비스별 namespace/ServiceAccount·prefix/action 합의 시 준비한다. runtime 배포는 각 서비스 담당자의 별도 작업이다.
- Kafka는 EKS 자체 운영으로 결정했다. Terraform 기반 준비 후 공식 운영자/CRD·StorageClass → runtime 순서이며, [Kafka 안내](platform/kafka/README.md)의 2 AZ 한계·노드 예산·비용 영향을 확인한다. Airflow는 별도 로컬 후보 검사만 준비했다. Spark/Airflow의 AWS 배포와 CDC 커넥터 설정은 포함하지 않았다.
- destroy: apps/platform → compute → eks → network 순서로 종속성을 검토한다. RDS·S3 삭제 보호는 자동 해제하지 않는다. bootstrap은 state 보존 대상이다.

## state

- 버킷: `clothes-query-tfstate-<AWS계정ID>` (프로젝트 전체에 하나)
- key: `clothes-query/dev/<스택명>/terraform.tfstate` (스택마다 다르게)
- `bootstrap`만 local state를 쓴다. 자세한 내용은 [bootstrap/bootstrap.md](bootstrap/bootstrap.md) 참고.

## 1차 고가용성 구성

실행 전 [구현·입력·검증 안내](IMPLEMENTATION.md)를 읽는다. 위 기존 platform 로드맵은 후속 단계다.

이번 순서는 `bootstrap 관리 상태 확인 → network → eks → compute → rds → apps`이며 storage/ecr은 bootstrap 확인 후 독립적으로 준비한다. apps는 먼저 기반 설정만 만들고, 이미지·DB Secret·인증서 준비 후 워크로드를 활성화한다.

노드 및 WEB/WAS 용량은 변수로 조정한다. [Generator 부하에 따른 증설·축소 가이드](SCALING.md)를 참고한다.

사용자 요청으로 ECR·업무 S3·RDS에 이어 NAT 1개·EKS·compute·Kafka 측정 환경을 배포했다. apps는 미배포다. Terraform state는 기존 S3 backend의 스택별 key에 보관한다. 기존 bootstrap은 보존하며 재생성하지 않는다. 삭제 시에는 종속 리소스를 먼저 검토하고 RDS·S3 삭제 보호를 자동 해제하지 않는다.

## 데이터 경로의 실측 전 준비

RDS의 선택적 CDC 파라미터와 데이터 서비스별 S3 접근 코드, Kafka/Connect 배포 구성을 준비했다. 업무 연결은 아직 활성화하지 않았으며 실제 예산·서비스 입력은 미정이다. Kafka synthetic TLS 메시지 검증은 완료했지만 Connect·Consumer·정제·조회 runtime과 RDS→Kafka→S3 전체 경로는 남아 있다. [연결 계약](../docs/design/infra/team-inputs.md)을 참고한다.
