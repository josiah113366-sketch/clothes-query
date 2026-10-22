# infra

2026-10-22 판정·조사 연결: [Git DAG 경로와 이미지 안내](platform/agent-development/README.md), [projection INSERT 실측](platform/agent-access/projection-validation.md), [승인 대시보드 접근](stacks/dashboard-access/README.md)을 준비한다. 업무 DAG·모델·SQL·승인 로직은 담당자 소유이며 [진행 기록](../docs/tasks/infra-agent-runtime-connections.md)에서 적용·미적용을 구분한다. 자동 머지는 하지 않는다.

Gold B 표 등록: Glue `gold_b` DB는 [gold-b-catalog](stacks/gold-b-catalog/README.md) Terraform 스택이 관리한다. `pipelines/gold_b/ddl/database.sql`은 실행하지 않으며, 나머지 5개 테이블은 담당자 SQL을 Athena에서 실행해 등록한다. 기존 권한 스택과 state가 분리돼 있고 데이터 입력은 하지 않는다. [적용 기록](../docs/tasks/infra-gold-b-catalog.md).

2026-10-21 입력 공유 결정: 공통 배포값은 추적되는 `deployment.auto.tfvars.json`과 `deployment.backend.hcl`로 관리하고 개인 IP·이메일만 로컬 override에 둔다. Terraform은 공유 auto 파일을 자동 로드한다. [파일 구분·실행 방법·보류 스택](DEPLOYMENT_CONFIG.md)을 먼저 따른다. 아래의 비공개 계정 입력 설명은 이전 기록이다.
2026-10-21 개발 Airflow 배포 완료: [Airflow 실행 기반](platform/airflow/README.md)은 기존 RDS 전용 DB·Simple Auth Manager·별도 업무 Pod 실행 신원과 연결했다. API 권한·S3 task 로그·5분 합성 cron 검증을 통과했고 테스트 DAG는 다시 pause했다. 기존 Kafka/API 노드 2개를 유지하며 새 노드·ALB·PVC·RDS 서버를 추가하지 않았다. 실제 판정/조사/재처리 DAG·업무 이미지·Athena 업무 쿼리·Spark 연결은 후속이다. [검증 기록](../docs/tasks/infra-airflow-runtime.md).

2026-10-21 Gold B 접근: 기존 network/eks/storage 이후 [gold-b-access](stacks/gold-b-access/README.md)에서 판정·조사 역할과 Athena workgroup을 분리해 조회용 자원 8개를 적용했다. 조회 결과는 기존 버킷의 `athena-results/detection/` 및 `athena-results/investigation/`이다. 이름·경로·쿼리당 스캔 상한은 변수다. agent namespace/ServiceAccount를 연결하고 실제 임시 Pod의 접근·정답표 차단 24개 검사를 통과했으며 합성 객체/Pod는 정리했다. 판정 업무 기록 쓰기와 업무 앱은 아직 미연결이다. 기존 미적용 Athena 단일 workgroup 후보와 동시에 배포하지 않는다. [작업 기록](../docs/tasks/infra-gold-b-access-prep.md). 아래 배포 설명은 각 기록일 기준이며 최신 업무 CDC는 [토폴로지](TOPOLOGY.md)와 해당 작업 기록을 따른다.

2026-10-16 최소 배포 완료: 기존 RDS/S3를 보존하고 NAT 1개·EKS 1.36 Auto Mode·private t3a.large 1대·단일 Kafka를 생성했다. 실제 관리자 접속·20GiB 암호화 EBS·TLS 메시지 생산/소비·JMX를 확인했고 network/EKS/compute 후속 plan은 변경 없음이다. [실행 결과·인수인계](../docs/tasks/infra-deploy-result.md).

2026-10-18 사용자 승인으로 실제 RDS → Kafka → S3 JSON6개 전송·CDC 중단 후 이어받기와 Pod Identity의 다른 prefix 접근 거부를 확인했다. 더미 DB/slot·Kafka/Connect·S3 버전8개·임시 IAM/접속 권한을 정리했다. 노드1대·Kafka4 Pod Ready/재시작0을 유지하고 rds/network/ecr/workload-access 후속 plan은 모두 변경 없음이다. RDS 논리 복제 설정과 데이터 없는 Connect ECR 이미지는 후속 연결 기반으로 남았다. [실제 시험·정리 기록](../docs/tasks/infra-pipeline-smoke.md).

