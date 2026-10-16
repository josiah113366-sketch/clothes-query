# 재사용 판단

상태: 제안 · 실배포 리소스 재사용은 state 및 소유권 확인 후 결정

경로 약어는 ZIP 내부 `infra_reuse_analysis/` 기준이다.

- `T`: `extracted/terraform/devops_tf_k8s_ci/infra/`
- `K`: `extracted/kubernetes/devops_tf_k8s_cd/k8s/`
- `A`: `extracted/docker/devops_tf_k8s_ci/apps/`

| 구성 | 분류 | 파일 근거 | 판단 및 최소 작업 |
|---|---|---|---|
| state S3 bootstrap | 그대로 재사용 가능 | Git `infra/bootstrap/*.tf` | 기존 주소/lock/provider/local state 방식을 보존. 기배포 여부 확인 전 재apply 금지 |
| PostgreSQL DDL | 그대로 재사용 가능 | Git `db/schema/*.sql` | 기존 스키마 계약 유지. 기존 DB에 재실행하기 전 migration/존재 여부 확인 |
| VPC/subnet/route | 수정 후 재사용 가능 | `T/vpc.tf`, `locals.tf`, `variables.tf` | network 모듈/스택으로 분리. 리전/AZ, CIDR, 이름, NAT 수를 결정한 뒤 입력화 |
| EKS Auto Mode | 확인 또는 의사결정 필요 | `T/eks.tf`; Git `infra/README.md` | 실습은 Auto Mode, 저장소 로드맵은 노드그룹/IRSA. 실제 배포를 먼저 확인하고 방식을 합의 |
| EKS/IAM/access entry | 수정 후 재사용 가능 | `T/iam.tf`, `eks.tf` | 선택한 운영 방식에 맞는 권한만 사용. 공개 API CIDR 제한, 관리자 권한 범위 검토 |
| ECR | 수정 후 재사용 가능 | `T/ecr.tf` | web/was 저장소 패턴 사용. force_delete, mutable tag, 보존 10개 정책 재검토; 이름 변경 |
| RDS subnet group | 수정 후 재사용 가능 | `T/rds.tf` | network의 DB subnet output 연결 |
| RDS 엔진/SG | 수정 후 재사용 가능 | `T/rds.tf`, `security.tf` | MySQL 8.0/3306을 그대로 복사하지 않음. PostgreSQL 설정·5432·백업/삭제 보호로 새 설계. 기존 DB 엔진을 변경하는 계획이 아님 |
| 데이터 S3 | 수정 후 재사용 가능 | ZIP `extracted/terraform/kafka-elk-efk-opensearch/infra/s3.tf`, `extracted/terraform/log_gen/infra/s3.tf` | 공개 차단·암호화 패턴 재사용. 삭제 방지·버전/보존·이름·권한 보강. state 버킷과 분리 |
| S3 Gateway Endpoint | 신규 생성 필요(코드) | Git 부재; ZIP 추출 TF 선언 부재 | network에 app route table 연결. 기존 endpoint 존재 시 중복 생성하지 않음 |
| WEB 이미지 | 수정 후 재사용 가능 | `A/web/nginx.conf`, `Dockerfile`, `index.html` | 80, /health, /api/ 프록시 골격 활용. 팀 UI와 경로/로그 정책 합의 |
| WAS 이미지 | 수정 후 재사용 가능 | `A/was/app.py`, `Dockerfile`, `requirements.txt` | 8000, /health, /api/info 골격. PyMySQL·MySQL SQL 교체, S3 SDK 및 API 신규 구현 |
| Deployment/Service | 수정 후 재사용 가능 | `K/base/*-deployment.yaml`, `*-service.yaml` | probe 및 requests/limits 존재. 이미지, namespace, Secret, ServiceAccount, 수량 조정 |
| Ingress | 수정 후 재사용 가능 | `K/base/ingress*.yaml` | backend web → 실제 web-service 정합화. Auto Mode/LBC 하나만 선택 |
| Secret/ConfigMap·workload IAM | 신규 생성 필요(통합) | `K/base/was-deployment.yaml`의 rds-secret 참조 | 실제 Secret 공급·회전 구현 필요. S3 접근 ServiceAccount 역할 및 비밀 없는 설정 분리 |
| CI/CD·Argo·Kafka·Generator·AI | 현재 단계에서 불필요 | ZIP `extracted/cicd/`, `data_infra/`; Git simulator | 후속 단계. CI용 OIDC와 platform 전체를 이번에 배포하지 않음 |

## 직접 확인한 호환성 결함

1. `T/variables.tf`: region 기본값은 ap-northeast-2, AZ 기본값은 us-east-2a/c. `K/overlays/dev/kustomization.yaml` 이미지도 다른 리전 고정이다. 실제 tfvars 실행값은 확인하지 않았으며, 오류는 기본값 조합에서 확정된다.
2. `K/base/ingress.yaml`은 Service `web`을 참조하지만 선언은 `web-service`다.
3. `K/base/was-service.yaml`의 `metadata.monitoring`은 labels 아래로 옮겨야 한다. 현재 단계에서 모니터링 도입은 별도다.
4. `A/was/app.py`의 `/api/db`는 GET 요청에서 CREATE TABLE/INSERT를 수행하고 오류 문자열을 외부로 반환한다. 연결 점검은 읽기 전용으로 바꾸고 예외 응답을 정리해야 한다.
5. 실습 WEB은 `/api/`를 `was-service:8000`으로 전달하며 URI를 유지한다. FastAPI의 `/api/info`, `/api/db`와 일치한다. 서비스 이름을 바꾸면 nginx도 함께 바꿔야 한다.
6. `/health`는 프로세스 상태만 반환한다. DB/S3 연결 성공을 증명하지 않으며 별도 통합 검증이 필요하다. DB 장애를 liveness와 결합해 재시작 폭주를 만들지 않는다.

## 통합 원칙

실습 Terraform root를 저장소에 통째로 합치지 않는다. 같은 `aws_vpc.main`, locals, variables 등의 중복 선언과 잘못된 state 연결을 피하도록 필요한 리소스만 기존 modules/stacks 관례에 맞춰 옮기는 방안을 제안한다. 이미 관리되는 리소스의 module 주소 변경도 state migration에 해당하므로 별도 승인 대상이다.

IAM/OIDC는 계정 내 존재 여부와 소유 state를 먼저 확인한다. GitHub OIDC와 EKS IRSA OIDC는 용도가 다르며 한쪽의 존재가 다른 쪽을 대체하지 않는다. CI용 GitHub OIDC 생성은 후속 단계로 보류한다.
