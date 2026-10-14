# 준비된 구성과 남은 구성

상태: 결정(코드 관찰 사실) / 제안(후속 작업) · 2026-10-14

## 조사 근거

`origin/main=f0a6059`와 `infra/analysis=7cdd4d5`를 분리해서 조사했다. 아래 `infra/analysis:<경로>`는 Git의 해당 커밋에서 읽은 파일을 뜻하며, 이 계획 브랜치에 그 파일이 있다는 뜻이 아니다. 실배포에 관한 설명은 기존 작업 기록의 내용이며 AWS에서 재확인하지 않았다.

## 기반 인프라 현황

| 구성 | 근거 | 준비 수준 | 플랫폼을 위해 남은 일 |
|---|---|---|---|
| state bootstrap | main의 [main.tf](../../../infra/bootstrap/main.tf), [설명](../../../infra/bootstrap/bootstrap.md) | state용 S3 코드 존재 | 실제 관리 PC·local state 소유권은 배포 환경에서 확인 |
| 네트워크 | `infra/analysis:infra/modules/network/main.tf` | 2 AZ, public/app/db subnet, AZ별 NAT, app S3 endpoint 코드 | 플랫폼 통신 경로와 필요 SG·endpoint를 합의. 무조건 새 VPC나 endpoint를 추가하지 않음 |
| EKS | `infra/analysis:infra/modules/eks/main.tf` | Auto Mode·클러스터/노드 IAM·관리자 access entry·API CIDR·로그 코드 | 플랫폼 namespace와 팀원 RBAC, 실행 도구 호환성 확인 |
| 노드풀 | `infra/analysis:infra/modules/compute/main.tf`, `infra/SCALING.md` | custom NodeClass/NodePool. 기존 한도 8 vCPU/32 GiB | 기존 WEB/WAS 및 시스템 Pod와 합산한 용량, 임시 작업·교체 여유 검토 |
| 운영 DB | `infra/analysis:infra/modules/rds/main.tf` | private Multi-AZ PostgreSQL, 백업·삭제 보호·관리형 master password | CDC 파라미터 그룹·전용 DB 계정·WAL/slot 관리가 별도로 필요 |
| 데이터 S3 | `infra/analysis:infra/modules/storage/main.tf` | 버전 관리·암호화·공개 차단·TLS·삭제 보호 코드 | Bronze/Silver/Gold 경로별 서비스 권한, checkpoint·로그 경로와 보존 합의 |
| 이미지 저장소 | `infra/analysis:infra/modules/ecr/main.tf`, `infra/IMPLEMENTATION.md` | WEB/WAS 2개. 배포·S3 state 검증 기록 있음 | Connect/Consumer/Spark 등 커스텀 이미지 필요 여부와 저장소 소유자 결정 |
| WEB/WAS | `infra/analysis:infra/modules/apps/main.tf` | Deployment/Service/ALB/ConfigMap/Pod Identity/PDB/HPA 코드 | 팀원 이미지·Secret·인증서 입력 및 실제 연결 확인 |
| 기본 메트릭 | 같은 apps 모듈 | Metrics Server addon과 WAS CPU HPA 코드 | 장기 저장·로그·Kafka lag·알림 기반은 별도. Metrics Server와 중복 소유하지 않음 |
| 검증 | `infra/analysis:infra/tests/*.tftest.hcl`, `docs/tasks/infra-analysis.md` | mock plan 16개 통과 기록 및 테스트 파일 존재 | 플랫폼용 검증 추가. 기존 통과 기록을 이번 PC의 실행 결과로 표시하지 않음 |

main에는 회원 베이스라인 구현도 추가돼 있다. 이는 플랫폼의 외부 의존성으로만 확인했고 수정하지 않는다. 이전 분석의 “시뮬레이터는 골격뿐”이라는 설명은 현재 main에는 맞지 않는다.

## 새로 준비할 플랫폼 항목

