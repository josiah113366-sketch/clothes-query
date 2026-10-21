# 작업 지시서: infra/ecs-simulator

> 상태: 진행 중 · 브랜치: `infra/ecs-simulator` (최신 `main`, `api/mvp` #44 머지 후) · 짝 작업: `sim/ecs-image`(이미지·실행 문서) · 이전 작업: `api/mvp`

## 목표

거래·회원 시뮬레이터를 **ECS Fargate 태스크 1개로 계속 실행**하는 Terraform 스택을 만든다. 시뮬레이터는 내부 ALB를 거쳐 업무 API로 쓰고 읽는다.

```
ECS Fargate 태스크 1개 (private app subnet, public IP 없음)
├─ controller : sim controller serve --incident-log s3   (데이터 오염만 RDS 직접)
├─ member     : sim member live      ─┐
├─ behavior   : sim behavior live    ─┼─ HTTP ─▶ 내부 ALB ─▶ API(EKS) ─▶ RDS / Kafka ─▶ S3
└─ 공유 볼륨 /control (control.json) ─┘
```

## 결정 (2026-10-21 사용자)

| 항목 | 결정 |
|---|---|
| 브랜치 | 인프라(`infra/ecs-simulator`)와 이미지(`sim/ecs-image`)를 나눈다 |
| apply | **사용자가 직접**(ECS 쪽 apply는 사용자가 맡기로 함). Claude는 plan까지 |
| 태스크 구성 | 태스크 1개, 같은 이미지 컨테이너 3개, 공유 볼륨으로 제어 파일 공유. 태스크를 나누는 안은 상태 공유 재설계 비용 때문에 제외 |
| 실행 방식 | Fargate **온디맨드**(Spot 아님). EC2 대신 Fargate(서버 관리 없음, 리뷰 시뮬레이터와 같은 패턴) |
| 네트워크 | private app subnet, public IP 없음. 컨트롤러 화면은 **ECS Exec 포트 포워딩**(로드밸런서 추가 없음) |
| 이미지 교체 | **Terraform apply**(`image_digest` 변수). 태스크 정의를 Terraform이 관리 |
| 데이터 오염 | **이번에 포함.** 오염 전용 DB 계정(`docs/design/api.md` 11절, `clothes_sim_admin`) 접속 문자열을 Secret으로 컨트롤러에만 |

## 만든 것

- `infra/modules/ecs-simulator/`: ECR `clothes-query-dev/simulator`(IMMUTABLE, 10개 보관), ECS 클러스터, SG(나가는 443·80·5432, 들어오는 규칙 없음),
  IAM 실행 역할(ECR·로그·Secret 1개 읽기), 태스크 역할(`ground_truth/incident_log/*` PutObject, ECS Exec SSM 채널), Secret(값 없음), 로그 그룹(14일).
  `image_digest`가 있을 때만 태스크 정의(0.5 vCPU / 1GB, 컨테이너 3개 essential, `initProcessEnabled`, 공유 볼륨)와 서비스(1개, min 0% / max 100%, ECS Exec).
- `infra/stacks/ecs-simulator/`: network·storage remote state, 비공개 입력(`state_bucket`, `image_digest`, `api_url`)은 Git 제외 파일.
- `infra/tests/ecs-simulator.tftest.hcl`: mock plan 5개.
- `infra/README.md`, `stacks/README.md`, `modules/README.md`에 한 줄씩.

## 이 브랜치에서 하지 않는 것 (레포 밖 비공개 입력, 사용자가 실행)

- rds `database_clients`(비공개 입력)에 이 스택 SG 추가 → rds apply
- API chart `runtime.local.yaml`의 `inboundCIDRs`를 app subnet 대역으로 → `helm upgrade`
- Dockerfile·오염 계정 SQL·실행 문서 → `sim/ecs-image`

## 완료 확인

- [x] `terraform fmt`, `validate`
- [x] mock plan 5개 통과(기반만 / 컨테이너 3개·공유 볼륨·컨트롤러에만 Secret·서비스 설정 / 잘못된 digest·태스크 2개·api_url 없음 거부)
- [x] 실제 plan(기반): 생성 14, 변경 0, 삭제 0
- [ ] 사용자 apply 1차(기반) → 이미지 push → apply 2차(태스크 정의·서비스) → 태스크 Running, 컨테이너 3개 재시작 0

## 작업 결과

(머지 전에 채운다)