현재 network 비공개 입력은 `enable_nat_gateways=true`, `single_nat_gateway=true`다. NAT 한 개를 두 app subnet에서 공유하며 S3 Gateway Endpoint는 유지한다. RDS는 여전히 `use_eks_security_group=false`로 클라이언트 연결을 기다린다.

compute는 `t3a.large` On-Demand, 6 vCPU/24GiB(세 대분 한도)다. 실제 한 대 배치를 확인했으며 고정 노드 수나 엄격한 비용 상한은 아니다. Kafka는 `single-node-values.yaml` + `measurement-values.yaml`로 broker 1개·RF 1·20GiB·72시간·synthetic 토픽/JMX/lag를 활성화했다. Connect는 비활성이다. Airflow는 namespace만 준비했으며 동료가 설치한다. Fargate 제네레이터·WEB/WAS·ALB·Spark·업무 CDC/S3 Sink는 미배포이며 [연결 입력](../docs/design/infra/team-inputs.md)을 따른다.

통합 PR #11은 main에 머지됐다. 배포 결과는 `infra/deploy-result`에서 기록한다. 기존 준비 이력은 [업로드·정리 기록](../docs/tasks/infra-ready.md)을 따른다.

배치 기준: **두 AZ subnet, RDS Single-AZ, NAT 1개 공유, private t3a.large 1대·Kafka 1개**. 현재 계정에서는 t3a.large 제공 AZ를 ap-northeast-1a만 확인했다. [현재 구성](TOPOLOGY.md)을 따른다.

2026-10-19 개발용 사용자 요청으로 우리 EKS public 관리 API의 IPv4 접속 범위를 `0.0.0.0/0`으로 변경했다. IAM/RBAC와 private endpoint는 유지한다. 원래 IP 목록은 비공개 입력에 보존하며 `allow_public_api_from_anywhere=false`로 바꿔 적용하면 복원된다. 자동 원복은 없다. [현재 접속·원복](EKS_ACCESS.md).

clothes-query의 AWS 기반 인프라를 Terraform으로, Kafka runtime을 별도 Helm release로 준비한다. 리전은 `ap-northeast-1`(도쿄).

## 스택 순서와 의존 관계

2026-10-21 후속: [Agent 개발 접근 스택](stacks/agent-development-access/README.md)은 기존 EKS 뒤에 독립 state로 추가한다. [판정·조사 이미지 등록/인증/협의 항목](platform/agent-development/README.md)을 따른다. 기존 EKS·관리자·업무 쓰기 권한을 변경하지 않는다.

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
| `ecs-review-simulator` | `stacks/ecs-review-simulator/` | 리뷰 시뮬레이터 ECS Fargate 기반: ECR·클러스터·IAM·Secret·꺼진 예약 실행·로그/대시보드 (담당자 apply, [안내](stacks/ecs-review-simulator/README.md)) | network, storage | 코드·validate, 미배포 |
| `sagemaker-review-score` | `stacks/sagemaker-review-score/` | 리뷰 점수화 SageMaker Processing Job 실행 기반: IAM 역할·SG·스크립트용 SSM 설정·Airflow용 launcher 정책 (실행은 Airflow silver DAG 종료 후, [안내](stacks/sagemaker-review-score/README.md)) | network, storage | 코드·validate·plan(9 create), 미배포 |
| `ecs-simulator` | [stacks/ecs-simulator/](stacks/ecs-simulator/README.md) | 거래·회원 시뮬레이터 ECS Fargate: ECR·클러스터·IAM·SG·오염용 DB Secret·로그, 이미지 digest가 있으면 태스크 정의(컨테이너 3개)·서비스 1개 (담당자 apply) | network, storage, 업무 API(내부 ALB) | 적용 완료(태스크 1개 Running, 컨테이너 3개) |
| `workload-access` | `stacks/workload-access/` | 명시된 데이터 서비스의 S3 prefix별 IAM/Pod Identity | network, eks, storage, 서비스 입력 | 코드·mock 검증, 기본 binding 없음 |
| `team-access` | [stacks/team-access/](stacks/team-access/README.md) | 동료 WAS 배포·클러스터 운영 조회 | 기존 EKS, 비공개 동료 신원 | 2026-10-19 실제 연결·RBAC16개 통과·후속 plan 변경 없음; 동료 본인 접속 확인 후속 |
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
