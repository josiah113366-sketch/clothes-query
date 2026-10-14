> **현재 구성(2026-10-14):** 이전 HA 결정을 변경했다. 워커·앱·RDS는 ap-northeast-1a 한 AZ, NAT 1개, RDS Single-AZ다. AWS 서비스 요구사항 때문에 두 AZ의 서브넷은 유지한다. WEB 2개/WAS HPA 2~3개는 유지한다. 아래의 이전 HA 설명보다 infra/SINGLE_AZ.md의 최신 결정을 우선한다.

# 배포 준비 현황

2026-10-14 기준. 실제 생성 테스트는 마지막에 수행한다. 코드 검증과 실환경 검증을 구분한다.

## 확정 및 검증한 범위

- 도쿄, 두 AZ, AZ별 NAT, private app/DB subnet, PostgreSQL Multi-AZ.
- EKS Auto Mode 1.36, custom NodePool 8 vCPU/32 GiB, On-Demand.
- WEB 2개, WAS HPA 2~3개·CPU 70%·축소 안정화 300초. [조절 방법](SCALING.md).
- ECR 두 저장소만 배포했다. S3 state 저장 및 후속 무변경 plan을 확인했다.
- network 최신 실제 plan(2026-10-14)은 NAT 1개 기준 21개 생성, 변경·삭제 없음이다. 아직 배포하지 않았다. 이전 23개 생성 계획은 대체되었으며 최종 배포 시 plan을 다시 만든다.
- 로컬 검증은 실제 클러스터의 CRD, 지표 수집, 스케줄링, 통신 성공을 보장하지 않는다.

## 남은 입력과 결정

| 단계 | 준비할 값 | 상태 |
|---|---|---|
| bootstrap | 최초 배포 PC의 local state 관리 위치·담당자 | 미확인. 기존 버킷을 다시 만들지 않는다 |
| 공통 | expected_account_id, state_bucket 및 backend 입력 | 실제 값은 Git 제외 파일에만 보관 |
| eks | 관리자 역할 ARN, 접근할 공인 IPv4 CIDR | 미정. 현재 인증 주체를 자동으로 관리자에 등록하지 않는다 |
| rds | PostgreSQL 16.15, 인스턴스 사양, 초기/최대 저장량 | 16.15·Single-AZ 유지. 사용자 요청으로 인스턴스 크기 결정 보류, 저장량 미확정 |
| storage | 전역 고유 업무 데이터 버킷 이름 | 미정. state 버킷과 별개 |
| apps 기초 | 업무 S3 prefix, Metrics Server 호환 버전 | prefix 예시는 application/. 최종 plan에서 버전 검토 |
| apps 서비스 | WEB/WAS 이미지 digest, 앱 전용 DB 계정 및 Secret | 미준비. 실제 앱 구현은 별도 작업 |
| HTTPS | 도메인, 도쿄 ACM 인증서, ALB 허용 CIDR, DNS 담당 | 미정 |
| 부하 테스트 | 목표 RPS, p95, 오류율, DB 연결 예산 | 미정. 현재 DB 직접 쓰기 제네레이터로 WAS HPA를 검증할 수 없음 |

RDS 사양은 고가용성 여부와 별개다. 작은 사양으로도 Multi-AZ를 선택할 수 있지만 처리량은 실측해야 한다. HPA가 늘리는 것은 WAS Pod이며 RDS 사양·저장량을 줄이는 기능은 없다. [시작 사양·비용 검토](../docs/design/infra/rds-sizing.md)를 참고한다.

## 마지막 실행 순서

1. 코드·실제 계정·state 소유권·기존 리소스를 대조하고 스택별 plan을 검토한다. 저장해 둔 이전 plan을 그대로 재사용하지 않는다.
2. network → eks → compute 순서로 준비한다. storage는 독립적이며 rds는 network/eks 출력 이후 준비한다. 각 단계의 실제 output이 생긴 다음 종속 plan을 실행한다.
3. apps 기초 배포에서 Namespace/Pod Identity/ConfigMap과 Metrics Server를 준비한다. 기존 Metrics Server 설치 여부와 관리 주체를 먼저 확인한다.
4. 앱 전용 DB 계정·schema·Secret을 준비한다. DB master 자격증명을 앱에 전달하지 않는다. 비밀값을 Terraform state에 넣지 않는다.
5. 이미지 digest·인증서·도메인 입력 후 apps 서비스 배포를 검토한다. WEB→WAS→DB/S3, HTTPS, DB TLS와 failover 재연결을 확인한다.
6. Metrics Server와 HPA 상태, API 부하에 따른 WAS 2→3→2, 노드 변화, 후속 plan의 replica 비간섭을 확인한다.

apply/import/state 변경은 이 문서 작성이나 정적 검사에 포함되지 않는다. 단계별 실제 결과가 나온 뒤 다음 단계로 진행한다. 상세 명령은 [실행 안내](IMPLEMENTATION.md)를 따른다.
