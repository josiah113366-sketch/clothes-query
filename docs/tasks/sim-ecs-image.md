# 작업 지시서: sim/ecs-image

> 상태: 진행 중 · 브랜치: `sim/ecs-image` (최신 `main`, `api/mvp` #44 머지 후) · 짝 작업: `infra/ecs-simulator`(ECS Terraform) · 다음 작업: `sim/console`

## 목표

시뮬레이터를 ECS Fargate 태스크 1개(컨테이너 3개)로 돌릴 **이미지와 실행 절차**를 만든다. 결정 사항은 `docs/tasks/infra-ecs-simulator.md` "결정" 표와 같다(태스크 1개·컨테이너 3개, 온디맨드, ECS Exec 포트 포워딩, Terraform apply로 이미지 교체, 데이터 오염 포함).

## 만든 것

- `simulator/Dockerfile`: 베이스 digest 고정(`api/Dockerfile`과 같은 python:3.12-slim), 비root(10001), RDS CA 묶음(sha256 고정, 데이터 오염 `sslmode=verify-full`용), `/control`을 비root 소유 `VOLUME`으로(ECS 공유 볼륨에서 control.json 쓰기)
- `simulator/.dockerignore`: `.env`, `.local`(PII 시드), `.venv`, 테스트 등을 빌드 컨텍스트에서 제외
- `simulator/deploy/sql/sim-admin-account.sql`: 오염 전용 계정 `clothes_sim_admin`(orders SELECT·UPDATE, payments SELECT·INSERT, 연결 한도 3). 오염 코드에 행 잠금이 없어 이 권한으로 충분하다
- `simulator/README.md` "ECS에서 실행": 기반 apply → 오염 계정·Secret → RDS 허용 → 이미지 push → 태스크 apply → API ALB 대역 좁히기, 확인, 컨트롤러 화면 터널

코드(src/) 변경은 없다. 컨테이너별 명령·환경 변수는 `infra/modules/ecs-simulator`의 태스크 정의에 있다.

## 완료 확인

- [x] 로컬 `docker build --platform linux/amd64` 성공, `sim --help`, 비root(10001)로 볼륨 `/control`에 쓰기, CA 파일 존재
- [ ] ECS: 컨테이너 3개 RUNNING·재시작 0, 로그에 가입·방문·주문·클릭, 오류 없음
- [ ] 15분 안에 S3 bronze `clickstream`·`orders`·`payments`·`members-events`·`order-items` 새 파일
- [ ] 컨트롤러 화면(포트 포워딩)에서 모드 전환 → 정답표가 S3 `ground_truth/incident_log/`에 생김, member·behavior 로그에 `mode: normal → …`
- [ ] 데이터 오염 1회(작은 count) → 정답표·DB 반영
- [ ] (ECS 후 할 일) S3 Sink 5분 주기 변경 후 `lag_sec` 정상 최대치·burst 중 최대치 측정 → Gold B 담당에게 전달

## 작업 결과

(머지 전에 채운다)
