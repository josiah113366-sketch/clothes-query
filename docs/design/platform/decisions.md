# 구현 전 결정 목록

상태: 제안 / 미정 · 2026-10-14

## 결정된 범위

- 인프라 담당의 플랫폼 계획만 작성한다. 제네레이터와 데이터 처리·AI 로직을 구현하지 않는다.
- 이 PC에서는 실제 배포하지 않는다. 기반 브랜치·state·팀원 파일을 보존한다.
- `infra/analysis@7cdd4d5`의 도쿄·PostgreSQL·EKS Auto Mode 구성은 후속 계획의 기반으로 참고한다. 이 계획에서 리전·엔진·노드 한도를 바꾸지 않는다.

## 결정표

아래 항목은 아직 구현 지시가 아니다. 합의된 항목만 후속 작업 지시서의 “결정”으로 옮긴다. Kafka/Connect부터 시작할 경우 D01~D06 및 D10에서 해당 서비스에 필요한 입력을 먼저 확정하고 Spark/Airflow 선택은 뒤로 미룰 수 있다.

| ID | 항목 | 검토할 선택과 기준 | 결정에 참여할 담당 | 완료 증거 |
|---|---|---|---|---|
| D01 | Kafka 운영 방식 | EKS 자체 운영 / 관리형 서비스. 기존 EKS 로드맵, 운영 부담, 예산·가용성·클라이언트 요구 비교 | 인프라 + 수집 | 운영 방식, 배포 도구·버전·관리자 확정 |
| D02 | Kafka 규모·보존 | broker/controller 배치, 복제·partition·보존, 예상 데이터량과 장애 허용. 그림의 토픽 6개만으로 용량을 정하지 않음 | 인프라 + 수집 | 처리량·보존·복구 목표와 산정표 |
| D03 | 인증·내부 접근 | TLS·클라이언트 인증·ACL, Connect 관리 API 및 UI의 접속 경로 | 인프라 + 각 클라이언트 담당 | 서비스별 통신표·접근 역할·Secret 참조 |
| D04 | PVC·StorageClass | EKS 자체 운영 선택 시 볼륨 종류·용량·암호화·AZ·reclaim/확장·복구, 삭제 시 데이터 보존 | 인프라 + 수집 | StorageClass/PVC 요구와 복구 기준 |
| D05 | RDS CDC | DB 엔진 버전과 맞는 parameter group, 계정·publication/slot, 캡처 allowlist·PII 제외, WAL 보존·관측 | 인프라 + DB/CDC | 기반 변경 작업, 재시작·failover 검증 계획, 권한 명세 |
| D06 | Connect 런타임 | 배포 방식·호환 버전·플러그인 이미지, 내부 토픽과 worker 수, 설정 등록·회전 주체 | 인프라 + CDC | 이미지/릴리스 관리 및 커넥터 공급 계약 |
| D07 | Spark 실행 | Kubernetes 직접 제출 / 별도 operator / 다른 실행 환경. 배치·스트리밍과 제출 주체를 먼저 결정 | 인프라 + 정제 | 이미지·RBAC·동시성·driver/executor 요구 |
| D08 | Airflow 실행 | 사용 여부·executor·metadata DB·DAG 공급·로그·UI 인증. 운영 DB와의 공유는 자동 결정하지 않음 | 인프라 + 오케스트레이션 | 실행·DB·Secret·배포 계약 |
| D09 | 메트릭·로그·알림 | 수집 제품, 대상·보존·S3/DB 지표·Kafka lag·저장/PVC·인증·수신처 | 인프라 + 각 서비스 담당 | 수집 대상/보존/알림표와 자원 산정 |
| D10 | Secret·AWS 권한 | 공급/회전 도구·담당, 서비스별 Pod Identity와 S3 prefix. 장기 AWS 키를 앱에 배포하지 않음 | 인프라 + 서비스 담당 | Secret 이름/키/전달 절차, 권한표 |
| D11 | 용량·예산 | 기존 시스템+WEB/WAS+플랫폼 상시 요청량+동시 잡+교체 여유, 가동 시간·스토리지·전송 비용 | 인프라 + 팀 | 자원 예산표, 기존 한도 변경 필요 여부 |
| D12 | 배포·state 소유 | Terraform/Helm/GitOps 역할, CRD/클러스터 공용 리소스 소유, 환경/릴리스 분리·승인·롤백 | 인프라 + 배포 담당 | 각 리소스/릴리스의 단일 관리자와 실행 순서 |