| 항목 | 코드 관찰 및 차이 | 후속 산출물 |
|---|---|---|
| namespace·팀원 권한 | 앱 namespace/ServiceAccount는 있지만 공용 데이터 플랫폼 권한 구성은 없음 | 서비스별 namespace/ServiceAccount/RBAC와 권한 안내 |
| 영구 볼륨 | Auto Mode block storage 기능은 켜져 있으나 StorageClass 선언은 없음 | 선택한 서비스의 PVC와 맞는 StorageClass, 용량·보존·복구 정책 |
| Kafka | main 및 기반 브랜치에 Kafka 배포 구현 없음 | 운영 방식 선택 후 배포·인증·스토리지·자원 설정 |
| Connect/Debezium 실행 환경 | 배포 구현 없음 | 런타임·플러그인 이미지·Secret 참조·접근 통제·내부 저장 설정 |
| RDS CDC | custom DB parameter group 및 `rds.logical_replication` 선언 없음 | 기반 브랜치 담당과 별도 변경 작업. publication/slot/계정은 데이터 담당과 공동 검토 |
| Consumer 실행 기반 | 실행 이미지 및 배포 계약 미확인 | 담당자 이미지에 대한 Deployment/Job, ServiceAccount와 S3 역할 |
| Spark | 공용 실행 기반 없음 | 제출 방식 결정 후 실행 namespace·RBAC·S3 권한·자원 한도 |
| Airflow | 공용 실행 기반 없음 | 사용 확정 후 executor·metadata DB·DAG 배포·로그/Secret 참조 |
| 관측·알림 | 장기 지표/애플리케이션 로그 수집 배포 없음 | 제품 선택 후 공용 수집·저장·보존·접근 설정 |
| CI | `.github/workflows` 없음 | 인증 없는 정적 검사부터 시작. 실배포 자동화는 별도 결정 |

**판단:** 기반 코드만으로 Kafka의 데이터 보존이나 DB CDC가 준비됐다고 볼 수 없다. Auto Mode는 StorageClass를 자동 생성하지 않으며 전용 provisioner 구성이 필요하다. [AWS StorageClass 안내](https://docs.aws.amazon.com/eks/latest/userguide/create-storage-class.html)

RDS PostgreSQL의 논리 복제는 파라미터·권한 설정이 필요하고 정적 파라미터 변경은 재시작이 필요하다. 현재 코드의 부재를 근거로 “추가 설정 필요”로 분류하며, 실제 DB 설정값이 꺼져 있다고 단정하지 않는다. [AWS 논리 복제 안내](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/PostgreSQL.Concepts.General.FeatureSupport.LogicalReplication.html)

## 상위 ZIP의 재사용 판단

경로는 ZIP 내부 `infra_reuse_analysis/` 기준이다. 루트 `README.md`, `reuse_matrix.md`, `missing_components.md`와 추출 파일 목록을 참고했다. 개별 추출 파일의 런타임 동작은 이번 작업에서 검증하지 않았다.

| 출처 | 활용할 부분 | 그대로 배포할 수 없는 이유 |
|---|---|---|
| `extracted/data_infra/kafka-elk-efk-opensearch/docker-compose.yml` | Kafka 로컬 구성의 검토 후보 | 로컬 예제이며 EKS용 영구 볼륨·인증·가용성 설계가 아님 |
| 같은 폴더의 `vector.yaml` | 로그/전송 설정 참고 | 목표 Consumer의 commit·중복·재처리 계약을 대신하지 않음 |
| `extracted/kubernetes/devops_tf_k8s_cd/monitoring/kube-prometheus-stack-values.yaml` | 메트릭 수집 설정 후보 | 클러스터 버전·권한·자원·PVC·접근 방법을 다시 검토해야 함 |
| 같은 `monitoring/resources/`의 dashboard·rules | 인프라 대시보드·경보 후보 | 실제 지표 이름·대상·임계값·PII 취급 검증 필요 |
| `extracted/cicd/`의 workflow·Argo 템플릿 | CI/GitOps 구조 참고 | 저장소·브랜치·권한과 관리 주체가 프로젝트에 맞게 결정되지 않음 |
| ZIP의 Spark/Airflow 관련 보고서 | 기존 예제의 위치·누락 조사 참고 | 현재 추출 자산에서 재사용 가능한 EKS 배포 기반을 확보했다고 간주하지 않음 |

실습에 포함된 다른 리전, MySQL 연결, 외부 서비스, 삭제 옵션과 기본 비밀번호를 프로젝트 설정으로 승격하지 않는다. 이미지·차트 버전은 후속 구현 시 공식 배포처에서 확인하고 고정한다.
