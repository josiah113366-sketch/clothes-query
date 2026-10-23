# 작업 지시서: infra/ecs-simulator-backend

> 상태: 진행 중 · 브랜치: `infra/ecs-simulator-backend` (최신 `main`)

## 목표

`infra/stacks/ecs-simulator/deployment.backend.hcl`을 다른 스택처럼 Git으로 관리한다. #58(`infra/shared-deployment-config`)이 이 파일을 공유 대상으로 바꿨지만, ECS 스택은 별도 PR(#56)로 들어와 빠져 있었다. 리소스·state 변경은 없다.

## 만드는 것

- `infra/stacks/ecs-simulator/deployment.backend.hcl` (bucket, region. 다른 스택과 같은 값)
- 스택 README: "커밋 안 됨" 설명 정정, PowerShell 인자 따옴표

## 완료 확인

- [x] 다른 스택(`rds`)의 같은 파일과 bucket·region이 같다
- [x] `git check-ignore`가 이 파일을 무시하지 않는다(`.gitignore`의 `!infra/stacks/*/deployment.backend.hcl`)
- [x] 사용자가 이 파일로 `terraform init`·plan·apply를 실제로 했다(2026-10-22 시뮬레이터 재배포)

## 작업 결과

- **한 줄 요약:** ECS 스택 backend 설정 파일을 공유 설정에 편입
- **무엇을 만들었나:** 위 파일 1개, 스택 README 수정
- **확인한 결과:** 위 완료 확인 3개
- **알려진 한계·남은 일:** 없음