## 특히 먼저 확인할 누락

### 영구 저장소

Auto Mode는 StorageClass를 자동 생성하지 않는다. 자체 운영 서비스에 EBS PVC를 쓴다면 Auto Mode provisioner `ebs.csi.eks.amazonaws.com`에 맞춰 검토해야 한다. 후보는 암호화된 gp3와 `WaitForFirstConsumer`지만, 실제 용량·이름·기본 클래스 지정·reclaim 정책은 D04에서 결정한다. 기존 클러스터에 있는 StorageClass의 관리 주체도 먼저 확인한다. [AWS 공식 안내](https://docs.aws.amazon.com/eks/latest/userguide/create-storage-class.html)

### RDS CDC

기반 코드에는 논리 복제 파라미터 그룹이 없다. RDS에서는 `rds.logical_replication` 등 관련 설정·DB 권한이 필요하며 정적 파라미터 변경에는 재시작이 필요하다. 복제 slot이 유지하는 WAL은 용량 위험이 있으므로 관측·정리 책임을 함께 정한다. 이 계획에서 DB 재시작·계정 생성·publication/slot 생성은 수행하지 않는다. [AWS 공식 안내](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/PostgreSQL.Concepts.General.FeatureSupport.LogicalReplication.html)

Debezium의 캡처 범위와 RDS 준비 요건은 선택한 버전의 문서로 검토한다. 개인정보가 있는 테이블/컬럼을 제외하거나 변환하는 책임을 CDC 담당과 합의한다. Secret 공급과 커넥터 등록은 같은 작업으로 취급하지 않는다. [Debezium PostgreSQL 공식 안내](https://debezium.io/documentation/reference/stable/connectors/postgresql.html)

### Spark와 Airflow

Spark는 Kubernetes에서 driver/executor를 실행하는 방식이 있어 “Spark 설치”만으로 요구사항을 정의할 수 없다. 제출 주체, 이미지·서비스 계정·RBAC와 동시 실행량을 받아 실행 방식을 정한다. [Spark 공식 안내](https://spark.apache.org/docs/latest/running-on-kubernetes.html)

Airflow의 executor·metadata DB·DAG 전달·로그를 먼저 결정한다. 공식 Helm 문서는 운영용 외부 metadata DB와 Secret 참조를 안내한다. 기존 이커머스 RDS의 master 자격증명을 그대로 공유하거나 예제 내장 DB를 운영 기본값으로 채택하지 않는다. [Airflow 공식 안내](https://airflow.apache.org/docs/helm-chart/stable/production-guide.html)

## 자원 예산 입력 양식

현재 8 vCPU/32 GiB는 기반 NodePool의 한도이며 플랫폼 수용 보장이 아니다. 아래 항목을 채운 후 예약된 시스템 자원, 스케줄링 제약, 임시 잡·rollout 여유와 함께 검토한다. 한도를 이 계획에서 늘리지 않는다.

| 구분 | 최소/최대 Pod 또는 동시 잡 | Pod당 CPU/memory requests | 디스크·일 증가량·보존 | 실행 시간/교체 여유 |
|---|---|---|---|---|
| 시스템·기존 WEB/WAS | 기반 설정 및 배포 시 관찰 | 기반 설정 및 배포 시 관찰 | 로그 보존 미정 | HPA·surge 포함 |
| Kafka·Connect | 미정 | 미정 | 미정 | 상시/복구 요구 미정 |
| Consumer | 미정 | 미정 | checkpoint/출력 미정 | 종료·재처리 요구 미정 |
| Spark | 미정 | driver/executor별 미정 | shuffle/checkpoint 미정 | 동시 잡·수행 시간 미정 |
| Airflow | executor 확정 후 | 구성요소별 미정 | metadata/log 미정 | 동시 task 미정 |
| 관측 서비스 | 제품 확정 후 | 미정 | 지표/log 보존 미정 | 상시 요구 미정 |

견적은 선택한 서비스·버전·실제 리전 단가·가동 시간·보존량을 확인한 뒤 작성한다. 이전의 단일 NAT·Single-AZ 개발 가정을 현재 HA 기반이나 확장 플랫폼 견적으로 사용하지 않는다.
