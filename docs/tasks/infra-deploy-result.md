# 최소 EKS/Kafka 배포 결과

상태: 완료 (최소 기반 배포·접속·TLS 메시지·스토리지·지표 검증 범위) · 2026-10-16 · 브랜치 infra/deploy-result

## 요청과 범위

사용자가 PR 머지 후 배포를 요청했다. PR #11을 최신 main과 통합하고 CI 전체 성공 후 main의 `6ef728e`로 머지했다. AWS 계정 guard·현재 PC IP·관리자 trust·EKS 1.36 표준 지원을 확인하고 검토한 저장 plan으로 NAT/EKS/compute를 적용했다. 기존 RDS·S3/ECR·state 버킷은 보존했다. 이번 명시적 사용자 요청은 일반적인 apply 담당 규칙을 영구 변경하지 않는다.

Airflow는 동료가 설치할 namespace까지만 준비한다. 동료 IAM 역할/IP는 아직 없다는 사용자 답에 따라 본인 관리자 접속만 유지했다. Airflow runtime·Connect·업무 CDC·S3 Sink·Fargate·WEB/WAS·ALB·Spark·업무 IAM은 배포하지 않았다. 팀원의 데이터/DAG 코드를 대신 구현하지 않는다.

## 실제 생성과 검증

| 항목 | 결과 |
|---|---|
| network | NAT/EIP 각 1개 추가, app route table 2개 변경, 삭제 0. NAT available·network 후속 plan 변경 없음 |
| EKS | 1.36 Auto Mode ACTIVE, 17개 리소스 생성·삭제 0. 기본 system/general-purpose NodePool은 비활성 |
| 접속 | 전용 관리자 역할 assume 및 실제 kubectl namespace 조회 성공. 전역 kubeconfig를 덮어쓰지 않고 Git 제외 `.cache/eks-kubeconfig.private` 생성 |
| compute | NodeClass/NodePool 2개 생성·삭제 0. 허용 타입 t3a.large, On-Demand, 한도 6 vCPU/24GiB·consolidation 10분. EKS/compute 후속 실제 plan 변경 없음 |
| 노드 | t3a.large 한 대, ap-northeast-1a, Ready/running, public IPv4 없음. 같은 계정에서 t3a.large는 현재 이 AZ만 제공 확인 |
| 노드 디스크 | 암호화 gp3 4GiB + 80GiB. Kafka PVC와 별도 |
| Kafka | Strimzi 1.3.0, Kafka 4.3.1. broker/controller 1개·RF 1·보관 72시간, synthetic infra-smoke 토픽·TLS 클라이언트 생성 |
| Kafka 스토리지 | 암호화 gp3 20GiB, Bound/in-use, ap-northeast-1a, Retain |
| Pod | broker·entity operator·cluster operator·Kafka exporter 4개 Pod 모두 Running/Ready, restart 0 |
| 메시지 | 별도 infra-probe namespace에서 실제 mTLS·hostname 확인 설정으로 synthetic 메시지 생산·소비 성공. 검사 중 노드 1대 유지 |
| 지표 | JMX HTTP 응답과 kafka_ 지표 65개 확인. kubelet stats/summary 조회 성공. 장기 수집 서버·대시보드·알림은 미설치 |
| 임시 자원 | 검사 client Pod와 infra-probe에 복사한 TLS Secret 모두 정리. 측정용 토픽/User와 Kafka는 유지 |
| Airflow | airflow namespace 생성. runtime·메타데이터 DB·API URL·동료 권한은 미구성 |

명시한 source 값·서비스 이름은 공개 가능한 운영 계약이며 실제 계정 ID·ARN·API endpoint·IP·CA/클라이언트 비밀키·Terraform plan 상세는 Git 제외 파일에만 보관한다. Helm은 공식 체크섬으로 고정한 3.19.0 portable binary, kubectl은 1.36.1을 사용했다.

## 자원 관측과 비용

실제 메시지 검사 직후 한 번의 stats/summary에서 노드 CPU 약 0.679 vCPU, memory working set 약 1.619GiB였다. 검사 client 종료 직전 CPU가 포함된 순간 표본이며 평시·피크·지속 처리량이나 전체 플랫폼 수용 보장이 아니다. 이때 broker memory 약 389.6MiB, entity operator 355.3MiB, cluster operator 272.8MiB였다.

도쿄 공개 단가·월 730시간·세금/크레딧 제외 기준: EKS $73 + t3a.large/Auto Mode $80.0445 + NAT/IPv4 $48.91 + RDS 20GiB 포함 $39.26 + Kafka EBS 20GiB $1.92 + 노드 EBS 84GiB $8.064 = **약 $251.20/월**. S3/ECR·Secret·로그·추가 백업·NAT 처리·AZ/외부 전송·CPU credit·Fargate 등은 별도다. 노드 추가 시 EC2/Auto Mode와 노드 디스크 비용도 증가한다. 6 vCPU/24GiB는 세 대분의 명목 한도이며 동시 provisioning 중 일시 초과 가능하다. vCPU quota 읽기는 AccessDenied였으며 한 대 실제 생성만 확인했다.

근거: [EKS 요금](https://aws.amazon.com/eks/pricing/), [도쿄 EC2 가격표](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/ap-northeast-1/index.json), [도쿄 RDS 가격표](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonRDS/current/ap-northeast-1/index.json).

## 동료 인수인계와 다음 작업

- Airflow 담당: 운영 버전/Executor/Auth Manager·Helm values·메타데이터 DB/전용 계정·DAG 이미지/코드·자원 요구를 준비한다. 현재의 로컬 3.3.2+LocalExecutor 테스트는 운영 확정이 아니다.
- 인프라 담당: 동료 IAM role ARN과 접속 IPv4 /32를 받으면 airflow namespace 범위의 배포 권한·API 접속 경로를 준비한다. 전체 관리자 공유를 기본값으로 쓰지 않는다.
- 판정 담당: 실제 Athena DB/table/SQL·workgroup·source/결과 prefix, reprocess_events 추가 읽기 조회·처리 기준·기대 결과를 제공한다. 그 입력으로 IAM을 분리하고 실측한다.
- 제네레이터/CDC/Sink: Fargate Task SG·DB 계정/DDL/TLS, 캡처 allowlist·slot/publication/WAL 예산, 업무 토픽/ACL·S3 Sink 이미지/역할을 연결한다. 현재 synthetic Kafka 성공을 전체 RDS→Kafka→S3 성공으로 표시하지 않는다.
- 정답표 ground_truth/incident_log/ JSON과 조사 에이전트 gold_b/ 전용 읽기는 계약만 확정됐다. 실제 역할 분리·거부 테스트는 후속이다.
- Kafka/RDS는 단일 장애 지점이 있다. 실제 노드 교체·EBS 재연결·72시간 경과/디스크 포화·장기 부하·CPU credits·경보·전체 Airflow 동시 배치는 미검증이다.

## 작업 결과

비용 축소 코드를 실제 AWS에 적용해 동료가 후속 서비스를 설치할 EKS 기반과 Kafka 측정 환경을 만들었다. PR #11 머지·NAT/EKS/compute apply·후속 변경 없음 plan·관리자 접속·private t3a.large 1대·Kafka 20GiB/TLS 메시지·JMX·임시 자원 정리를 확인했다. 실행 코드 변경 없이 현재 상태·비용·접속·미완료 경계를 문서에 반영한다. Airflow 및 업무 경로는 위 입력을 받은 뒤 연결하고 실제 작업으로 추가 실측한다.
