# 작업 지시서: sim/review-ecs

> 상태: 진행 전 · 브랜치: `sim/review-ecs` · 다음 작업: `실 DB 데이터(제품/거래)와 직접적인 연계 작업(sim/review-transaction-import)`

## 목표

리뷰 시뮬레이터를 로컬 PC 에서 AWS ECS 로 옮겨 실행하고, 배포와 실행을 스크립트로 반복할 수 있게 한다.
실행할 때 옵션으로 특정 상품의 긍정·부정 리뷰 비율을 올리거나, 직접 쓴 리뷰를 넣을 수 있게 한다.

## 먼저 읽을 것

- 루트 `CLAUDE.md`, `review-simulator/CLAUDE.md`
- `docs/tasks/sim-review-product-import.md` (이전 브랜치)
- `review-simulator/README.md` (주문 기반 실행, `rsim inject`, 컨테이너로 실행), `review-simulator/Dockerfile`
- `docs/design/infra/deployment_plan.md`, `infra/stacks/` (ecr, compute, apps)
- `review-simulator/data/incidents.example.json` (특정 상품·카테고리 불만 급증 시나리오, 이미 있는 기능)

## 이번 작업의 특례 (사용자 결정, 다른 문서보다 우선)

- 현재 branch에서는 기능을 변경하지 않고 local/ECS 기능을 모두 동일하게 유지하면서 진행한다.
- ECS 시뮬레이터의 상황(비용/상태)을 확인할 수 있는 관제 환경 구성까지 포함한다.


## 시작 전 확인 (Claude가 한다)

- `sim/review-product-import` PR 이 main 에 합쳐졌는지, 새 브랜치를 최신 main 에서 만들었는지
- 민감정보는 script 활용하여 AWS Secret Manager 통해 관리하도록 구성

## 만드는 것

### 1. ECS 로 시뮬레이터 이관
- ECR에 소스 등록하여 관리
- 시뮬레이터 버전 간 기능 차이점 등을 담는 md 파일 작성/갱신 - 패치노트 형식

### 2. 배포 스크립트 작성
- Bedrock API 와 같은 민감정보 등록/갱신을 위한 Secret 주입 script
- 상태 조정을 위한 On/Off script
- 모드 조정을 위한 switch script
- 배포를 담당하는 deploy script

### 3. 실행 옵션이 담긴 스크립트 작성
- 특정 상품에 대한 긍정·부정 리뷰 비율 올리기
- 직접 쓴 리뷰 넣기 (`rsim inject`)

## 만들지 않는 것

- git commit (사람의 확인을 받고 commit 단위가 되었다고 판단될 때 commit 메시지 제안만 한다)
- (항목 → 이후 브랜치)

## 작업 순서

1. 시작 전 확인을 하고, **계획을 먼저 제시해 사용자 확인을 받는다**
2. (단계)
3. "완료 확인"을 실행하고 결과 보고

## 완료 확인

아래를 **실제로 실행**해서 결과를 보고한다.

- [ ] `ruff check . && ruff format --check .`
- [ ] `pytest`
- [ ] (필요 시 채우기)

## README 갱신

- `review-simulator/README.md`
- (필요 시 채우기)
