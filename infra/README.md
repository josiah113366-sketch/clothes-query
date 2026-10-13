# infra

clothes-query의 AWS 인프라를 Terraform으로 관리한다. 리전은 `ap-northeast-1`(도쿄).

## 스택 순서와 의존 관계

```
bootstrap → network → eks → compute → apps
                          └→ platform (후속)
```

| 스택 | 위치 | 내용 | 의존 | 상태 |
|---|---|---|---|---|
| `bootstrap` | `bootstrap/` | state 저장용 S3 버킷 (버저닝, 암호화, 퍼블릭 차단) | 없음 | 코드 작성됨 |
| `network` | `stacks/network/` | 2 AZ VPC, public/app/db subnet, AZ별 NAT, S3 endpoint | bootstrap | 코드 작성·정적 검증 |
| `eks` | `stacks/eks/` | EKS Auto Mode, IAM, access entry | network | 코드 작성·정적 검증 |
| `compute` | `stacks/compute/` | custom NodeClass/NodePool, 타입·증설 한도·자동 축소 | network, eks | 코드 작성·정적 검증 |
| `rds` | `stacks/rds/` | private Multi-AZ PostgreSQL | network, eks | 코드 작성·정적 검증 |
| `storage` | `stacks/storage/` | 데이터 S3, 버저닝·암호화·보호 | bootstrap | 코드 작성·정적 검증 |
| `ecr` | `stacks/ecr/` | WEB/WAS 이미지 저장소 | bootstrap | 실배포·S3 state 저장 검증 완료 |
| `apps` | `stacks/apps/` | Pod Identity, WEB/WAS, Auto Mode ALB | eks, compute, rds, storage, 앱 이미지 | 코드 작성·정적 검증 |
| `platform` | `stacks/platform/` | Helm으로 Kafka / Spark / Airflow 설치 | eks | 예정 |

## apply / destroy 순서

- apply: bootstrap 상태 확인 후 network → eks → compute 순서. rds/storage/ecr 준비 후 apps, platform은 후속이다. 생성 테스트는 사용자 요청으로 마지막 단계에 진행한다.
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
