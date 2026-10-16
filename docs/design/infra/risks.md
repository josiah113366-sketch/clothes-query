# 위험과 비용

상태: 제안 / 미정 · 2026-10-13 확인

## 위험 및 대응

| 우선순위 | 근거/위험 | 대응 |
|---|---|---|
| P0 | 실 AWS와 state 소유권 미확인 | bootstrap 포함 기배포 여부 확인 전 생성/교체 금지. 기존 state 보존 |
| P0 | Git 최신 원격 확인 실패 | 구현 전 최신 main/팀 브랜치 확인. 이번 분석은 bbe9fae 기준 |
| P0 | 실습 MySQL과 Git PostgreSQL 불일치 | RDS 엔진만 바꾸지 말고 SQL/드라이버/5432/Secret/DDL까지 일치시킴. 기존 RDS 교체 금지 |
| P0 | 실습 region/AZ 불일치, 다른 리전 이미지 | Tokyo/provider/AZ/ECR/실제 AWS를 함께 대조. 기존 리전 변경은 별도 계획 |
| P0 | Ingress web 참조, 실제 web-service | Service 이름/port/namespace와 nginx 연결을 정합화 |
| P1 | 실습 EKS API CIDR 0.0.0.0/0 및 광범위 admin | 제한 CIDR/사설 경로와 최소 RBAC. 인증 미설정이라는 의미는 아님 |
| P1 | 실습 RDS 삭제 보호 false, final snapshot 생략, 즉시 적용 | 보존/백업/유지보수 정책 결정 후 수정 |
| P1 | 실습 데이터 S3 force_destroy=true | false 및 필요시 보호 설정. state S3를 업무 데이터 버킷으로 사용하지 않음 |
| P1 | 실습 ECR force_delete=true, mutable tag | digest/불변 태그 및 롤백 이미지 보존 정책 |
| P1 | WAS GET /api/db가 데이터를 변경, 오류 원문 반환 | 읽기 전용 검증으로 대체, 민감 오류 응답 제한 |
| P1 | Secret 참조만 있고 공급·회전 미완성 | 비밀 관리 책임과 공급 도구/권한 결정. 앱에 DB master 권한 부여하지 않음 |
| P1 | member_archive에 PII 컬럼 존재 | 후속 CDC/레이크 공개 범위 제한. 테스트에도 실제 PII를 로그/문서로 남기지 않음 |
| P1 | 예제 Terraform root 단순 합치기 | 중복 리소스 주소·IAM/OIDC·backend key 방지, 스택별 소유권 명시 |
| P1 | backend 예시 이름에 계정 ID 포함 가능 | 공개 저장소 정책과 함께 검토. 실제 값은 비공개 backend 입력 방식으로 전달하는 방안 제안 |
| P2 | 예제 HPA/PDB/replica와 소형 노드 용량 불일치 | workload requests/limits, 최소/최대 replica, 노드 상한을 함께 검증 |

## 비용 추정

현재 AWS 사용량·실제 사양은 미확인이다. 다음은 **확정 견적이 아닌 개발 환경 예산 가정**이다. 도쿄, 월 730시간, 표준 지원 EKS 1개, 소형 노드 1~2개, NAT 1개, ALB 1개, 소형 Single-AZ PostgreSQL, 소량의 데이터/로그를 가정한다. 이 가정은 아키텍처 결정이 아니다.

| 항목 | 월 예산 가정(USD) | 근거 및 한계 |
|---|---:|---|
| EKS control plane | 73 | 공식 표준 지원 $0.10/시간 × 730 |
| 노드·EBS·Auto Mode 사용 시 추가 비용 | 40~120 | 용량 미정으로 잡은 예산 배분. 도쿄 특정 SKU 견적 아님 |
| NAT 및 관련 처리·주소 비용 | 35~55 | 저트래픽 가정의 예산 배분. NAT 수·대역폭 증가 시 초과 가능 |
| ALB·LCU·공인 주소 | 20~40 | 저트래픽 예산 배분. 요청/연결/바이트에 따라 변동 |
| RDS 및 스토리지 | 20~60 | 소형 Single-AZ 예산 배분. 엔진 버전·타입·백업·IO에 따라 변동 |
| S3/ECR/로그/비밀관리 등 | 10~40 | 보관량 및 요청량 미확정 |
| 합계 | 약 200~400 | 세금·환율·할인/크레딧 미반영. 대용량 전송 및 추가 endpoint 비용 제외 |

EKS 외 범위는 공식 SKU 단가에서 계산한 견적이 아니라 초기 예산 논의를 위한 추정치다. 배포 전 승인된 인스턴스·리전·가동시간·트래픽을 AWS Pricing Calculator에 넣어 다시 산정해야 한다. 기존 인프라를 재사용해도 해당 리소스의 지속 비용이 없어지는 것은 아니다.

EKS extended support는 $0.60/시간이므로 월 730시간 기준 $438로 증가한다. Auto Mode 관리 요금은 EC2 비용에 추가된다. 지원 버전과 모드를 선택할 때 확인한다. [AWS EKS 가격](https://aws.amazon.com/eks/pricing/)

실습은 NAT 2개와 Multi-AZ RDS이므로 위 개발 예산과 동일하게 계산하면 안 된다. NAT를 1개로 줄이는 안은 가용성 저하와 AZ 간 전송 경로를 검토해야 한다. Multi-AZ에서 Single-AZ로 낮추는 안은 장애 대응/복구 요구와 함께 결정한다. [VPC 가격](https://aws.amazon.com/vpc/pricing/), [RDS PostgreSQL 가격](https://aws.amazon.com/rds/postgresql/pricing/)

S3 Gateway Endpoint 자체에는 추가 요금이 없으며 S3 경로에서 NAT 처리를 줄일 수 있다. ECR/비밀관리 등의 interface endpoint는 별도 비용과 필요 서비스를 계산한다. ALB에는 시간 및 LCU 요금이 있어 단순히 로드밸런서 개수만으로 총액을 확정할 수 없다. [S3 Gateway Endpoint](https://docs.aws.amazon.com/vpc/latest/privatelink/vpc-endpoints-s3.html), [ELB 가격](https://aws.amazon.com/elasticloadbalancing/pricing/)

비용 통제 제안은 노드/replica 상한, 로그 보존 기간, ECR 이미지 보존, S3 lifecycle, 비용 알림이다. 예산 알림만으로 지출이 자동 중단되는 것으로 보지 않는다. Kafka/Spark/Airflow/AI는 이번 예산과 구축 범위에서 제외한다.
